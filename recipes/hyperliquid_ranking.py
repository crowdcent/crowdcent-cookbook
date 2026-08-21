# /// script
# dependencies = [
#     "crowdcent-challenge",
#     "marimo",
#     "polars",
#     "pyarrow",
#     "scikit-learn",
#     "xgboost",
# ]
#
# [tool.marimo.opengraph]
# title = "Hyperliquid ranking, end to end"
# description = "Train a gradient booster, predict the latest inference release, and submit to the Hyperliquid ranking challenge."
# ///

import marimo

__generated_with = "0.23.15"
app = marimo.App(width="medium")


@app.cell
def _():
    import crowdcent_challenge as cc
    import marimo as mo
    import polars as pl
    from xgboost import XGBRegressor

    return XGBRegressor, cc, mo, pl


@app.cell
def _(mo):
    mo.md("""
    # Hyperliquid ranking, end to end

    Train a model on CrowdCent's training data, predict the latest inference
    release, and submit to the `hyperliquid-ranking` challenge.

    The client reads `CROWDCENT_API_KEY` from the environment. On CrowdCent
    Cloud, turn on Challenge access for the project. Locally,
    [generate a key](https://crowdcent.com/profile/settings/) and export it.
    """)
    return


@app.cell
def _(cc):
    client = cc.ChallengeClient("hyperliquid-ranking")
    return (client,)


@app.cell
def _(client, pl):
    client.download_training_dataset("latest", "training_data.parquet")
    training_data = pl.read_parquet("training_data.parquet")
    training_data.head()
    return (training_data,)


@app.cell
def _(XGBRegressor, training_data):
    features = [c for c in training_data.columns if c.startswith("feature")]
    targets = ["target_10d", "target_30d"]

    model = XGBRegressor(n_estimators=200)
    model.fit(training_data[features].to_numpy(), training_data[targets].to_numpy())
    return features, model


@app.cell
def _(client, pl):
    client.download_inference_data("latest", "inference_data.parquet")
    inference_data = pl.read_parquet("inference_data.parquet")
    inference_data.head()
    return (inference_data,)


@app.cell
def _(features, inference_data, model, pl):
    predictions = (
        pl.from_numpy(
            model.predict(inference_data[features].to_numpy()), ["pred_10d", "pred_30d"]
        )
        .with_columns(inference_data["id"])
        .select(["id", "pred_10d", "pred_30d"])
        .with_columns(pl.col(["pred_10d", "pred_30d"]).clip(0, 1))
    )
    predictions.sort("pred_30d", descending=True)
    return (predictions,)


@app.cell
def _(mo):
    submit = mo.ui.run_button(label="Submit to the Challenge")
    submit
    return (submit,)


@app.cell
def _(client, mo, predictions, submit):
    mo.stop(
        not submit.value,
        mo.md("Press **Submit to the Challenge** to send these predictions to slot 1."),
    )
    client.submit_predictions(df=predictions, slot=1)
    return


if __name__ == "__main__":
    app.run()
