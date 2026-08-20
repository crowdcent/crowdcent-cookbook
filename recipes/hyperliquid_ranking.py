# /// script
# dependencies = [
#     "crowdcent-challenge",
#     "marimo",
#     "numpy",
#     "polars",
#     "pyarrow",
#     "scikit-learn",
#     "xgboost-cpu",
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
    import os
    import pathlib
    import sys

    import marimo as mo
    import polars as pl

    # Pyodide reports this platform and nothing else does, so it is the one
    # honest way for a notebook to know where it woke up.
    IN_BROWSER = sys.platform == "emscripten"
    INTERACTIVE = not bool(os.environ.get("CROWDCENT_RUN_ID"))

    CHALLENGE = "hyperliquid-ranking"
    SLOT = 1

    DATA = pathlib.Path(os.environ.get("CROWDCENT_DATA_DIR", "/data"))
    OUT = pathlib.Path(os.environ.get("CROWDCENT_OUT_DIR", "/work/out"))
    return CHALLENGE, DATA, IN_BROWSER, INTERACTIVE, OUT, SLOT, mo, os, pl, sys


@app.cell
def _(mo):
    # Asked once, here, so every cell below can say what it can actually do
    # rather than discovering it halfway through a fit.
    try:
        from xgboost import XGBRegressor

        HAS_XGBOOST = True
    except ImportError:
        XGBRegressor = None
        HAS_XGBOOST = False

    mo.md(
        "# Hyperliquid ranking, end to end"
        if HAS_XGBOOST
        else "# Hyperliquid ranking, end to end *(preview)*"
    )
    return HAS_XGBOOST, XGBRegressor


@app.cell
def _(CHALLENGE, DATA, HAS_XGBOOST, IN_BROWSER, mo):
    mo.md(
        f"""
        Train a model on CrowdCent's training data, predict on the latest
        inference release, and submit to `{CHALLENGE}`. The line that submits is
        yours, at the bottom: the same public client you would use from a laptop.

        {
            "**Running in your tab.** Pyodide has no xgboost, so the model below "
            "is a rank of trailing features rather than a trained booster: "
            "enough to see the whole shape of the loop without sending anything. "
            "Run this locally or on CrowdCent hardware to train and submit with "
            "a key supplied by the runtime."
            if IN_BROWSER or not HAS_XGBOOST
            else f"**Running on CrowdCent hardware**, with xgboost from the built "
            f"environment and the release in reach at `{DATA}`."
        }
        """
    )
    return


@app.cell
def _(mo):
    mo.md("""
    ## The training data
    """)
    return


@app.cell
def _(DATA, pl):
    def load_training_data(client):
        """The mounted release when there is one, the API when there is not.

        Cloud mounts the release read-only, so on our hardware this costs no
        download and no egress. On a laptop there is nothing mounted and the
        client fetches it, which is the path the tutorial takes. Same notebook.
        """
        if DATA.is_dir():
            mounted = sorted(DATA.rglob("*train*.parquet")) or sorted(
                DATA.rglob("*.parquet")
            )
            if mounted:
                print(f"reading the mounted release: {mounted[0].name}")
                return pl.read_parquet(mounted[0])

        if client is None:
            return None

        print("nothing mounted, so downloading the training data")
        try:
            client.download_training_dataset(
                version="latest", dest_path="training.parquet"
            )
        except Exception as refusal:  # noqa: BLE001 - the fallback says why
            # A download this notebook can work without is not worth dying
            # over --- unlike submission below, which must never fail quietly.
            print(f"the download was refused ({refusal}); using a generated universe")
            return None
        return pl.read_parquet("training.parquet")

    return (load_training_data,)


@app.cell
def _(CHALLENGE, os):
    def credentials():
        """Read a key from the runtime without storing it in the notebook."""
        return os.environ.get("CROWDCENT_API_KEY", "")

    def challenge_client():
        key = credentials()
        if not key:
            return None
        try:
            from crowdcent_challenge import ChallengeClient
        except ImportError:
            print("crowdcent-challenge is not installed in this environment")
            return None
        return ChallengeClient(CHALLENGE, api_key=key)

    return (challenge_client,)


@app.cell
def _(challenge_client, load_training_data, pl):
    client = challenge_client()
    training_data = load_training_data(client)

    if training_data is None:
        print("no release mounted and no key, so generating a universe to work against")
        import numpy as np

        rng = np.random.default_rng(0)
        size = 400
        training_data = pl.DataFrame(
            {
                "id": [f"asset_{i:04d}" for i in range(size)],
                **{f"feature_{d}": rng.normal(0, 1, size) for d in range(1, 21)},
                "target_10d": rng.uniform(0, 1, size),
                "target_30d": rng.uniform(0, 1, size),
            }
        )

    features = [
        column for column in training_data.columns if column.startswith("feature")
    ]
    TARGETS = ["target_10d", "target_30d"]
    print(f"{training_data.height} rows, {len(features)} features")
    training_data.head()
    return TARGETS, client, features, training_data


@app.cell
def _(mo):
    mo.md("""
    ## The model
    """)
    return


