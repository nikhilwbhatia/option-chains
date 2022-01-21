import datetime
import logging
import pathlib
import typing
from dataclasses import dataclass
from multiprocessing.dummy import Pool as ThreadPool

import pandas as pd
import pyetrade
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)
VALID_INCREMENTS = [1, 2.5, 5, 10, 50, 100]
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
    company_name: str
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

    def get_csv_df(self):
        sector_path = pathlib.Path(__file__).parent / "data" / "sectors.csv"
        csv_df = pd.read_csv(sector_path)
        csv_df.fillna("", inplace=True)
        return csv_df

    def get_all_options_info(
        self,
        sector="Communication Services",
        sub_sector="Comm - Media & Ent",
        percentile_of_52_range: int = 25,
        min_strike: float = 30,
        max_strike: float = 20,
        month_look_ahead: int = 3,
        min_volume: int = 1,
        min_open_interest: int = 1,
        min_annualized_return: float = 0.0,
        include_next_earnings_date: bool = True,
    ):
        csv_df = self.get_csv_df()

        # filter csv_df down by sector
        csv_df = csv_df.loc[csv_df["Sector"] == sector]

        # filter csv_df down by sub-sector (if any)
        if sub_sector:
            csv_df = csv_df.loc[csv_df["Sub-Sector"] == sub_sector]

        # skip some buggy tickers
        skip = ["NVR", "KSU"]
        tickers = [ticker for ticker in csv_df["Ticker"].unique() if ticker not in skip]

        def helper(ticker):
            market_data = self.get_market_data(ticker)
            range_52 = market_data.high_52 - market_data.low_52
            if (
                (market_data.market_price - market_data.low_52) / range_52
            ) * 100 > percentile_of_52_range:
                return pd.DataFrame()

            options_info = self.get_options_info(
                ticker=ticker,
                min_strike=min_strike,
                max_strike=max_strike,
                increment=1,
                month_look_ahead=month_look_ahead,
                min_volume=min_volume,
                min_open_interest=min_open_interest,
                min_annualized_return=min_annualized_return,
                include_next_earnings_date=include_next_earnings_date,
            )
            data = []
            for option in options_info:
                option_data = {}
                for key, value in option.items():
                    if not isinstance(value, dict):
                        option_data[key] = value
                    elif key == "auxiliaryInfo":
                        for inner_key, inner_val in value.items():
                            option_data[inner_key] = inner_val
                data.append(option_data)
            return pd.DataFrame(data)

        thread_pool = ThreadPool(5)

        results = thread_pool.map(helper, tickers)
        df = pd.concat(results)

        if not df.empty:
            # add sector and sub-sector columns to final df
            ticker_to_sector = dict(zip(csv_df["Ticker"], csv_df["Sector"]))
            ticker_to_sub_sector = dict(zip(csv_df["Ticker"], csv_df["Sub-Sector"]))
            df["sector"] = df["symbol"].map(ticker_to_sector)
            df["sub_sector"] = df["symbol"].map(ticker_to_sub_sector)

        return df

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=0.2),
        reraise=True,
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
        include_next_earnings_date: bool = True,
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
        log.debug(f"Finding options for ticker: {ticker}")

        market_price = self.get_market_data(ticker).market_price

        # convert min and max strike from percentage to decimal
        max_strike = int(market_price * (1 - (max_strike / 100)))
        min_strike = int(market_price * (1 - (min_strike / 100)))
        log.debug(
            f"Restricting strike price to ({min_strike}, {max_strike}) for {market_price} market price."
        )

        valid_expiry_dates = self.get_expiry_dates(
            ticker, month_look_ahead, include_next_earnings_date
        )
        log.debug(
            f"Restricting search to {len(valid_expiry_dates)} valid expiry dates."
        )

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

        log.debug(
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
            log.debug(f"Hiding {len(invalid_puts)} puts due to min volume filter.")

        # filter based on min open interest
        check = lambda put: int(put["openInterest"]) >= min_open_interest
        invalid_puts = [put for put in valid_puts if not check(put)]
        valid_puts = [put for put in valid_puts if check(put)]
        if invalid_puts:
            log.debug(
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
            log.debug(
                f"Hiding {len(invalid_puts)} puts due to min annualized return filter."
            )

        log.info(f"Found {len(valid_puts)} valid options for ticker {ticker}.")

        return valid_puts

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=0.1),
        reraise=True,
    )
    def get_market_data(self, ticker: str) -> MarketData:
        all_data = self.market.get_quote([ticker], require_earnings_date=True)[
            "QuoteResponse"
        ]["QuoteData"]["All"]
        return MarketData(
            ticker=ticker,
            company_name=str(all_data["companyName"]),
            market_price=sum([float(all_data["bid"]), float(all_data["ask"])]) / 2,
            high_52=float(all_data["high52"]),
            low_52=float(all_data["low52"]),
            beta=float(all_data["beta"]),
            next_earnings_date=str(all_data["nextEarningDate"]),
        )

    def get_expiry_dates(
        self,
        ticker: str,
        month_look_ahead: int = 3,
        include_next_earnings_date: bool = True,
    ):
        dates = self.market.get_option_expire_date(underlier=ticker)[
            "OptionExpireDateResponse"
        ]["ExpirationDate"]
        monthly_dates = [date for date in dates if date["expiryType"] == "MONTHLY"]
        return [
            datetime.date(
                year=int(date["year"]), month=int(date["month"]), day=int(date["day"])
            )
            for date in monthly_dates[
                0 if include_next_earnings_date else 1 : month_look_ahead
            ]
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
        print(put["expiryDate"])
        print(datetime.date.today())
        print(days_to_hold)
        print(days_to_hold.days)
        annualize_factor = (365 / days_to_hold.days) if days_to_hold.days > 0 else 0
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
