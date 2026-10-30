# /// script
# dependencies = [
#     "crowdcent-challenge>=0.2.16",
#     "lightgbm",
#     "marimo",
#     "numpy",
#     "polars",
#     "pyarrow",
#     "scikit-learn",
#     "xgboost",
# ]
#
# [tool.marimo.opengraph]
# title = "How the zoo is made"
# description = "Train one model zoo family on CrowdCent's training data with purged walk-forward folds, score it out-of-sample, and save it in a safe format."
#
# [tool.crowdcent.thumbnail]
# title = "Ridge baseline by fold"
# output = "fold_scores.csv"
# label = "Purged walk-forward · Ridge"
# badge = "OUT-OF-SAMPLE = FOLD 5"
# columns = {fold = "FOLD", spearman_10d = "10-DAY SPEARMAN", spearman_30d = "30-DAY SPEARMAN", "ndcg@40_30d" = "30-DAY NDCG@40"}
# args = ["--family=ridge"]
# needs_api_key = true
# ///

import marimo

__generated_with = "0.24.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import dataclasses
    import datetime as dt
    import hashlib
    import importlib
    import json
    import os
    import pathlib
    import re
    import tempfile
    import time
    from typing import Any, Callable

    import crowdcent_challenge as cc
    import marimo as mo
    import numpy as np
    import polars as pl
    from crowdcent_challenge import scoring

    return (
        Any,
        Callable,
        cc,
        dataclasses,
        dt,
        hashlib,
        importlib,
        json,
        mo,
        np,
        os,
        pathlib,
        pl,
        re,
        scoring,
        tempfile,
        time,
    )


@app.cell
def _(mo):
    mo.md("""
    # How the zoo is made

    Every CrowdCent zoo model comes from this notebook. It trains one family
    on the latest training data, scores it on purged walk-forward folds, and
    saves it in a format that loads as data, never as code. The steps are the
    same for every family, so every zoo model is scored on the same dates.

    1. Download the training data, the latest inference release and the
       meta-model with the CrowdCent Challenge client.
    2. Cut the dates into 4 dev folds and an out-of-sample fold. Each fold
       trains only on dates more than 31 days before it, because a 30-day
       target needs 31 days to resolve.
    3. Fit the family on each fold and predict the dates it never saw.
    4. Fit once more on every labeled row. That fit is the published model.
    5. Save it to `out/zoo/` with its out-of-fold predictions, its predictions
       for the latest release and a `manifest.json`, then load the saved file
       back and check that it predicts the same.

    Pick a family and press **Train**. Cloud runs take parameters such as
    `family=xgboost version=2`. The LSTM trains on a GPU machine, from
    `zoo_models_gpu.py` with `family=lstm`.
    """)
    return


@app.cell
def _(mo):
    DEFAULTS = {"family": "ridge", "version": 1, "name": ""}
    form = (
        mo.md("{family} {version} {name}")
        .batch(
            family=mo.ui.dropdown(
                ["ridge", "xgboost", "lightgbm", "mlp", "blend"],
                value=DEFAULTS["family"],
                label="Family",
            ),
            version=mo.ui.number(1, 999, value=DEFAULTS["version"], label="Version"),
            name=mo.ui.text(
                value=DEFAULTS["name"], label="Name (blank for the default)"
            ),
        )
        .form(submit_button_label="Train")
    )
    form
    return DEFAULTS, form


@app.cell
def _(mo):
    mo.md("""
    ## The families

    A family says how to fit, predict, save and load. `fit` gets the feature
    matrix and both targets and returns a model that predicts both. Each
    family saves in its library's own data format: numpy `.npz` for Ridge,
    the MLP and the LSTM, XGBoost UBJ and LightGBM text. None of them can run
    code when it loads, unlike pickle or joblib. The blend trains nothing. It
    rank-averages other zoo models, so it saves no model file at all.
    """)
    return


@app.cell
def _(Any, Callable, dataclasses):
    @dataclasses.dataclass(frozen=True)
    class Family:
        kind: str
        name: str
        title: str
        summary: str
        library: str
        params: dict
        files: dict
        fit: Callable[[Any, Any], Any]
        predict: Callable[[Any, Any], Any]
        save: Callable[[Any, Any], None]
        load: Callable[[Any], Any]
        # The feature columns in the order the model reads them.
        columns: Callable[[list], list] = list
        # Out-of-fold predictions made some other way than one fit per fold.
        out_of_fold: Callable[..., Any] | None = None

    return (Family,)


@app.cell
def _(mo):
    mo.md("""
    ### Ridge

    A linear model on all features. The weights are two plain number arrays,
    so any surface predicts with one matrix product.
    """)
    return


