# /// script
# dependencies = [
#     "crowdcent-challenge",
#     "marimo",
#     "plotly",
#     "polars",
# ]
#
# [tool.marimo.opengraph]
# title = "Simulate the meta-model"
# description = "Backtest the meta-model as a long/short book with the engine behind the Simulator, from a few sliders."
# ///

import marimo

__generated_with = "0.24.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import crowdcent_challenge as cc
    import marimo as mo
    import plotly.express as px
    import polars as pl

    return cc, mo, pl, px


@app.cell
def _(mo):
    mo.md("""
    # Simulate the meta-model

    Trade the meta-model's rankings as a long/short book and see what it
    would have earned. The engine is the one behind the site's Simulator;
    knobs above your points tier are clamped and reported back.

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
    book = (
        mo.md("""
        {n_long} {n_short}

        {rebalance} {optimizer}

        {leverage}
        """)
        .batch(
            n_long=mo.ui.slider(1, 50, value=10, label="Long names"),
            n_short=mo.ui.slider(1, 50, value=10, label="Short names"),
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
                label="Sizing",
            ),
            leverage=mo.ui.slider(0.25, 3, step=0.25, value=1, label="Leverage"),
        )
        .form(submit_button_label="Simulate")
    )
    book
    return (book,)


@app.cell
def _(book, client, mo):
    mo.stop(book.value is None, mo.md("Choose a book and press **Simulate**."))
    result = client.run_simulation(
        config={
            "n_long": book.value["n_long"],
            "n_short": book.value["n_short"],
            "rebalance_days": book.value["rebalance"],
            "optimizer": book.value["optimizer"],
        },
        leverage=book.value["leverage"],
        include=["curve"],
    )
    stats = result["stats"]
    return result, stats


@app.cell
def _(mo, result, stats):
    mo.vstack(
        [
            mo.hstack(
                [
                    mo.stat(f"{stats['sharpe']:.2f}", label="Sharpe"),
                    mo.stat(f"{100 * stats['cagr']:+.1f}%", label="CAGR"),
                    mo.stat(f"{100 * stats['ann_vol']:.1f}%", label="Volatility"),
                    mo.stat(
                        f"{100 * stats['max_drawdown']:.1f}%", label="Max drawdown"
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
    curve = pl.DataFrame(result["curve"]).with_columns(pl.col("dates").str.to_date())
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
