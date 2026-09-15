# /// script
# dependencies = [
#     "marimo",
#     "numpy",
#     "plotly",
#     "polars",
#     "urllib3",
# ]
#
# [tool.marimo.opengraph]
# title = "Numerai dashboard"
# description = "Payouts, stake at risk, and per-model scores for any Numerai account, read live from Numerai's public API."
#
# [tool.crowdcent.cloud]
# default_view = "app"
# ///

import marimo

__generated_with = "0.24.1"
app = marimo.App(width="full")


@app.cell
def _():
    import marimo as mo
    import plotly.express as px
    import polars as pl

    import numerai

    return mo, numerai, pl, px


@app.cell
def _(mo):
    mo.md("""
    # Numerai dashboard

    Payouts, stake at risk, and per-model scores for any Numerai account, read
    live from Numerai's public API. Nothing here needs a key.
    """)
    return


@app.cell
def _(mo):
    account = mo.ui.text(value="crowdcent", label="Numerai account").form(
        submit_button_label="Go"
    )
    account
    return (account,)


@app.cell
def _(account, mo, numerai):
    mo.stop(account.value is None, mo.md("Press **Go** to read the account."))
    models = numerai.models(account.value)
    mo.stop(
        models.is_empty(), mo.md(f"Numerai has no models under **{account.value}**.")
    )
    with mo.status.progress_bar(
        total=len(models), title="Reading rounds", remove_on_exit=True
    ) as bar:
        rounds = numerai.rounds(models, tick=bar.update)
    return models, rounds


@app.cell
def _(pl, rounds):
    daily = (
        rounds.filter(pl.col("resolved"))
        .group_by("tournament", "date")
        .agg(pl.col("payout").sum())
        .sort("tournament", "date")
        .with_columns(pl.col("payout").cum_sum().over("tournament").alias("cumulative"))
    )
    # Each model's newest round is the stake it has at risk today.
    newest = rounds.filter(pl.col("round") == pl.col("round").max().over("id"))
    stake = dict(newest.group_by("tournament").agg(pl.col("at_risk").sum()).iter_rows())
    return daily, stake


@app.cell
def _(daily, mo, pl, stake):
    earned = daily.group_by("tournament").agg(pl.col("payout").sum()).sort("tournament")
    mo.hstack(
        [
            mo.stat(
                value=f"{payout:+,.1f} NMR",
                label=tournament.capitalize(),
                caption=f"{stake.get(tournament, 0):,.0f} NMR at risk",
                direction="increase" if payout >= 0 else "decrease",
            )
            for tournament, payout in earned.iter_rows()
        ],
        justify="space-around",
    )
    return


@app.cell
def _(mo):
    COLORS = {"classic": "#8a8780", "signals": "#24aac2", "crypto": "#17c843"}

    def chart(figure, title):
        """One look for every chart, on whichever theme the page brought."""
        figure.update_layout(
            title=title,
            template="plotly_dark" if mo.app_meta().theme == "dark" else "plotly_white",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            legend_title=None,
            xaxis_title=None,
            height=340,
            margin={"l": 8, "r": 8, "t": 48, "b": 8},
        )
        return figure

    return COLORS, chart


@app.cell
def _(COLORS, chart, daily, mo, px):
    cumulative = px.line(
        daily,
        x="date",
        y="cumulative",
        color="tournament",
        color_discrete_map=COLORS,
        labels={"cumulative": "NMR"},
    )
    by_day = px.bar(
        daily,
        x="date",
        y="payout",
        color="tournament",
        color_discrete_map=COLORS,
        barmode="relative",
        labels={"payout": "NMR"},
    )
    mo.hstack(
        [
            chart(cumulative, "Cumulative payout"),
            chart(by_day, "Payout by resolution day"),
        ],
        widths="equal",
    )
    return


@app.cell
def _(mo, models):
    picker = mo.ui.dropdown(
        options={
            f"{model} ({tournament})": (model, tournament)
            for tournament, model, _ in models.iter_rows()
        },
        value=f"{models['model'][0]} ({models['tournament'][0]})",
        label="Model",
        searchable=True,
    )
    picker
    return (picker,)


@app.cell
def _(chart, mo, numerai, picker, pl, px):
    model, tournament = picker.value
    scored = numerai.scores(model, tournament).with_columns(
        pl.col("value", "percentile").rolling_mean(20).over("metric")
    )
    values = px.line(scored, x="date", y="value", color="metric")
    percentiles = px.line(
        scored, x="date", y="percentile", color="metric", range_y=[0, 100]
    )
    mo.hstack(
        [
            chart(values, f"{model}, 20-round mean score"),
            chart(percentiles, "Percentile in the field"),
        ],
        widths="equal",
    )
    return


if __name__ == "__main__":
    app.run()