@app.cell
def _(Family, np):
    def _fit(X, Y):
        from sklearn.linear_model import Ridge

        model = Ridge(alpha=RIDGE_PARAMS["alpha"]).fit(X, Y)
        return {
            "coef": model.coef_.astype(np.float64),
            "intercept": model.intercept_.astype(np.float64),
        }

    def _predict(weights, X):
        return X.astype(np.float64) @ weights["coef"].T + weights["intercept"]

    def _save(weights, folder):
        np.savez(folder / "weights.npz", **weights)

    def _load(folder):
        with np.load(folder / "weights.npz", allow_pickle=False) as stored:
            return {"coef": stored["coef"], "intercept": stored["intercept"]}

    RIDGE_PARAMS = {"alpha": 1.0}
    ridge = Family(
        kind="linear",
        name="hl-ridge-baseline",
        title="Ridge baseline",
        summary="A ridge regression on all features, both horizons.",
        library="numpy",
        params=RIDGE_PARAMS,
        files={"model": "weights.npz"},
        fit=_fit,
        predict=_predict,
        save=_save,
        load=_load,
    )
    return (ridge,)


@app.cell
def _(mo):
    mo.md("""
    ### XGBoost

    1000 trees that predict both horizons at once. `base_score=0.5` keeps
    one starting value for both targets, so XGBoost 2.1 in a Browser tab
    loads the file and predicts exactly what XGBoost 3 does.
    """)
    return


@app.cell
def _(Family):
    def _fit(X, Y):
        import xgboost

        return xgboost.XGBRegressor(**XGB_PARAMS).fit(X, Y).get_booster()

    def _predict(booster, X):
        import xgboost

        return booster.predict(xgboost.DMatrix(X))

    def _save(booster, folder):
        booster.save_model(folder / "model.ubj")

    def _load(folder):
        import xgboost

        booster = xgboost.Booster()
        booster.load_model(folder / "model.ubj")
        return booster

    XGB_PARAMS = {
        "n_estimators": 1000,
        "max_depth": 6,
        "learning_rate": 0.02,
        "base_score": 0.5,
        "random_state": 0,
    }
    xgboost_family = Family(
        kind="xgboost",
        name="hl-xgb-baseline",
        title="XGBoost baseline",
        summary="1000 trees on all features, both horizons.",
        library="xgboost",
        params=XGB_PARAMS,
        files={"model": "model.ubj"},
        fit=_fit,
        predict=_predict,
        save=_save,
        load=_load,
    )
    return (xgboost_family,)


@app.cell
def _(mo):
    mo.md("""
    ### LightGBM

    LightGBM fits one target per model, so this family saves two text files,
    one per horizon.
    """)
    return


@app.cell
def _(Family, np):
    _HORIZONS = ("10d", "30d")

    def _fit(X, Y):
        import lightgbm

        return [
            lightgbm.train(
                LGB_PARAMS, lightgbm.Dataset(X, Y[:, k]), num_boost_round=LGB_ROUNDS
            )
            for k in range(Y.shape[1])
        ]

    def _predict(boosters, X):
        return np.column_stack([booster.predict(X) for booster in boosters])

    def _save(boosters, folder):
        for horizon, booster in zip(_HORIZONS, boosters):
            booster.save_model(folder / f"model_{horizon}.txt")

    def _load(folder):
        import lightgbm

        return [
            lightgbm.Booster(model_file=folder / f"model_{h}.txt") for h in _HORIZONS
        ]

    LGB_ROUNDS = 1000
    LGB_PARAMS = {
        "objective": "regression",
        "learning_rate": 0.02,
        "num_leaves": 31,
        "seed": 0,
        "deterministic": True,
        "verbose": -1,
    }
    lightgbm_family = Family(
        kind="lightgbm",
        name="hl-lgb-baseline",
        title="LightGBM baseline",
        summary="1000 rounds on all features, one model per horizon.",
        library="lightgbm",
        params={**LGB_PARAMS, "num_boost_round": LGB_ROUNDS},
        files={f"model_{h}": f"model_{h}.txt" for h in _HORIZONS},
        fit=_fit,
        predict=_predict,
        save=_save,
        load=_load,
    )
    return (lightgbm_family,)


@app.cell
def _(mo):
    mo.md("""
    ### MLP

    A small neural net: two hidden layers with ReLU, trained by
    scikit-learn. The saved file holds the layer weights as plain arrays,
    so a Browser tab predicts with numpy alone.
    """)
    return


