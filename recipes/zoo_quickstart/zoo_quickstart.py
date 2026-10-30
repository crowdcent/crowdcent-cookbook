# /// script
# dependencies = [
#     "crowdcent-challenge>=0.2.16",
#     "lightgbm",
#     "marimo",
#     "numpy",
#     "polars",
#     "requests",
#     "xgboost",
# ]
#
# [tool.marimo.opengraph]
# title = "Submit with a zoo model"
# description = "Load a ready-made model from the CrowdCent model zoo, predict the latest inference release, and submit. No training step."
#
# [tool.crowdcent.thumbnail]
# title = "Zoo model predictions"
# output = "predictions.csv"
# label = "hl-xgb-baseline"
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
    import hashlib
    import io
    import os
    import tempfile
    from pathlib import Path

    import crowdcent_challenge as cc
    import marimo as mo
    import numpy as np
    import polars as pl

    return Path, cc, hashlib, io, mo, np, os, pl, tempfile


@app.cell
def _(mo):
    mo.md("""
    # Submit with a zoo model

    The model zoo holds ready-made models that CrowdCent trains and scores.
    This notebook loads one, predicts the latest inference release, and
    submits to the `hyperliquid-ranking` challenge. There is no training
    step. The `zoo_models` recipe shows how each model was made.

    The default is the XGBoost baseline. Pick another model below, or set a
    run parameter such as `model=hl-ridge-baseline`.

    Cloud runs, including scheduled runs, submit automatically to slot 1.
    In an interactive notebook, submission waits for the button below.

    The client reads `CROWDCENT_API_KEY` from the environment. On Cloud, turn
    on Challenge access for this project. Anywhere else,
    [create a key](https://crowdcent.com/profile/settings/) and export it.
    """)
    return


@app.cell
def _(cc, mo):
    client = cc.ChallengeClient("hyperliquid-ranking")
    zoo = f"{client.base_url}/zoo"
    listed = client.session.get(f"{zoo}/", params={"challenge": client.challenge_slug})
    listed.raise_for_status()
    names = sorted({entry["ref"].split("@")[0] for entry in listed.json()})
    mo.stop(not names, mo.md("The model zoo has no live model yet."))
    picker = mo.ui.dropdown(
        names,
        value="hl-xgb-baseline" if "hl-xgb-baseline" in names else names[0],
        label="Model",
    )
    picker
    return client, picker, zoo


@app.cell
def _(mo, picker):
    MODEL = mo.cli_args().get("model") or picker.value
    return (MODEL,)


@app.cell
def _(mo):
    mo.md("""
    ## Load the model

    The zoo API describes each model in a manifest: the features it reads,
    its out-of-sample scores and the SHA-256 of every file. Each download is
    checked against the manifest before the model reads it.
    """)
    return


