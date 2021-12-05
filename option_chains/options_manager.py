import collections

import pyetrade
import numpy as np
import datetime
import typing
import logging

import requests.exceptions
from tenacity import (
    retry,
    stop_after_attempt,
    retry_if_exception_type,
    wait_exponential,
)

log = logging.getLogger(__name__)
VALID_INCREMENTS = [0, 5, 10, 50, 100]
PUT_INFO_TO_INCLUDE = [
    "bid",
    "ask",
    "lastPrice",
    "volume",
    "openInterest",
    "OptionGreeks",
    "strikePrice",
    "symbol",
    "optionType",
]


class OptionsManager:
    def __init__(
        self,
        consumer_key: str,
        consumer_secret: str,
        oauth_token: str,
        oauth_secret: str,
    ):
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.oauth_token = oauth_token
        self.oauth_secret = oauth_secret

        self.market = pyetrade.ETradeMarket(
            self.consumer_key,
            self.consumer_secret,
            self.oauth_token,
            self.oauth_secret,
            dev=False,
        )

        self.accounts = pyetrade.ETradeAccounts(
            self.consumer_key,
            self.consumer_secret,
            self.oauth_token,
            self.oauth_secret,
            dev=False,
        )

    def get_options_info(
        self,
        ticker: str,
        min_strike: float = 0.3,
        max_strike: float = 0.2,
        increment: int = 10,
        month_look_ahead: int = 3,
        hide_no_contracts: bool = True,
        hide_no_interest: bool = True,
        contracts_to_buy: int = None,
    ):
        assert (
            0 < max_strike < 1.0
        ), "max strike should be expressed as a percentage below market price (> 0 and < 1.0)"
        assert (
            0 < min_strike < 1.0
        ), "min strike should be expressed as a percentage below market price (> 0 and < 1.0)"
        assert (
            min_strike > max_strike
        ), "strikes should be expressed as a percentage below market price (and thus min_strike must be > max_strike)"
        assert (
            increment in VALID_INCREMENTS
        ), f"increment should be one {VALID_INCREMENTS}"

        mkt_price = self.get_market_price(ticker)
        max_strike = int(mkt_price * (1 - max_strike))
        min_strike = int(mkt_price * (1 - min_strike))
        log.info(
            f"Restricting strike price to ({min_strike}, {max_strike}) for {mkt_price} market price."
        )

        valid_expiry_dates = self.get_expiry_dates(ticker, month_look_ahead)
        log.info(f"Restricting search to {len(valid_expiry_dates)} valid expiry dates.")

        valid_strikes = [
            strike
            for strike in range(min_strike, max_strike)
            if strike % increment == 0
        ]

        valid_puts = []
        for date in valid_expiry_dates:
            option_pairs_for_date = self.market.get_option_chains(
                underlier=ticker, expiry_date=date
            )["OptionChainResponse"]["OptionPair"]
            for option_pair in option_pairs_for_date:
                put = option_pair["Put"]
                if int(float(put["strikePrice"])) in valid_strikes:
                    put = {
                        key: value
                        for key, value in put.items()
                        if key in PUT_INFO_TO_INCLUDE
                    }
                    put["expiryDate"] = date
                    put["marketPrice"] = mkt_price
                    valid_puts.append(put)

        log.info(
            f"Found {len(valid_puts)} options for specified expiry dates and strikes."
        )

        if hide_no_contracts:
            check = lambda put: int(put["volume"]) != 0
            invalid_puts = [put for put in valid_puts if not check(put)]
            valid_puts = [put for put in valid_puts if check(put)]
            if invalid_puts:
                log.info(f"Hiding {len(invalid_puts)} puts due to no volume.")

        if hide_no_interest:
            check = lambda put: int(put["openInterest"]) != 0
            invalid_puts = [put for put in valid_puts if not check(put)]
            valid_puts = [put for put in valid_puts if check(put)]
            if invalid_puts:
                log.info(f"Hiding {len(invalid_puts)} puts due to no open interest.")

        log.info(f"Returning {len(valid_puts)} valid options.")

        return [self.process_put_object(put, contracts_to_buy) for put in valid_puts]

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=0.1),
        retry=retry_if_exception_type(requests.exceptions.HTTPError),
    )
    def get_market_price(self, ticker: str) -> float:
        all_data = self.market.get_quote([ticker])["QuoteResponse"]["QuoteData"]["All"]
        return sum([float(all_data["bid"]), float(all_data["ask"])]) / 2

    def get_expiry_dates(self, ticker: str, month_look_ahead: int = 3):
        dates = self.market.get_option_expire_date(underlier=ticker)[
            "OptionExpireDateResponse"
        ]["ExpirationDate"]
        monthly_dates = [date for date in dates if date["expiryType"] == "MONTHLY"]
        return [
            datetime.date(
                year=int(date["year"]), month=int(date["month"]), day=int(date["day"])
            )
            for date in monthly_dates[:month_look_ahead]
        ]

    def process_put_object(self, put: typing.Dict, contracts_to_buy: int):
        put["belowMarketPct"] = round(
            (float(put["marketPrice"]) - float(put["strikePrice"]))
            / float(put["marketPrice"]),
            2,
        )

        auxiliary_info = {}

        contracts_to_buy = (
            min(contracts_to_buy, int(put["volume"]))
            if contracts_to_buy
            else int(put["volume"])
        )
        auxiliary_info["contractsToBuy"] = contracts_to_buy

        contract_price = sum([float(put["bid"]), float(put["ask"])]) / 2
        num_underlying_shares = 100 * contracts_to_buy
        revenue = contract_price * num_underlying_shares
        auxiliary_info["revenue"] = round(revenue, 2)

        days_to_hold = put["expiryDate"] - datetime.date.today()
        annualize_factor = 365 / days_to_hold.days
        auxiliary_info["annualizedRevenue"] = int(revenue * annualize_factor)

        auxiliary_info["annualizedReturn"] = round(
            ((revenue / float(put["strikePrice"])) * annualize_factor / 100), 2
        )

        put["auxiliaryInfo"] = auxiliary_info
        return put