@app.cell
def _(Family, np):
    def _fit(X, Y):
        import warnings

        from sklearn.exceptions import ConvergenceWarning
        from sklearn.neural_network import MLPRegressor

        mean = X.mean(axis=0, dtype=np.float64)
        scale = X.std(axis=0, dtype=np.float64)
        scale[scale == 0] = 1.0
        with warnings.catch_warnings():
            # Five epochs scored best on the dev folds. More epochs overfit.
            warnings.simplefilter("ignore", ConvergenceWarning)
            net = MLPRegressor(**MLP_PARAMS).fit((X - mean) / scale, Y)
        weights = {"x_mean": mean, "x_scale": scale}
        for k, (w, b) in enumerate(zip(net.coefs_, net.intercepts_)):
            weights[f"w{k}"] = w.astype(np.float64)
            weights[f"b{k}"] = b.astype(np.float64)
        return weights

    def _predict(weights, X):
        h = (X.astype(np.float64) - weights["x_mean"]) / weights["x_scale"]
        layers = sum(key.startswith("w") for key in weights)
        for k in range(layers):
            h = h @ weights[f"w{k}"] + weights[f"b{k}"]
            if k < layers - 1:
                h = np.maximum(h, 0.0)
        return h

    def _save(weights, folder):
        np.savez(folder / "weights.npz", **weights)

    def _load(folder):
        with np.load(folder / "weights.npz", allow_pickle=False) as stored:
            return {key: stored[key] for key in stored.files}

    MLP_PARAMS = {
        "hidden_layer_sizes": (64, 32),
        "activation": "relu",
        "alpha": 1e-4,
        "batch_size": 512,
        "learning_rate_init": 1e-3,
        "max_iter": 5,
        "random_state": 0,
    }
    mlp_family = Family(
        kind="mlp",
        name="hl-mlp-baseline",
        title="MLP baseline",
        summary="A two-layer neural net on all features, both horizons.",
        library="numpy",
        params={**MLP_PARAMS, "hidden_layer_sizes": list(MLP_PARAMS["hidden_layer_sizes"])},
        files={"model": "weights.npz"},
        fit=_fit,
        predict=_predict,
        save=_save,
        load=_load,
    )
    return (mlp_family,)


@app.cell
def _(mo):
    mo.md("""
    ### LSTM

    Each feature comes at four lags, 15, 10, 5 and 0 days, so every row is a
    short sequence per asset: four steps of 45 features, oldest first. An
    LSTM reads the steps in order and predicts both horizons from its last
    state. It trains with JAX on a GPU machine, so `zoo_models_gpu.py` runs
    this family, not the form above. Prediction is a numpy loop over the
    four steps, so the saved model also loads in a Browser tab.
    """)
    return


