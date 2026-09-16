# /// script
# dependencies = [
#     "crowdcent-challenge>=0.1.21",
#     "marimo",
#     "plotly",
#     "polars",
# ]
#
# [tool.marimo.opengraph]
# title = "Simulate the meta-model"
# description = "Backtest the meta-model as a long/short book with the engine behind the Simulator, from a few sliders."
#
# [tool.crowdcent.thumbnail]
# title = "Strategy vs. Bitcoin"
# output = "figure"
# figure = "figure"
# label = "10L / 10S · Min var · 1×"
# badge = "BACKTEST"
# args = ["--n_long=10"]
# legend = ["Strategy", "BTC"]
# needs_api_key = true
# ///

import marimo

__generated_with = "0.24.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import os

    import crowdcent_challenge as cc
    import marimo as mo
    import plotly.express as px
    import polars as pl

    return cc, mo, os, pl, px


@app.cell
def _(mo):
    mo.md("""
    # Simulate the meta-model

    Trade the meta-model's rankings as a long/short book and see what it
    would have earned. The engine is the one behind the site's Simulator;
    knobs above your points tier are clamped and reported back.

    Cloud runs use the form's defaults. Run parameters such as
    `n_long=20 n_short=20 leverage=1.5` override them.

    The client reads `CROWDCENT_API_KEY` from the environment. On Cloud, turn
    on Challenge access for this project. Anywhere else,
    [create a key](https://crowdcent.com/profile/settings/) and export it.
    """)
    return


@app.cell
def _(cc):
    client = cc.ChallengeClient("hyperliquid-ranking")
    return (client,)


@app.cell
def _(mo):
    DEFAULTS = {
        "n_long": 10,
        "n_short": 10,
        "rebalance": "10t",
        "optimizer": "min_var",
        "leverage": 1.0,
    }
    book = (
        mo.md("""
        {n_long} {n_short}

        {rebalance} {optimizer}

        {leverage}
        """)
        .batch(
            n_long=mo.ui.slider(1, 50, value=DEFAULTS["n_long"], label="Long names"),
            n_short=mo.ui.slider(1, 50, value=DEFAULTS["n_short"], label="Short names"),
            rebalance=mo.ui.dropdown(
                {
                    "Daily": "1",
                    "Every 10 days": "10",
                    "Every 10 days, tranched": "10t",
                    "Every 30 days": "30",
                    "Every 30 days, tranched": "30t",
                },
                value="Every 10 days, tranched",
                label="Rebalance",
            ),
            optimizer=mo.ui.dropdown(
                {
                    "Equal weight": "equal",
                    "Inverse vol": "inv_vol",
                    "Min var": "min_var",
                    "Signal": "signal",
                },
                value="Min var",
                label="Weighting",
            ),
            leverage=mo.ui.slider(
                0.25, 3, step=0.25, value=DEFAULTS["leverage"], label="Leverage"
            ),
        )
        .form(submit_button_label="Simulate")
    )
    book
    return DEFAULTS, book


@app.cell
def _(DEFAULTS, book, client, mo, os):
    answered = dict(mo.cli_args()) or book.value
    mo.stop(
        not answered and not os.environ.get("CROWDCENT_RUN_ID"),
        mo.md("Choose a book and press **Simulate**."),
    )
    config = {**DEFAULTS, **(answered or {})}
    result = client.run_simulation(
        config={
            "n_long": config["n_long"],
            "n_short": config["n_short"],
            "rebalance_days": str(config["rebalance"]),
            "optimizer": config["optimizer"],
        },
        leverage=config["leverage"],
        include=["curve"],
    )
    stats = result["stats"]
    return result, stats


@app.cell
def _(mo, result, stats):
    def metric(value, *, percent=False):
        if value is None:
            return "—"
        return f"{100 * value:+.1f}%" if percent else f"{value:.2f}"

    mo.vstack(
        [
            mo.hstack(
                [
                    mo.stat(metric(stats["sharpe"]), label="Sharpe"),
                    mo.stat(metric(stats["cagr"], percent=True), label="CAGR"),
                    mo.stat(metric(stats["ann_vol"], percent=True), label="Volatility"),
                    mo.stat(
                        metric(stats["max_drawdown"], percent=True),
                        label="Max drawdown",
                    ),
                ],
                justify="space-around",
            ),
            mo.md(
                (
                    f"Clamped to your tier: {', '.join(result['locked'])}. "
                    if result["locked"]
                    else ""
                )
                + f"[Open this book on crowdcent.com]({result['web_url']})."
            ),
        ]
    )
    return


@app.cell
def _(mo, pl, px, result):
    curve = pl.DataFrame(result["curve"], strict=False).with_columns(
        pl.col("dates").str.to_date()
    )
    figure = px.line(
        curve,
        x="dates",
        y=["strategy", "btc_benchmark"],
        labels={"dates": "", "value": "Cumulative return", "variable": ""},
        title="Equity curve",
        template="plotly_dark" if mo.app_meta().theme == "dark" else "plotly_white",
    )
    figure.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        yaxis_tickformat=".0%",
    )
    figure
    return


if __name__ == "__main__":
    app.run()
