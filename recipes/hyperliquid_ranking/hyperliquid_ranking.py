# /// script
# dependencies = [
#     "crowdcent-challenge>=0.2.6",
#     "marimo",
#     "polars",
#     "pyarrow",
#     "scikit-learn",
#     "xgboost",
# ]
#
# [tool.marimo.opengraph]
# title = "Hyperliquid ranking, end to end"
# description = "Train a gradient booster on CrowdCent's training data, predict the latest inference release, and submit."
#
# [tool.crowdcent.thumbnail]
# title = "10d / 30d predictions"
# output = "predictions.csv"
# label = "Model predictions"
# badge = "MODEL OUTPUT"
# sort = "pred_30d"
# columns = {id = "ASSET", pred_10d = "10-DAY RANK", pred_30d = "30-DAY RANK"}
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
    import polars as pl
    from xgboost import XGBRegressor

    return XGBRegressor, cc, mo, os, pl


@app.cell
def _(mo):
    mo.md("""
    # Hyperliquid ranking, end to end

    Train a model on CrowdCent's training data, predict the latest inference
    release, and submit to the `hyperliquid-ranking` challenge.

    Cloud runs, including scheduled runs, submit automatically to slot 1.
    In an interactive notebook, submission waits for the button below.

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
def _(client, pl):
    client.download_training_dataset("latest", "training_data.parquet")
    training_data = pl.read_parquet("training_data.parquet", use_pyarrow=True)
    training_data.head()
    return (training_data,)


@app.cell
def _(XGBRegressor, pl, training_data):
    features = [c for c in training_data.columns if c.startswith("feature")]
    targets = ["target_10d", "target_30d"]

    labeled = training_data.filter(pl.all_horizontal(pl.col(targets).is_finite()))
    if not features or labeled.is_empty():
        raise ValueError(
            "Training data needs features and resolved 10-day and 30-day targets."
        )
    X, y = labeled[features].to_numpy(), labeled[targets].to_numpy()
    model = XGBRegressor(n_estimators=200, n_jobs=2, random_state=0)
    # Prints in-sample error every 25 trees: a progress heartbeat, not model quality.
    model.fit(X, y, eval_set=[(X, y)], verbose=25)
    return features, model


@app.cell
def _(client, pl):
    client.download_inference_data("latest", "inference_data.csv")
    inference_data = pl.read_csv("inference_data.csv")
    inference_data.head()
    return (inference_data,)


@app.cell
def _(features, inference_data, model, pl):
    predictions = (
        pl.from_numpy(
            model.predict(inference_data[features].to_numpy()), ["pred_10d", "pred_30d"]
        )
        .with_columns(inference_data["id"])
        .select("id", "pred_10d", "pred_30d")
        .with_columns(pl.col("pred_10d", "pred_30d").clip(0, 1))
    )
    predictions.sort("pred_30d", descending=True)
    return (predictions,)


@app.cell
def _(predictions):
    from pathlib import Path

    output = Path("out")
    output.mkdir(parents=True, exist_ok=True)
    predictions.write_csv(output / "predictions.csv")
    return


@app.cell
def _(mo):
    submit = mo.ui.run_button(label="Submit to the Challenge")
    submit
    return (submit,)


@app.cell
def _(client, mo, os, predictions, submit):
    mo.stop(
        not os.environ.get("CROWDCENT_RUN_ID") and not submit.value,
        mo.md("Press **Submit to the Challenge** to send these predictions to slot 1."),
    )
    client.submit_predictions(df=predictions, slot=1)
    mo.callout("Submitted to slot 1.", kind="success")
    return


if __name__ == "__main__":
    app.run()