@app.cell
def _(Family, np, re):
    def _columns(features):
        """Oldest lag first, and the same feature order within every lag."""
        lagged = {name: re.fullmatch(r"feature_(\d+)_lag(\d+)", name) for name in features}
        if not all(lagged.values()):
            raise ValueError("The LSTM reads lagged features named feature_<n>_lag<days>.")
        bases = {int(m[1]) for m in lagged.values()}
        lags = {int(m[2]) for m in lagged.values()}
        if len(lags) != LSTM_PARAMS["steps"] or len(features) != len(bases) * len(lags):
            raise ValueError(f"The LSTM needs every feature at {LSTM_PARAMS['steps']} lags.")
        return sorted(features, key=lambda name: (-int(lagged[name][2]), int(lagged[name][1])))

    def _sigmoid(x):
        return 1.0 / (1.0 + np.exp(-x))

    def _predict(weights, X):
        z = (X.astype(np.float64) - weights["x_mean"]) / weights["x_scale"]
        width, hidden = weights["w_input"].shape[0], weights["w_hidden"].shape[0]
        steps = z.reshape(len(z), -1, width)
        h = np.zeros((len(z), hidden))
        c = np.zeros_like(h)
        for t in range(steps.shape[1]):
            gates = steps[:, t] @ weights["w_input"] + h @ weights["w_hidden"] + weights["b"]
            i, f, g, o = np.split(gates, 4, axis=1)
            c = _sigmoid(f) * c + _sigmoid(i) * np.tanh(g)
            h = _sigmoid(o) * np.tanh(c)
        return h @ weights["w_out"] + weights["b_out"]

    def _fit(X, Y):
        import jax
        import jax.numpy as jnp

        print(f"LSTM fit on {jax.devices()[0].platform} ({len(X)} rows)")
        mean = X.mean(axis=0, dtype=np.float64)
        scale = X.std(axis=0, dtype=np.float64)
        scale[scale == 0] = 1.0
        steps, hidden = LSTM_PARAMS["steps"], LSTM_PARAMS["hidden"]
        width = X.shape[1] // steps
        seq = jnp.asarray(((X - mean) / scale).reshape(len(X), steps, width), jnp.float32)
        target = jnp.asarray(Y, jnp.float32)

        keys = jax.random.split(jax.random.PRNGKey(LSTM_PARAMS["seed"]), 3)
        bound = 1.0 / np.sqrt(hidden)
        params = {
            "w_input": jax.random.uniform(keys[0], (width, 4 * hidden), minval=-bound, maxval=bound),
            "w_hidden": jax.random.uniform(keys[1], (hidden, 4 * hidden), minval=-bound, maxval=bound),
            # A forget-gate bias of 1 keeps early state while the net learns.
            "b": jnp.zeros(4 * hidden).at[hidden : 2 * hidden].set(1.0),
            "w_out": jax.random.uniform(keys[2], (hidden, Y.shape[1]), minval=-bound, maxval=bound),
            "b_out": jnp.asarray(Y.mean(axis=0), jnp.float32),
        }

        def forward(p, xs):
            h = jnp.zeros((xs.shape[0], hidden))
            c = jnp.zeros_like(h)
            for t in range(steps):
                gates = xs[:, t] @ p["w_input"] + h @ p["w_hidden"] + p["b"]
                i, f, g, o = jnp.split(gates, 4, axis=1)
                c = jax.nn.sigmoid(f) * c + jax.nn.sigmoid(i) * jnp.tanh(g)
                h = jax.nn.sigmoid(o) * jnp.tanh(c)
            return h @ p["w_out"] + p["b_out"]

        def loss(p, rows):
            return jnp.mean((forward(p, seq[rows]) - target[rows]) ** 2)

        rate, beta1, beta2 = LSTM_PARAMS["learning_rate"], 0.9, 0.999

        @jax.jit
        def step(p, m, v, t, rows):
            grads = jax.grad(loss)(p, rows)
            m = jax.tree.map(lambda a, g: beta1 * a + (1 - beta1) * g, m, grads)
            v = jax.tree.map(lambda a, g: beta2 * a + (1 - beta2) * g * g, v, grads)
            p = jax.tree.map(
                lambda w, a, b: w
                - rate * (a / (1 - beta1**t)) / (jnp.sqrt(b / (1 - beta2**t)) + 1e-8),
                p,
                m,
                v,
            )
            return p, m, v

        m = jax.tree.map(jnp.zeros_like, params)
        v = jax.tree.map(jnp.zeros_like, params)
        order = np.random.default_rng(LSTM_PARAMS["seed"])
        batch, t = LSTM_PARAMS["batch_size"], 0
        for _ in range(LSTM_PARAMS["epochs"]):
            shuffled = order.permutation(len(X))
            for start in range(0, len(X) - batch + 1, batch):
                t += 1
                params, m, v = step(params, m, v, t, jnp.asarray(shuffled[start : start + batch]))
        weights = {key: np.asarray(value, dtype=np.float64) for key, value in params.items()}
        return {"x_mean": mean, "x_scale": scale, **weights}

    def _save(weights, folder):
        np.savez(folder / "weights.npz", **weights)

    def _load(folder):
        with np.load(folder / "weights.npz", allow_pickle=False) as stored:
            return {key: stored[key] for key in stored.files}

    # One pass over the rows scored best on the dev folds. Every extra epoch overfit.
    LSTM_PARAMS = {
        "steps": 4,
        "hidden": 64,
        "epochs": 1,
        "batch_size": 512,
        "learning_rate": 1e-3,
        "seed": 0,
    }
    lstm_family = Family(
        kind="lstm",
        name="hl-lstm-baseline",
        title="LSTM baseline",
        summary="An LSTM over each asset's four feature lags, trained on a GPU.",
        library="jax",
        params=LSTM_PARAMS,
        files={"model": "weights.npz"},
        fit=_fit,
        predict=_predict,
        save=_save,
        load=_load,
        columns=_columns,
    )
    return (lstm_family,)


@app.cell
def _(mo):
    mo.md("""
    ### Blend

    The blend trains nothing. It rank-averages four published zoo models
    with equal weights. Each member already has out-of-fold predictions on
    these same folds, so the blend's out-of-fold predictions are the average
    of theirs, and its out-of-sample score needs no new fit. Its manifest
    names each member by `name@version`, and loading it loads every member.
    """)
    return


