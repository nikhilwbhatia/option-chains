import pyetrade
import numpy as np


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

    def get_option_info(
        self,
        consumer_key: str,
        consumer_secret: str,
        oauth_token: str,
        oath_secret: str,
        ticker: str,
        min_percent: float,
        max_percent: float,
        increment: float,
    ):
        print("hi")

    def get_market_price(self, ticker: str) -> float:
        all_data = self.market.get_quote([ticker])["QuoteResponse"]["QuoteData"]["All"]
        return sum([float(all_data["bid"]), float(all_data["ask"])]) / 2
