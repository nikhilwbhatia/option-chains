import datetime
import logging
import typing
from dataclasses import dataclass

import pyetrade
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)
VALID_INCREMENTS = [0, 2.5, 5, 10, 50, 100]
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
    "netChange",
]


@dataclass
class MarketData:
    ticker: str
    market_price: float
    high_52: float
    low_52: float
    beta: float
    next_earnings_date: str


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
        min_strike: float = 30,
        max_strike: float = 20,
        increment: float = 10,
        month_look_ahead: int = 3,
        min_volume: int = 1,
        min_open_interest: int = 1,
        min_annualized_return: float = 0.0,
        contracts_to_buy: int = None,
    ):
        assert (
            0 < max_strike < 100
        ), "max strike should be expressed as a percentage below market price (> 0 and < 100)"
        assert (
            0 < min_strike < 100
        ), "min strike should be expressed as a percentage below market price (> 0 and < 100)"
        assert (
            min_strike > max_strike
        ), "strikes should be expressed as a percentage below market price (and thus min_strike must be > max_strike)"
        assert (
            increment in VALID_INCREMENTS
        ), f"increment should be one {VALID_INCREMENTS}"

        market_price = self.get_market_data(ticker).market_price

        # convert min and max strike from percentage to decimal
        max_strike = int(market_price * (1 - (max_strike / 100)))
        min_strike = int(market_price * (1 - (min_strike / 100)))
        log.info(
            f"Restricting strike price to ({min_strike}, {max_strike}) for {market_price} market price."
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
                    put["marketPrice"] = market_price
                    valid_puts.append(put)

        log.info(
            f"Found {len(valid_puts)} options for specified expiry dates and strikes."
        )

        # augment put objects with custom calculated fields
        valid_puts = [
            self.process_put_object(put, contracts_to_buy) for put in valid_puts
        ]

        # filter based on min volume
        check = lambda put: int(put["volume"]) >= min_volume
        invalid_puts = [put for put in valid_puts if not check(put)]
        valid_puts = [put for put in valid_puts if check(put)]
        if invalid_puts:
            log.info(f"Hiding {len(invalid_puts)} puts due to min volume filter.")

        # filter based on min open interest
        check = lambda put: int(put["openInterest"]) >= min_open_interest
        invalid_puts = [put for put in valid_puts if not check(put)]
        valid_puts = [put for put in valid_puts if check(put)]
        if invalid_puts:
            log.info(
                f"Hiding {len(invalid_puts)} puts due to min open interest filter."
            )

        # filter based on min annualized return
        check = (
            lambda put: float(put["auxiliaryInfo"]["annualizedReturn"])
            >= min_annualized_return
        )
        invalid_puts = [put for put in valid_puts if not check(put)]
        valid_puts = [put for put in valid_puts if check(put)]
        if invalid_puts:
            log.info(
                f"Hiding {len(invalid_puts)} puts due to min annualized return filter."
            )

        log.info(f"Returning {len(valid_puts)} valid options.")

        return valid_puts

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=0.1),
        reraise=True,
    )
    def get_market_data(self, ticker: str) -> MarketData:
        all_data = self.market.get_quote([ticker])["QuoteResponse"]["QuoteData"]["All"]
        return MarketData(
            ticker=ticker,
            market_price=sum([float(all_data["bid"]), float(all_data["ask"])]) / 2,
            high_52=float(all_data["high52"]),
            low_52=float(all_data["low52"]),
            beta=float(all_data["beta"]),
            next_earnings_date=str(all_data["nextEarningDate"]),
        )

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
            / float(put["marketPrice"])
            * 100,
            1,
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

        # (revenue / (strike * 100)) * annualize factor * 100 -- 100s cancel (expressed as %)
        auxiliary_info["annualizedReturn"] = round(
            ((revenue / float(put["strikePrice"])) * annualize_factor), 2
        )

        auxiliary_info["notionalPrinciple"] = round(
            float(put["strikePrice"]) * 100 * contracts_to_buy
        )

        put["auxiliaryInfo"] = auxiliary_info
        return put