@app.cell
def _(
    Family,
    cc,
    hashlib,
    json,
    lightgbm_family,
    mlp_family,
    np,
    pathlib,
    pl,
    ridge,
    tempfile,
    xgboost_family,
):
    _BY_KIND = {f.kind: f for f in (ridge, xgboost_family, lightgbm_family, mlp_family)}
    BLEND_MEMBERS = ["hl-ridge-baseline", "hl-xgb-baseline", "hl-lgb-baseline", "hl-mlp-baseline"]

    def _zoo(path, **params):
        client = cc.ChallengeClient("hyperliquid-ranking")
        response = client.session.get(f"{client.base_url}/zoo/{path}", params=params or None)
        response.raise_for_status()
        return response

    def _download(manifest, key):
        content = _zoo(f"{manifest['ref']}/download/", file=key).content
        if hashlib.sha256(content).hexdigest() != manifest["files"][key]["sha256"]:
            raise ValueError(f"{manifest['ref']} {key} does not match its SHA-256.")
        return content

    def _members(refs):
        weight = 1.0 / len(refs)
        return [(_zoo(f"{ref}/").json()["manifest"], weight) for ref in refs]

    def _load_members(members):
        loaded = []
        for manifest, weight in members:
            family = _BY_KIND[manifest["kind"]]
            folder = pathlib.Path(tempfile.mkdtemp())
            for key, filename in family.files.items():
                (folder / filename).write_bytes(_download(manifest, key))
            loaded.append((manifest, weight, family, family.load(folder)))
        return loaded

    def _rank01(raw):
        return (
            pl.DataFrame(np.asarray(raw), schema=["a", "b"], orient="row")
            .select((pl.all().rank("average") - 1) / (pl.len() - 1))
            .fill_nan(0.5)
            .to_numpy()
        )

    def _fit(X, Y):
        return _load_members(_members(BLEND_MEMBERS))

    def _predict(loaded, X):
        return sum(weight * _rank01(family.predict(model, X)) for _, weight, family, model in loaded)

    def _save(loaded, folder):
        pass

    def _load(folder):
        manifest = json.loads((folder / "manifest.json").read_text())
        return _load_members(
            [(_zoo(f"{m['ref']}/").json()["manifest"], m["weight"]) for m in manifest["members"]]
        )

    def _folds_of(manifest):
        evaluation = manifest["evaluation"]
        holdout = evaluation["holdout"]
        return evaluation["folds"] + [
            {
                "fold": holdout["fold"],
                "train_end": holdout["trained_through"],
                "test_start": holdout["start"],
                "test_end": holdout["end"],
            }
        ]

    def _out_of_fold(labeled, folds, training_sha256, targets):
        expected = [
            {k: v if k == "fold" else v.isoformat() for k, v in row.items() if k != "role"}
            for row in folds.iter_rows(named=True)
        ]
        parts = []
        for manifest, weight in _members(BLEND_MEMBERS):
            if manifest["data"]["training_sha256"] != training_sha256:
                raise ValueError(f"{manifest['ref']} was trained on other data. Train it again first.")
            if _folds_of(manifest) != expected:
                raise ValueError(f"{manifest['ref']} was scored on other folds. Train it again first.")
            parts.append(
                pl.read_csv(_download(manifest, "oof_csv")).with_columns(
                    pl.col("date").str.to_date(), pl.col("pred_10d", "pred_30d") * weight
                )
            )
        blended = (
            pl.concat(parts)
            .group_by("id", "date", "fold")
            .agg(pl.col("pred_10d", "pred_30d").sum(), pl.len().alias("members"))
            .filter(pl.col("members") == len(parts))
            .drop("members")
        )
        return labeled.select("id", "date", *targets).join(blended, on=["id", "date"])

    blend_family = Family(
        kind="blend",
        name="hl-blend",
        title="Blend",
        summary="Ridge, XGBoost, LightGBM and the MLP, rank-averaged with equal weights.",
        library="numpy",
        params={"members": BLEND_MEMBERS, "weights": "equal"},
        files={},
        fit=_fit,
        predict=_predict,
        save=_save,
        load=_load,
        out_of_fold=_out_of_fold,
    )
    return (blend_family,)


@app.cell
def _(
    DEFAULTS,
    blend_family,
    form,
    lightgbm_family,
    lstm_family,
    mlp_family,
    mo,
    os,
    re,
    ridge,
    xgboost_family,
):
    FAMILIES = {
        "ridge": ridge,
        "xgboost": xgboost_family,
        "lightgbm": lightgbm_family,
        "mlp": mlp_family,
        "lstm": lstm_family,
        "blend": blend_family,
    }
    answered = dict(mo.cli_args()) or form.value
    mo.stop(
        not answered and not os.environ.get("CROWDCENT_RUN_ID"),
        mo.md("Pick a family and press **Train**."),
    )
    config = {**DEFAULTS, **(answered or {})}
    if config["family"] not in FAMILIES:
        raise ValueError(f"family must be one of {', '.join(FAMILIES)}.")
    family = FAMILIES[config["family"]]
    name = str(config["name"]).strip() or family.name
    version = int(config["version"])
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) or not 1 <= version <= 999:
        raise ValueError(
            "name must be lowercase letters, digits and hyphens, and version a whole number from 1."
        )
    mo.md(f"Training **{family.title}** as `{name}@{version}`.")
    return config, family, name, version


