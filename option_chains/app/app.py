from flask import Flask
from flask import render_template, redirect, url_for, request
from collections import defaultdict

import pyetrade
from option_chains import options_manager, constants
import logging
import datetime
from pprint import pprint

global oauth_object
global oauth_token
global oauth_secret


app = Flask(__name__)


@app.route("/login")
def login():
    global oauth_object

    oauth_object = pyetrade.ETradeOAuth(
        constants.CONSUMER_KEY, constants.CONSUMER_SECRET
    )
    return render_template("login.html", url=oauth_object.get_request_token())


@app.route("/auth", methods=["POST"])
def auth():
    verification_token = request.form["verificationToken"]

    tokens = oauth_object.get_access_token(verification_token)

    global oauth_token
    global oauth_secret
    oauth_token = tokens["oauth_token"]
    oauth_secret = tokens["oauth_token_secret"]

    return redirect(url_for("index"))


@app.route("/", methods=["GET", "POST"])
def index():
    if "oauth_token" not in globals():
        return redirect(url_for("login"))

    # do work

    print(request.form)

    defaults = {
        "ticker": "GOOG",
        "min_strike": 0.3,
        "max_strike": 0.2,
        "increment": 100,
        "lookahead": 3,
        "contracts": 1,
    }

    manager = options_manager.OptionsManager(
        consumer_key=constants.CONSUMER_KEY,
        consumer_secret=constants.CONSUMER_SECRET,
        oauth_token=oauth_token,
        oauth_secret=oauth_secret,
    )

    ticker = request.form.get("ticker", defaults["ticker"])
    min_strike = float(request.form.get("min_strike", defaults["min_strike"]))
    max_strike = float(request.form.get("max_strike", defaults["max_strike"]))
    result = manager.get_options_info(
        ticker=ticker,
        min_strike=min_strike,
        max_strike=max_strike,
        increment=int(request.form.get("increment", defaults["increment"])),
        month_look_ahead=int(request.form.get("lookahead", defaults["lookahead"])),
        hide_no_contracts=True,
        hide_no_interest=True,
        contracts_to_buy=int(request.form.get("contracts", defaults["contracts"])),
    )

    options_dict = defaultdict(list)
    for option_info in result:
        options_dict[option_info["expiryDate"]].append(option_info)

    options_dict = {
        key: sorted(value, key=lambda d: d["strikePrice"])
        for key, value in options_dict.items()
    }

    # get market price to use in general stock info
    market_price = round(manager.get_market_price(ticker), 2)
    # turn percentages into actual strike prices to use in general stock info
    max_strike = int(float(market_price) * (1 - max_strike))
    min_strike = int(float(market_price) * (1 - min_strike))

    return render_template(
        "index.html",
        options=options_dict,
        prior_form=dict(request.form),
        defaults=defaults,
        valid_increments=options_manager.VALID_INCREMENTS,
        market_price=market_price,
        max_strike=max_strike,
        min_strike=min_strike,
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8008)