@app.cell
def _(HAS_XGBOOST, TARGETS, XGBRegressor, features, pl, training_data):
    def fit(frame):
        """A trained booster where there is one, a ranked composite where not.

        The tutorial passes `device="cuda"`. There is no GPU on the S and M
        shapes, and asking for one silently falls back to CPU with a warning, so
        it is simply not asked for here: a notebook that lies about its
        hardware is worse than one that is plain about it.
        """
        if not HAS_XGBOOST:
            return None
        model = XGBRegressor(n_estimators=200, n_jobs=-1)
        # `.to_numpy()` rather than the frame itself. Handed a polars frame,
        # xgboost routes through pandas -- so a notebook that never mentions
        # pandas fails with `No module named 'pandas'` from inside a fit, in
        # any environment that does not happen to have it. The array is what
        # xgboost wants anyway.
        model.fit(frame[features].to_numpy(), frame[TARGETS].to_numpy())
        return model

    def predict(model, frame):
        if model is not None:
            raw = model.predict(frame[features].to_numpy())
            return pl.from_numpy(raw, ["pred_10d", "pred_30d"])
        # The preview path: rank a composite of the features. Same output
        # contract, so everything downstream is exercised for real.
        composite = frame.select(pl.sum_horizontal(features).alias("composite"))
        ranked = composite.select((pl.col("composite").rank() / frame.height))
        return ranked.rename({"composite": "pred_10d"}).with_columns(
            pl.col("pred_10d").alias("pred_30d")
        )

    model = fit(training_data)
    print(
        "trained an xgboost model" if model is not None else "using the preview ranker"
    )
    return model, predict


@app.cell
def _(mo):
    mo.md("""
    ## The latest inference data, and predictions
    """)
    return


@app.cell
def _(DATA, client, features, model, pl, predict, training_data):
    def load_inference_data():
        if DATA.is_dir():
            mounted = sorted(DATA.rglob("*infer*.parquet"))
            if mounted:
                print(f"reading the mounted release: {mounted[0].name}")
                return pl.read_parquet(mounted[0]), True
        if client is not None:
            print("nothing mounted, so downloading the inference data")
            try:
                client.download_inference_data("latest", "inference.parquet")
                return pl.read_parquet("inference.parquet"), True
            except Exception as refusal:  # noqa: BLE001 - the fallback says why
                print(
                    f"the download was refused ({refusal}); showing an in-sample "
                    "preview with submission disabled"
                )
        # Nothing to infer on: predict on the training universe so the loop
        # still completes and the shape is visible.
        return training_data.select(["id", *features]), False

    inference_data, inference_is_real = load_inference_data()

    predictions = (
        predict(model, inference_data)
        .with_columns(inference_data["id"])
        .select(["id", "pred_10d", "pred_30d"])
        # The Challenge takes predictions in the unit interval.
        .with_columns(pl.col(["pred_10d", "pred_30d"]).clip(0, 1))
        .sort("pred_30d", descending=True)
    )
    predictions
    return inference_is_real, predictions


@app.cell
def _(mo):
    mo.md("""
    ## Submit
    """)
    return


@app.cell
def _(OUT, predictions, sys):
    def write_parquet(frame, path):
        """Parquet, by whichever writer this environment actually has.

        polars' WebAssembly build ships no parquet writer, in a browser tab and
        nowhere else. pyarrow is there and is what polars would have handed the
        bytes to anyway.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        if sys.platform != "emscripten":
            frame.write_parquet(path)
            return path

        import pyarrow as pa
        import pyarrow.parquet as pq

        pq.write_table(pa.table({n: frame[n].to_list() for n in frame.columns}), path)
        return path

    output = write_parquet(predictions, OUT / "predictions.parquet")
    print(f"wrote {output}")
    return (output,)


@app.cell
def _(INTERACTIVE, mo):
    # Interactive notebooks must never submit just because they were opened.
    # A scheduled CrowdCent run is already an explicit instruction to run.
    submit_gate = (
        mo.ui.run_button(label="Submit to the Challenge") if INTERACTIVE else None
    )
    submit_gate
    return (submit_gate,)


@app.cell
def _(CHALLENGE, SLOT, client, inference_is_real, mo, output, submit_gate):
    mo.stop(
        not inference_is_real,
        mo.md(
            "**Submission disabled.** The predictions above use generated or "
            "in-sample fallback data."
        ),
    )
    mo.stop(
        submit_gate is not None and not submit_gate.value,
        mo.md(
            "**Nothing has been sent.** Press **Submit to the Challenge** above "
            f"to send `{output.name}` to `{CHALLENGE}` slot {SLOT} from this tab."
        ),
    )
    if client is None:
        print(
            f"\nNo key available here, so nothing was submitted to {CHALLENGE}.\n"
            "Set CROWDCENT_API_KEY locally, or run with API access enabled."
        )
    else:
        receipt = client.submit_predictions(file_path=str(output), slot=SLOT)
        print(f"\nsubmitted to {CHALLENGE} slot {SLOT}: {receipt}")
    return


if __name__ == "__main__":
    app.run()