@app.cell
def _(cc, family, hashlib, pathlib, pl, tempfile):
    downloads = pathlib.Path(tempfile.mkdtemp())
    client = cc.ChallengeClient("hyperliquid-ranking")
    training_info = client.get_training_dataset("latest")
    client.download_training_dataset("latest", downloads / "training_data.parquet")
    training_sha256 = hashlib.sha256(
        (downloads / "training_data.parquet").read_bytes()
    ).hexdigest()
    release = client.get_inference_data("latest")["release_date"][:10]
    client.download_inference_data(release, downloads / "inference_data.csv")
    client.download_meta_model(downloads / "meta_model.parquet")

    training = pl.read_parquet(
        downloads / "training_data.parquet", use_pyarrow=True
    ).with_columns(pl.col("date").cast(pl.Date))
    inference = pl.read_csv(downloads / "inference_data.csv")
    meta = pl.read_parquet(downloads / "meta_model.parquet", use_pyarrow=True)
    features = family.columns([c for c in training.columns if c.startswith("feature_")])
    targets = ["target_10d", "target_30d"]
    labeled = training.filter(pl.all_horizontal(pl.col(targets).is_not_null()))
    missing = [c for c in features if c not in inference.columns]
    if not features or labeled.is_empty() or missing:
        raise ValueError(
            "The training data needs features and resolved targets, and the inference "
            f"release needs every feature{f' (it lacks {missing[0]})' if missing else ''}."
        )
    print(
        f"{family.title}: {labeled.height} labeled rows, {len(features)} features, release {release}"
    )
    return (
        features,
        inference,
        labeled,
        meta,
        release,
        targets,
        training_info,
        training_sha256,
    )


@app.cell
def _(mo):
    mo.md("""
    ## The folds

    The out-of-sample block is the last 180 dates with a 30-day target. The 4
    dev folds are the 180-date blocks before it, with 31 days between the last
    dev fold and the out-of-sample block. Every fold trains on dates more than
    31 days before its first date. Together they give each of those rows an
    out-of-fold prediction, and the out-of-sample scores are the ones on the
    model card.
    """)
    return


@app.cell
def _(dt, labeled, pl):
    GAP = dt.timedelta(days=31)
    FOLD_DATES = 180
    dates = labeled["date"].unique().sort()
    holdout_dates = dates[-FOLD_DATES:]
    dev_dates = dates.filter(dates < holdout_dates[0] - GAP)
    if len(dev_dates) < 4 * FOLD_DATES:
        raise ValueError(
            "The training data is too short for 4 dev folds and an out-of-sample block."
        )
    blocks = [dev_dates[-(4 - k) * FOLD_DATES :][:FOLD_DATES] for k in range(4)] + [
        holdout_dates
    ]
    folds = pl.DataFrame(
        {
            "fold": [1, 2, 3, 4, 5],
            "role": ["dev"] * 4 + ["out-of-sample"],
            "train_end": [block[0] - GAP - dt.timedelta(days=1) for block in blocks],
            "test_start": [block[0] for block in blocks],
            "test_end": [block[-1] for block in blocks],
        }
    )
    folds
    return (folds,)


@app.cell
def _(mo):
    mo.md("""
    ## Train and score

    Predictions are ranked within each date and scaled to 0 to 1, the shape a
    submission has. Each date is scored with the challenge's own metrics from
    `crowdcent_challenge.scoring`, and the table shows the mean per fold.
    """)
    return


