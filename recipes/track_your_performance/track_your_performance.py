# /// script
# dependencies = [
#     "crowdcent-challenge>=0.1.21",
#     "marimo",
#     "plotly",
#     "polars",
# ]
#
# [tool.marimo.opengraph]
# title = "Track your performance"
# description = "Every scored submission you have made, by slot, over time."
#
# [tool.crowdcent.thumbnail]
# title = "Composite percentile"
# output = "figure"
# figure = "figure"
# label = "Account performance"
# needs_api_key = true
# account_label = true
# legend_prefix = "Slot "
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
    # Track your performance

    Every scored submission you have made to the `hyperliquid-ranking`
    challenge, by slot, over time.

    The client reads `CROWDCENT_API_KEY` from the environment. On Cloud, turn
    on Challenge access for this project. Anywhere else,
    [create a key](https://crowdcent.com/profile/settings/) and export it.
    """)
    return


@app.cell
def _(cc, mo, pl):
    client = cc.ChallengeClient("hyperliquid-ranking")
    history = pl.DataFrame(client.get_performance(), strict=False)
    mo.stop(
        history.is_empty(),
        mo.md(
            "No scored submissions yet. Submit predictions and come back after they are scored."
        ),
    )
    mo.stop(
        "composite_percentile" not in history.columns,
        mo.md(
            "Your submissions have scores, but composite percentiles are not available yet."
        ),
    )
    history = history.with_columns(
        pl.col("release_date").str.to_date(),
        pl.col("slot").cast(pl.String),
        pl.col("composite_percentile").cast(pl.Float64),
    ).sort("release_date")
    history.select("release_date", "slot", "status", "composite_percentile").sort(
        "release_date", descending=True
    )
    return (history,)


@app.cell
def _(history, pl):
    history.group_by("slot").agg(
        pl.col("composite_percentile").mean().round(1).alias("mean percentile"),
        pl.len().alias("submissions"),
    ).sort("slot")
    return


@app.cell
def _(mo):
    window = mo.ui.slider(1, 20, value=5, label="Rolling window")
    window
    return (window,)


@app.cell
def _(history, mo, pl, px, window):
    smoothed = history.with_columns(
        pl.col("composite_percentile").rolling_mean(window.value).over("slot")
    )
    figure = px.line(
        smoothed,
        x="release_date",
        y="composite_percentile",
        color="slot",
        markers=True,
        range_y=[0, 100],
        labels={
            "release_date": "Inference period",
            "composite_percentile": "Percentile",
        },
        title="Composite percentile by slot",
        template="plotly_dark" if mo.app_meta().theme == "dark" else "plotly_white",
    )
    figure.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    figure
    return


if __name__ == "__main__":
    app.run()
