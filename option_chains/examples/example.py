import pyetrade
from option_chains import options_manager, constants
import logging
import datetime
import pprint
from flask import request

logging.basicConfig(level=logging.INFO)


def main():

    # oauth = pyetrade.ETradeOAuth(constants.CONSUMER_KEY, constants.CONSUMER_SECRET)
    # print(oauth.get_request_token())  # Use the printed URL
    #
    # verifier_code = input("Enter verification code: ")
    # tokens = oauth.get_access_token(verifier_code)
    #
    # print("\nCopy the following 4 values into the manager's arguments:")
    # print(constants.CONSUMER_KEY)
    # print(constants.CONSUMER_SECRET)
    # print(tokens["oauth_token"])
    # print(tokens["oauth_token_secret"])

    manager = options_manager.OptionsManager(
        consumer_key="a694bf19a1a7ee1724e35a21e626bffe",
        consumer_secret="c52c35186ec76bcbe37e308e2e37d942e179dc07921efb3c79094b525785dd25",
        oauth_token="9KHoaNu/329QDTUWn9hMQ7L8fCkD/V42uQ/EgT4WmX8=",
        oauth_secret="wURP9wwdYMlLeauOvzrI/OpaHgKNE/r7W38rRoDNop4=",
    )

    print(manager.get_market_price("GOOG"))

    pprint.pprint(
        manager.get_options_info(
            ticker="GOOG",
            percent_below_mkt=0.05,
            percent_above_mkt=0.1,  # all arguments below have defaults and don't need to be passed
            increment=100,
            month_look_ahead=3,
            hide_no_contracts=True,
            hide_no_interest=True,
            contracts_to_buy=1,  # defaults to max available
        )
    )


if __name__ == "__main__":
    main()