@app.cell
def _(np, pl, scoring):
    def ranked(frame):
        return frame.with_columns(
            ((pl.col(c).rank("average").over("date") - 1) / (pl.len().over("date") - 1))
            .fill_nan(0.5)
            .fill_null(0.5)
            .alias(c)
            for c in ("pred_10d", "pred_30d")
        )

    def daily_scores(frame, meta):
        rows = []
        joined = frame.join(
            meta.rename({"pred_10d": "meta_10d", "pred_30d": "meta_30d"}).with_columns(
                pl.col("release_date").cast(pl.Date)
            ),
            left_on=["id", pl.col("date").dt.offset_by("1d")],
            right_on=["id", "release_date"],
            how="left",
        )
        for (date,), day in joined.group_by(["date"], maintain_order=True):
            arrays = {
                c: day[c].to_numpy() for c in day.columns if c not in ("id", "date")
            }
            row = {
                "date": date,
                **scoring.evaluate_hyperliquid_submission(
                    arrays["target_10d"],
                    arrays["pred_10d"],
                    arrays["target_30d"],
                    arrays["pred_30d"],
                ),
            }
            has_meta = day["meta_10d"].is_not_null()
            if has_meta.sum() > 1:
                row["corr_to_meta_10d"] = scoring.corr_to_meta(
                    arrays["pred_10d"][has_meta.to_numpy()],
                    arrays["meta_10d"][has_meta.to_numpy()],
                )
                row["corr_to_meta_30d"] = scoring.corr_to_meta(
                    arrays["pred_30d"][has_meta.to_numpy()],
                    arrays["meta_30d"][has_meta.to_numpy()],
                )
            rows.append(row)
        return pl.DataFrame(rows, infer_schema_length=None).with_columns(
            pl.col(pl.Float64).fill_nan(None)
        )

    def matrix(frame, columns):
        return frame.select(columns).to_numpy().astype(np.float32)

    return daily_scores, matrix, ranked


@app.cell
def _(
    daily_scores,
    family,
    features,
    folds,
    labeled,
    matrix,
    meta,
    pathlib,
    pl,
    ranked,
    targets,
    time,
    training_sha256,
):
    started = time.time()

    def _walk_forward():
        for fold in folds.iter_rows(named=True):
            fold_start = time.time()
            train = labeled.filter(pl.col("date") <= fold["train_end"])
            test = labeled.filter(
                pl.col("date").is_between(fold["test_start"], fold["test_end"])
            )
            model = family.fit(matrix(train, features), matrix(train, targets))
            predicted = family.predict(model, matrix(test, features))
            print(
                f"fold {fold['fold']} ({fold['role']}): trained on {train.height} rows, "
                f"predicted {test.height} in {time.time() - fold_start:.0f}s"
            )
            yield test.select("id", "date", *targets).with_columns(
                pl.Series("pred_10d", predicted[:, 0]),
                pl.Series("pred_30d", predicted[:, 1]),
                pl.lit(fold["fold"]).alias("fold"),
            )

    oof_parts = (
        [family.out_of_fold(labeled, folds, training_sha256, targets)]
        if family.out_of_fold
        else list(_walk_forward())
    )
    oof = ranked(pl.concat(oof_parts))
    daily = daily_scores(oof.drop("fold"), meta).join(
        oof.select("date", "fold").unique(), on="date"
    )
    fold_scores = daily.group_by("fold").agg(pl.exclude("date").mean()).sort("fold")
    pathlib.Path("out").mkdir(exist_ok=True)
    fold_scores.select("fold", "spearman_10d", "spearman_30d", "ndcg@40_30d").write_csv(
        "out/fold_scores.csv", float_precision=4
    )
    fold_scores
    return daily, oof, started


@app.cell
def _(mo):
    mo.md("""
    ## The published model

    The last fit uses every labeled row. It predicts the latest inference
    release, and those predictions go into `check.csv`, so anyone who loads
    the published file can check that it predicts the same.
    """)
    return


@app.cell
def _(family, features, inference, labeled, matrix, pl, ranked, targets, time):
    final_start = time.time()
    final_model = family.fit(matrix(labeled, features), matrix(labeled, targets))
    final_raw = family.predict(final_model, matrix(inference, features))
    check = ranked(
        inference.select("id", "date").with_columns(
            pl.Series("pred_10d", final_raw[:, 0]),
            pl.Series("pred_30d", final_raw[:, 1]),
        )
    ).drop("date")
    print(f"final fit on {labeled.height} rows in {time.time() - final_start:.0f}s")
    check.sort("pred_30d", descending=True).head()
    return check, final_model, final_raw


@app.cell
def _(mo):
    mo.md("""
    ## Save to `out/zoo/`

    The folder holds the model file, `oof.parquet` and its CSV copy,
    `check.csv` and `manifest.json`. The manifest names every file with its
    size and SHA-256, the exact feature order, the folds and the out-of-sample
    scores.
    """)
    return


