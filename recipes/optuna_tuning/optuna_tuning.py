# /// script
# dependencies = [
#     "crowdcent-challenge>=0.1.21",
#     "joblib",
#     "marimo",
#     "numpy",
#     "optuna",
#     "plotly",
#     "polars",
#     "pyarrow",
#     "scikit-learn",
#     "xgboost",
# ]
#
# [tool.marimo.opengraph]
# title = "Tune a model with Optuna"
# description = "Search XGBoost settings on CrowdCent's training data, from a form in the browser or with defaults and optional parameters on Cloud."
#
# [tool.crowdcent.thumbnail]
# title = "XGBoost trial results"
# output = "figure"
# figure = "trial_figure"
# label = "24 trials · XGBoost"
# badge = "VALIDATION"
# args = ["--trials=24", "--depth_max=8"]
# x_label = "Learning rate"
# y_label = "Mean daily Spearman"
# needs_api_key = true
# ///

import marimo

__generated_with = "0.24.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import datetime as dt
    import os
    import pathlib

    import crowdcent_challenge as cc
    import joblib
    import marimo as mo
    import optuna
    import plotly.express as px
    import polars as pl
    from xgboost import XGBRegressor

    return XGBRegressor, cc, dt, joblib, mo, optuna, os, pathlib, pl, px


@app.cell
def _(mo):
    mo.md("""
    # Tune a model with Optuna

    Search XGBoost settings on CrowdCent's training data, scored the way the
    challenge scores you: mean daily Spearman correlation on dates the model
    never saw.

    In an interactive notebook, choose a search and press **Tune**. Cloud
    runs use the defaults below automatically. Override them with run
    parameters like `trials=100 lr_max=0.2`; runs with different parameters
    sit side by side under History.

    The notebook charts every trial and names the best one. It saves the
    trials to `trials/<name>.csv` and the best model to `models/<name>.joblib`
    under the run's output directory (locally, `out/`). Download those files
    from the run report or publish them to the project store for another job.
    """)
    return


@app.cell
def _(mo):
    DEFAULTS = {
        "trials": 30,
        "depth_max": 8,
        "lr_min": 0.01,
        "lr_max": 0.3,
        "target": "target_10d",
        "name": "best",
    }
    search_form = (
        mo.md("""
        {trials} {depth_max}

        {lr_min} {lr_max}

        {target} {name}
        """)
        .batch(
            trials=mo.ui.slider(5, 200, value=DEFAULTS["trials"], label="Trials"),
            depth_max=mo.ui.slider(
                2, 12, value=DEFAULTS["depth_max"], label="Deepest tree"
            ),
            lr_min=mo.ui.number(
                0.001,
                1.0,
                step=0.001,
                value=DEFAULTS["lr_min"],
                label="Learning rate from",
            ),
            lr_max=mo.ui.number(
                0.001, 1.0, step=0.001, value=DEFAULTS["lr_max"], label="to"
            ),
            target=mo.ui.dropdown(
                ["target_10d", "target_30d"], value=DEFAULTS["target"], label="Target"
            ),
            name=mo.ui.text(value=DEFAULTS["name"], label="Save as"),
        )
        .form(submit_button_label="Tune")
    )
    search_form
    return DEFAULTS, search_form


@app.cell
def _(DEFAULTS, mo, os, search_form):
    answered = dict(mo.cli_args()) or search_form.value
    mo.stop(
        not answered and not os.environ.get("CROWDCENT_RUN_ID"),
        mo.md(
            "Choose a search and press **Tune**, or start a Cloud run to use the defaults with optional parameters like `trials=100 lr_max=0.2`."
        ),
    )
    search = {**DEFAULTS, **(answered or {})}
    if not str(search["name"]).replace("_", "").replace("-", "").isalnum():
        raise ValueError(
            "Save as must contain only letters, numbers, underscores, and hyphens."
        )
    if search["target"] not in ("target_10d", "target_30d"):
        raise ValueError("Target must be target_10d or target_30d.")
    if not 1 <= int(search["trials"]) <= 200 or not 2 <= int(search["depth_max"]) <= 12:
        raise ValueError("Choose 1–200 trials and a maximum depth of 2–12.")
    if not all(0 < float(search[key]) <= 1 for key in ("lr_min", "lr_max")):
        raise ValueError("Learning rates must be greater than zero and at most one.")
    search
    return (search,)


