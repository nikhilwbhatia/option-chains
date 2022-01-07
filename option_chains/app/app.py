from collections import defaultdict

import pyetrade
from flask import Flask
from flask import render_template, redirect, url_for, request

from option_chains import options_manager, constants

global oauth_object
global oauth_token
global oauth_secret


app = Flask(__name__)


@app.route("/login")
def login():
    redirect_page = request.args.get("redirect")

    global oauth_object

    oauth_object = pyetrade.ETradeOAuth(
        constants.CONSUMER_KEY, constants.CONSUMER_SECRET
    )
    return render_template(
        "login.html", url=oauth_object.get_request_token(), redirect=redirect_page
    )


@app.route("/auth", methods=["POST"])
def auth():
    redirect_page = request.args.get("redirect")
    verification_token = request.form["verificationToken"]

    tokens = oauth_object.get_access_token(verification_token)

    global oauth_token
    global oauth_secret
    oauth_token = tokens["oauth_token"]
    oauth_secret = tokens["oauth_token_secret"]

    return redirect(url_for(redirect_page))


@app.route("/", methods=["GET", "POST"])
def index():
    if "oauth_token" not in globals():
        return redirect(url_for("login", redirect="index"))

    defaults = {
        "ticker": "GOOG",
        "min_strike": 30,
        "max_strike": 20,
        "increment": 100,
        "lookahead": 3,
        "contracts": 1,
        "min_volume": 1,
        "min_open_interest": 1,
        "min_annualized_return": 0.0,
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
        increment=float(request.form.get("increment", defaults["increment"])),
        month_look_ahead=int(request.form.get("lookahead", defaults["lookahead"])),
        min_volume=int(request.form.get("min_volume", defaults["min_volume"])),
        min_open_interest=int(
            request.form.get("min_open_interest", defaults["min_open_interest"])
        ),
        min_annualized_return=float(
            request.form.get("min_annualized_return", defaults["min_annualized_return"])
        ),
        contracts_to_buy=int(request.form.get("contracts", defaults["contracts"])),
    )

    options_dict = defaultdict(list)
    for option_info in result:
        options_dict[option_info["expiryDate"]].append(option_info)

    options_dict = {
        key: sorted(value, key=lambda d: d["strikePrice"])
        for key, value in options_dict.items()
    }

    # get market data values for ticker to use in general stock info
    market_data = manager.get_market_data(ticker)
    company_name = market_data.company_name
    market_price = round(market_data.market_price, 2)
    high_52 = round(market_data.high_52, 2)
    low_52 = round(market_data.low_52, 2)
    beta = round(market_data.beta, 2)
    next_earnings_date = market_data.next_earnings_date

    # TODO: remove duplicate code (original in options_manager.py)
    max_strike_resolved = int(float(market_price) * (1 - (max_strike / 100)))
    min_strike_resolved = int(float(market_price) * (1 - (min_strike / 100)))

    return render_template(
        "index.html",
        options=options_dict,
        prior_form=dict(request.form),
        defaults=defaults,
        valid_increments=options_manager.VALID_INCREMENTS,
        market_price=market_price,
        company_name=company_name,
        high_52=high_52,
        low_52=low_52,
        beta=beta,
        next_earnings_date=next_earnings_date,
        min_strike=min_strike_resolved,
        max_strike=max_strike_resolved,
    )


@app.route("/multi", methods=["GET", "POST"])
def multi():
    if "oauth_token" not in globals():
        return redirect(url_for("login", redirect="multi"))

    defaults = {
        "sector": "Communication Services",
        "sub_sector": "Comm - Media & Ent",
        "min_strike": 30,
        "max_strike": 20,
        "lookahead": 3,
        "contracts": 1,
        "min_volume": 1,
        "min_open_interest": 1,
        "min_annualized_return": 0.0,
    }

    manager = options_manager.OptionsManager(
        consumer_key=constants.CONSUMER_KEY,
        consumer_secret=constants.CONSUMER_SECRET,
        oauth_token=oauth_token,
        oauth_secret=oauth_secret,
    )

    df = manager.get_all_options_info(
        sector=request.form.get("sector", defaults["sector"]),
        sub_sector=request.form.get("sub_sector", defaults["sub_sector"]),
        min_strike=float(request.form.get("min_strike", defaults["min_strike"])),
        max_strike=float(request.form.get("max_strike", defaults["max_strike"])),
        month_look_ahead=int(request.form.get("lookahead", defaults["lookahead"])),
        min_volume=int(request.form.get("min_volume", defaults["min_volume"])),
        min_open_interest=int(
            request.form.get("min_open_interest", defaults["min_open_interest"])
        ),
        min_annualized_return=float(
            request.form.get("min_annualized_return", defaults["min_annualized_return"])
        ),
    )

    # get unique sectors/sub-sectors for use in dropdowns
    csv_df = manager.get_csv_df()
    all_sectors = sorted(list(set(csv_df["Sector"].to_list())))
    all_sub_sectors = sorted(list(set(csv_df["Sub-Sector"].to_list())))
    # # get {sector1: [sub_sector1, sub_sector2], sector2: [...]]
    # all_sub_sectors = {
    #     sector: list(set(csv_df[csv_df["Sector"] == sector]["Sub-Sector"].to_list()))
    #     for sector in all_sectors
    # }

    return render_template(
        "multi.html",
        df=df.to_html(classes="table table-striped table-condensed", table_id="df"),
        titles=df.columns.values,
        prior_form=dict(request.form),
        defaults=defaults,
        all_sectors=all_sectors,
        all_sub_sectors=all_sub_sectors,
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8008)