@app.cell
def _(
    check,
    config,
    daily,
    family,
    features,
    final_model,
    folds,
    hashlib,
    importlib,
    json,
    labeled,
    name,
    oof,
    os,
    pathlib,
    pl,
    release,
    started,
    targets,
    time,
    training_info,
    training_sha256,
    version,
):
    zoo = pathlib.Path("out") / "zoo"
    zoo.mkdir(parents=True, exist_ok=True)
    for stale in zoo.iterdir():
        stale.unlink()
    family.save(final_model, zoo)
    oof_frame = oof.select("id", "date", "pred_10d", "pred_30d", "fold")
    oof_frame.write_parquet(zoo / "oof.parquet", use_pyarrow=True)
    oof_frame.write_csv(zoo / "oof.csv")
    check.write_csv(zoo / "check.csv")

    def _entry(filename, **extra):
        data = (zoo / filename).read_bytes()
        return {
            "name": filename,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            **extra,
        }

    def _iso(value):
        return value.isoformat()

    files = {key: _entry(filename) for key, filename in family.files.items()}
    files |= {
        "oof": _entry("oof.parquet"),
        "oof_csv": _entry("oof.csv"),
        "check": _entry("check.csv", release=release),
    }
    holdout = folds.row(4, named=True)
    holdout_daily = daily.filter(pl.col("fold") == 5)
    means = {
        c: holdout_daily[c].mean()
        for c in holdout_daily.columns
        if c not in ("date", "fold")
    }
    manifest = {
        "schema": 1,
        "ref": f"{name}@{version}",
        "name": name,
        "version": version,
        "title": family.title,
        "summary": family.summary,
        "challenge": "hyperliquid-ranking",
        "data_version": training_info["version"],
        "author": "crowdcent",
        "license": "Apache-2.0",
        "kind": family.kind,
        "data": {
            "training_version": training_info["version"],
            "trained_through": _iso(labeled["date"].max()),
            "training_sha256": training_sha256,
            "rows": labeled.height,
        },
        "features": features,
        "targets": targets,
        "outputs": ["pred_10d", "pred_30d"],
        "files": files,
        "library": {
            family.library: importlib.import_module(family.library).__version__
        },
        "training": {
            "recipe": "zoo-models",
            "family": config["family"],
            "cookbook_commit": None,
            "run": os.environ.get("CROWDCENT_RUN_ID") or None,
            "params": family.params,
            "seeds": [0],
            "machine": None,
            "minutes": round((time.time() - started) / 60, 1),
        },
        "evaluation": {
            "scheme": "purged walk-forward",
            "purge_days": 31,
            "folds": [
                {
                    "fold": f["fold"],
                    "train_end": _iso(f["train_end"]),
                    "test_start": _iso(f["test_start"]),
                    "test_end": _iso(f["test_end"]),
                }
                for f in folds.head(4).iter_rows(named=True)
            ],
            "holdout": {
                "fold": 5,
                "start": _iso(holdout["test_start"]),
                "end": _iso(holdout["test_end"]),
                "trained_through": _iso(holdout["train_end"]),
            },
            "scores": {
                k: means[k]
                for k in ("spearman_10d", "spearman_30d", "ndcg@40_10d", "ndcg@40_30d")
            },
            "corr_to_meta_10d": means.get("corr_to_meta_10d"),
            "corr_to_meta_30d": means.get("corr_to_meta_30d"),
        },
        **(
            {"members": [{"ref": m["ref"], "weight": w} for m, w, _, _ in final_model]}
            if family.kind == "blend"
            else {}
        ),
        "size_bytes": sum(entry["bytes"] for entry in files.values()),
        "supersedes": f"{name}@{version - 1}" if version > 1 else None,
    }
    (zoo / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {zoo}: {', '.join(sorted(p.name for p in zoo.iterdir()))}")
    return manifest, zoo


@app.cell
def _(mo):
    mo.md("""
    ## Load it back

    The saved file goes through the family's loader, the same way a member
    loads a zoo model, and must predict the latest release exactly as the
    model in memory did.
    """)
    return


@app.cell
def _(family, final_raw, inference, manifest, matrix, mo, np, zoo):
    reloaded = family.predict(family.load(zoo), matrix(inference, manifest["features"]))
    difference = float(
        np.abs(
            np.asarray(reloaded, dtype=np.float64)
            - np.asarray(final_raw, dtype=np.float64)
        ).max()
    )
    if difference != 0.0:
        raise ValueError(
            f"The saved model predicts differently after loading (largest difference {difference})."
        )
    print(f"reloaded {manifest['ref']}: identical predictions on {len(reloaded)} ids")
    mo.vstack(
        [
            mo.md(
                f"Reloaded `{manifest['ref']}` predicts the {manifest['files']['check']['release']} release identically."
            ),
            mo.json(manifest["evaluation"]),
        ]
    )
    return


if __name__ == "__main__":
    app.run()