@app.cell
def _(MODEL, Path, client, hashlib, io, mo, np, pl, tempfile, zoo):
    def describe(ref):
        found = client.session.get(f"{zoo}/{ref}/")
        found.raise_for_status()
        manifest = found.json()["manifest"]
        if manifest["challenge"] != client.challenge_slug:
            raise ValueError(f"{manifest['ref']} predicts {manifest['challenge']}.")
        return manifest

    def download(manifest, key):
        response = client.session.get(
            f"{zoo}/{manifest['ref']}/download/", params={"file": key}
        )
        response.raise_for_status()
        if (
            hashlib.sha256(response.content).hexdigest()
            != manifest["files"][key]["sha256"]
        ):
            raise ValueError(f"{manifest['ref']} {key} does not match its SHA-256.")
        return response.content

    def arrays(manifest):
        with np.load(io.BytesIO(download(manifest, "model")), allow_pickle=False) as weights:
            return {key: weights[key] for key in weights.files}

    def linear(manifest):
        w = arrays(manifest)
        return lambda X: X.astype(np.float64) @ w["coef"].T + w["intercept"]

    def mlp(manifest):
        w = arrays(manifest)
        layers = sum(key.startswith("w") for key in w)

        def forward(X):
            h = (X.astype(np.float64) - w["x_mean"]) / w["x_scale"]
            for k in range(layers):
                h = h @ w[f"w{k}"] + w[f"b{k}"]
                if k < layers - 1:
                    h = np.maximum(h, 0.0)
            return h

        return forward

    def lstm(manifest):
        w = arrays(manifest)
        width, hidden = w["w_input"].shape[0], w["w_hidden"].shape[0]

        def sigmoid(x):
            return 1.0 / (1.0 + np.exp(-x))

        def forward(X):
            # The manifest lists the features oldest lag first, one step at a time.
            z = (X.astype(np.float64) - w["x_mean"]) / w["x_scale"]
            steps = z.reshape(len(X), -1, width)
            h = np.zeros((len(X), hidden))
            c = np.zeros_like(h)
            for t in range(steps.shape[1]):
                gates = steps[:, t] @ w["w_input"] + h @ w["w_hidden"] + w["b"]
                i, f, g, o = np.split(gates, 4, axis=1)
                c = sigmoid(f) * c + sigmoid(i) * np.tanh(g)
                h = sigmoid(o) * np.tanh(c)
            return h @ w["w_out"] + w["b_out"]

        return forward

    def xgboost_model(manifest):
        import xgboost

        booster = xgboost.Booster()
        booster.load_model(bytearray(download(manifest, "model")))
        return lambda X: booster.predict(xgboost.DMatrix(X))

    def lightgbm_model(manifest):
        import lightgbm

        folder = Path(tempfile.mkdtemp())
        boosters = []
        for horizon in ("10d", "30d"):
            path = folder / f"model_{horizon}.txt"
            path.write_bytes(download(manifest, f"model_{horizon}"))
            boosters.append(lightgbm.Booster(model_file=path))
        return lambda X: np.column_stack([b.predict(X) for b in boosters])

    def ranks(raw):
        return (
            pl.DataFrame(np.asarray(raw), schema=["a", "b"], orient="row")
            .select((pl.all().rank("average") - 1) / (pl.len() - 1))
            .fill_nan(0.5)
            .to_numpy()
        )

    def blend(manifest):
        members = [(load(describe(m["ref"])), m["weight"]) for m in manifest["members"]]
        return lambda frame: sum(weight * ranks(member(frame)) for member, weight in members)

    LOADERS = {
        "linear": linear,
        "mlp": mlp,
        "lstm": lstm,
        "xgboost": xgboost_model,
        "lightgbm": lightgbm_model,
    }

    def load(manifest):
        """A function from an inference frame to the model's raw predictions."""
        if manifest["kind"] == "blend":
            return blend(manifest)
        if manifest["kind"] not in LOADERS:
            raise ValueError(f"This notebook cannot load a {manifest['kind']} model.")
        predict = LOADERS[manifest["kind"]](manifest)
        features = manifest["features"]
        # float32, the precision the model was trained and checked at.
        return lambda frame: predict(frame.select(features).to_numpy().astype(np.float32))

    manifest = describe(MODEL)
    model = load(manifest)

    scores = manifest["evaluation"]["scores"]
    mo.md(
        f"Loaded **{manifest['title']}** (`{manifest['ref']}`), trained through "
        f"{manifest['data']['trained_through']}. Out-of-sample Spearman: "
        f"{scores['spearman_10d']:.3f} at 10 days, {scores['spearman_30d']:.3f} at 30 days."
    )
    return manifest, model


@app.cell
def _(Path, client, pl, tempfile):
    downloads = Path(tempfile.mkdtemp())
    client.download_inference_data("latest", downloads / "inference_data.csv")
    inference_data = pl.read_csv(downloads / "inference_data.csv")
    inference_data.head()
    return (inference_data,)


@app.cell
def _(mo):
    mo.md("""
    ## Predict

    The model predicts 10 and 30 days ahead. A submission ranks the assets,
    so each prediction becomes its rank scaled from 0 to 1.
    """)
    return


@app.cell
def _(inference_data, model, pl):
    raw = model(inference_data)
    predictions = pl.DataFrame(
        {"id": inference_data["id"], "pred_10d": raw[:, 0], "pred_30d": raw[:, 1]}
    ).with_columns(
        ((pl.col(c).rank("average") - 1) / (pl.len() - 1)).alias(c)
        for c in ("pred_10d", "pred_30d")
    )
    predictions.sort("pred_30d", descending=True)
    return (predictions,)


@app.cell
def _(Path, predictions):
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