@app.cell
def _(cc, dt, pl, search):
    client = cc.ChallengeClient("hyperliquid-ranking")
    client.download_training_dataset("latest", "training_data.parquet")
    data = pl.read_parquet("training_data.parquet").drop_nulls(search["target"])
    features = [c for c in data.columns if c.startswith("feature_")]

    # Validate on the last fifth of dates, a month past training, so no target's window reaches back.
    dates = data["date"].unique().sort()
    train_end = dates[int(len(dates) * 0.8)]
    train = data.filter(pl.col("date") <= train_end)
    valid = data.filter(pl.col("date") > train_end + dt.timedelta(days=31))
    if not features or train.is_empty() or valid.is_empty():
        raise ValueError(
            "Training data needs features and enough dates for a 31-day purged validation split."
        )
    return data, features, train, valid


@app.cell
def _(XGBRegressor, features, optuna, os, pl, search, train, valid):
    target = search["target"]
    low, high = sorted((search["lr_min"], search["lr_max"]))

    def objective(trial):
        model = XGBRegressor(
            n_estimators=trial.suggest_int("n_estimators", 100, 500, step=100),
            learning_rate=trial.suggest_float("learning_rate", low, high, log=True),
            max_depth=trial.suggest_int("max_depth", 2, search["depth_max"]),
            subsample=trial.suggest_float("subsample", 0.5, 1.0),
            colsample_bytree=trial.suggest_float("colsample_bytree", 0.3, 1.0),
            n_jobs=1,
        )
        model.fit(train[features].to_numpy(), train[target].to_numpy())
        scored = valid.select("date", target).with_columns(
            pl.Series("pred", model.predict(valid[features].to_numpy()))
        )
        return (
            scored.group_by("date")
            .agg(pl.corr("pred", target, method="spearman"))
            .get_column("pred")
            .mean()
        )

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(
        direction="maximize", sampler=optuna.samplers.TPESampler(seed=0)
    )
    # Bound parallel trials: every concurrent fit holds another training matrix.
    study.optimize(
        objective, n_trials=int(search["trials"]), n_jobs=min(2, os.cpu_count() or 1)
    )
    return (study,)


@app.cell
def _(mo, pl, px, study):
    trials = pl.DataFrame(
        [
            {"trial": t.number, "score": t.value, **t.params}
            for t in study.trials
            if t.value is not None
        ]
    )
    trial_figure = px.scatter(
        trials,
        x="learning_rate",
        y="score",
        color="max_depth",
        log_x=True,
        title="Every trial",
        template="plotly_dark" if mo.app_meta().theme == "dark" else "plotly_white",
    )
    mo.vstack(
        [
            mo.md(f"Best score **{study.best_value:.4f}** after {len(trials)} trials."),
            trial_figure,
            trials.sort("score", descending=True),
        ]
    )
    return (trials,)


@app.cell
def _(XGBRegressor, data, features, joblib, os, pathlib, search, study, trials):
    model = XGBRegressor(**study.best_params, n_jobs=2)
    model.fit(data[features].to_numpy(), data[search["target"]].to_numpy())
    out = pathlib.Path(os.environ.get("CROWDCENT_OUT_DIR", "out"))
    for folder in ("models", "trials"):
        (out / folder).mkdir(parents=True, exist_ok=True)
    joblib.dump(model, out / "models" / f"{search['name']}.joblib")
    trials.write_csv(out / "trials" / f"{search['name']}.csv")
    print(f"saved {out / 'models'} and {out / 'trials'}")
    return


if __name__ == "__main__":
    app.run()
