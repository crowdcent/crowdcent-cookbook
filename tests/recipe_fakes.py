"""Deterministic API boundaries for full-notebook execution, never recipe data.

The real client still builds requests and serializes submissions. Only network
I/O is replaced; Polars, XGBoost, Optuna, Plotly and marimo all run normally.
"""

import datetime as dt
import functools
import hashlib
import io
import json
import os
from pathlib import Path

import numpy as np
import polars as pl


def record(kind, **values):
    with Path("calls.jsonl").open("a") as output:
        output.write(json.dumps({"kind": kind, **values}) + "\n")


def install():
    import crowdcent_challenge as cc
    import requests
    import urllib3

    scenario = os.environ.get("COOKBOOK_TEST_SCENARIO", "normal")

    def request(self, method, endpoint, **kwargs):
        record(
            "request", method=method, endpoint=endpoint, payload=kwargs.get("json_data")
        )
        if scenario == "api_failure":
            raise RuntimeError("Fixture API unavailable")
        if endpoint.endswith("training_data/latest/"):
            data = {"version": "test"}
        elif endpoint.endswith("inference_data/"):
            data = [{"release_date": "2026-01-01", "id": 1}]
        elif endpoint.endswith("inference_data/2026-01-01/"):
            data = {"release_date": "2026-01-01", "id": 1}
        elif endpoint.endswith("/submissions/") and method == "GET":
            data = (
                []
                if scenario == "empty"
                else [
                    {
                        "id": index,
                        "slot": 1 + index % 2,
                        "status": "evaluated",
                        "inference_data_release_date": f"2026-01-{index + 1:02}",
                        "score_details": {"spearman_10d": 0.1},
                        "percentile_details": {"composite_percentile": 40.0 + index},
                    }
                    for index in range(12)
                ]
            )
        elif endpoint.endswith("/submissions/") and method == "POST":
            name, handle = kwargs["files"]["prediction_file"][:2]
            frame = (
                pl.read_csv(handle)
                if name.endswith(".csv")
                else pl.read_parquet(handle)
            )
            assert frame.columns == ["id", "pred_10d", "pred_30d"]
            assert frame.height == 8
            assert frame.select(
                pl.col("pred_10d", "pred_30d").is_between(0, 1).all()
            ).row(0) == (True, True)
            record("submission", rows=frame.height, slot=kwargs["data"]["slot"])
            data = {"id": 1, "status": "pending"}
        elif endpoint.endswith("/simulator/run/"):
            data = {
                "stats": {
                    "sharpe": 1.1,
                    "cagr": 0.12,
                    "ann_vol": 0.2,
                    "max_drawdown": -0.1,
                },
                "locked": [],
                "web_url": "https://crowdcent.com/",
                "curve": {
                    "dates": ["2026-01-01", "2026-01-02"],
                    "strategy": [0, 0.01],
                    "btc_benchmark": [0, -0.01],
                },
            }
            if scenario == "null_stats":
                data["stats"] = dict.fromkeys(data["stats"])
            if scenario == "missing_benchmark":
                data["curve"]["btc_benchmark"] = [None, None]
        else:
            raise AssertionError(f"Unexpected request {method} {endpoint}")
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(data).encode()
        return response

    def download(self, endpoint, dest_path, *args, **kwargs):
        record("download", endpoint=endpoint)
        if scenario == "api_failure":
            raise RuntimeError("Fixture API unavailable")
        rng = np.random.default_rng(7)
        if "meta_model" in endpoint:
            pl.DataFrame(
                {
                    "id": [f"coin-{i % 8}" for i in range(800)],
                    "release_date": [
                        dt.date(2026, 1, 1) - dt.timedelta(days=i // 8)
                        for i in range(800)
                    ],
                    "pred_10d": rng.uniform(0, 1, 800),
                    "pred_30d": rng.uniform(0, 1, 800),
                }
            ).write_parquet(dest_path)
            return
        training = "training_data" in endpoint
        days = 1000 if training else 1
        count = days * 8
        x = rng.uniform(0, 1, count)
        frame = pl.DataFrame(
            {
                "id": [f"coin-{i % 8}" for i in range(count)],
                "date": [
                    dt.date(2023, 4, 7) + dt.timedelta(days=i // 8)
                    for i in range(count)
                ],
                "feature_0": x,
                "feature_1": rng.uniform(0, 1, count),
            }
        )
        if training:
            # Unresolved labels are present in real training releases.
            target = [float(v) if i < count - 32 else None for i, v in enumerate(x)]
            frame = frame.with_columns(
                pl.Series("target_10d", target), pl.Series("target_30d", target)
            )
        if str(dest_path).endswith(".csv"):
            frame.write_csv(dest_path)
        else:
            frame.write_parquet(dest_path)

    cc.ChallengeClient._request = request
    cc.ChallengeClient._download_file = download

    def numerai_request(method, url, *, json=None, **kwargs):
        assert url == "https://api-tournament.numer.ai/"
        query, variables = json["query"], json.get("variables") or {}
        record("numerai", variables=variables)
        if scenario == "api_failure":
            return urllib3.response.HTTPResponse(body=b"unavailable", status=503)
        if scenario == "partial" and "tournament: 11" in query:
            return urllib3.response.HTTPResponse(
                body=b'{"errors": [{"message": "Signals temporarily unavailable"}]}',
                status=200,
            )
        if "accountProfile" in query:
            models = (
                []
                if scenario == "empty"
                else [{"id": f"id-{variables['tournament']}", "displayName": "example"}]
            )
            data = {"accountProfile": {"models": models}}
        elif "v2RoundModelPerformances" in query:
            data = {
                "m0": [
                    {
                        "roundNumber": 1,
                        "roundResolved": True,
                        "roundResolveTime": "2026-01-01T00:00:00Z",
                        "atRisk": 10,
                        "payout": 0.5,
                    },
                    {
                        "roundNumber": 2,
                        "roundResolved": False,
                        "roundResolveTime": None,
                        "atRisk": 10,
                        "payout": None,
                    },
                ]
            }
        elif "v3UserProfile" in query:
            data = {
                "v3UserProfile": {
                    "roundModelPerformances": [
                        {
                            "roundNumber": 1,
                            "roundResolveTime": "2026-01-01T00:00:00Z",
                            "corr20V2": 0.1,
                            "mmc": 0.2,
                            "corr20V2Percentile": 0.75,
                            "mmcPercentile": None,
                        },
                    ]
                }
            }
        else:
            raise AssertionError(query)
        import json as json_module

        return urllib3.response.HTTPResponse(
            body=json_module.dumps({"data": data}).encode(), status=200
        )

    urllib3.request = numerai_request

    class ProxyManager:
        """A recipe calls the host directly; it never configures a proxy."""

        def __init__(self, *args, **kwargs):
            raise AssertionError(
                "A recipe must not configure a proxy; call the host directly."
            )

    urllib3.ProxyManager = ProxyManager

    def ridge_weights():
        weights = io.BytesIO()
        np.savez(
            weights, coef=np.array([[1.0, -0.5], [0.2, 1.0]]), intercept=np.zeros(2)
        )
        return weights.getvalue()

    def xgboost_model():
        import xgboost

        X = np.random.default_rng(3).uniform(0, 1, (64, 2))
        model = xgboost.XGBRegressor(n_estimators=5, max_depth=2, base_score=0.5)
        return bytes(model.fit(X, X[:, ::-1]).get_booster().save_raw("ubj"))

    def arrays(**values):
        weights = io.BytesIO()
        np.savez(weights, **{k: np.asarray(v, float) for k, v in values.items()})
        return weights.getvalue()

    def mlp_weights():
        return arrays(
            x_mean=[0.5, 0.5], x_scale=[0.25, 0.25],
            w0=[[1.0, -1.0], [0.5, 1.0]], b0=[0.0, 0.1],
            w1=[[1.0, 0.0], [0.0, -1.0]], b1=[0.0, 0.0],
        )

    def lstm_weights():
        # Two steps of one feature each, two hidden units.
        rng = np.random.default_rng(5)
        return arrays(
            x_mean=[0.5, 0.5], x_scale=[0.25, 0.25],
            w_input=rng.normal(size=(1, 8)), w_hidden=rng.normal(size=(2, 8)),
            b=np.zeros(8), w_out=rng.normal(size=(2, 2)), b_out=[0.0, 0.0],
        )

    # The zoo's files, built only when a recipe downloads them.
    zoo_files = {
        "hl-ridge-baseline": ("linear", "Ridge baseline", ridge_weights),
        "hl-xgb-baseline": ("xgboost", "XGBoost baseline", xgboost_model),
        "hl-lgb-baseline": ("lightgbm", "LightGBM baseline", lambda: b"tree\n"),
        "hl-mlp-baseline": ("mlp", "MLP baseline", mlp_weights),
        "hl-lstm-baseline": ("lstm", "LSTM baseline", lstm_weights),
        "hl-blend": ("blend", "Blend", None),
    }

    @functools.cache
    def zoo_entry(name):
        kind, title, build = zoo_files[name]
        content = build() if build else None
        ref = f"{name}@1"
        manifest = {
            "ref": ref,
            "title": title,
            "challenge": "hyperliquid-ranking",
            "data_version": "test",
            "kind": kind,
            # Trained on other data than the fixture's, so a new blend refuses it.
            "data": {"trained_through": "2025-12-01", "training_sha256": "0" * 64},
            "features": ["feature_0", "feature_1"],
            "files": (
                {"model": {"sha256": hashlib.sha256(content).hexdigest()}} if content else {}
            ),
            "evaluation": {
                "scores": {"spearman_10d": 0.05, "spearman_30d": 0.07},
                "folds": [],
                "holdout": {},
            },
        }
        if kind == "blend":
            manifest["members"] = [
                {"ref": "hl-ridge-baseline@1", "weight": 0.5},
                {"ref": "hl-xgb-baseline@1", "weight": 0.5},
            ]
        return {
            "ref": ref,
            "challenge": "hyperliquid-ranking",
            "manifest": manifest,
        }, content

    # A missed mock must fail immediately, never touch a real account.
    def zoo_or_no_network(self, method, url, params=None, **kwargs):
        path = url.split("/api", 1)[-1]
        if not path.startswith("/zoo/"):
            raise AssertionError("Unexpected network request in recipe test")
        record("zoo", method=method, path=path, params=params)
        if scenario == "api_failure":
            raise RuntimeError("Fixture API unavailable")
        response = requests.Response()
        response.status_code = 200
        name = path.split("/")[2].split("@")[0]
        if path == "/zoo/" and params == {"challenge": "hyperliquid-ranking"}:
            listing = [{"ref": f"{n}@1"} for n in zoo_files]
            response._content = json.dumps(listing).encode()
        elif path in (f"/zoo/{name}/", f"/zoo/{name}@1/") and name in zoo_files:
            response._content = json.dumps(zoo_entry(name)[0]).encode()
        elif path == f"/zoo/{name}@1/download/" and params == {"file": "model"}:
            content = zoo_entry(name)[1]
            response._content = b"tampered" if scenario == "tampered" else content
        else:
            raise AssertionError(f"Unexpected zoo request {method} {url}")
        return response

    requests.Session.request = zoo_or_no_network
