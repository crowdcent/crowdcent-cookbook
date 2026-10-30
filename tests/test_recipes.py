"""Execute every complete recipe with Cloud's export command and API fixtures."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
_PROXY_VARIABLES = {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}


class RecipeTests(unittest.TestCase):
    def test_every_recipe_has_a_standard_thumbnail(self):
        from scripts.thumbnails import preview

        for notebook in (ROOT / "recipes").glob("*/*.py"):
            if notebook.stem != notebook.parent.name:
                continue
            image = (
                notebook.parent
                / "__marimo__"
                / "assets"
                / notebook.stem
                / "opengraph.png"
            )
            with self.subTest(recipe=notebook.stem):
                preview(notebook.read_text())
                data = image.read_bytes()
                self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
                self.assertEqual(struct.unpack(">II", data[16:24]), (1200, 630))

    def export(
        self,
        recipe,
        *,
        args=(),
        scenario="normal",
        cloud=True,
        success=True,
    ):
        work = Path(self.enterContext(tempfile.TemporaryDirectory()))
        source = ROOT / "recipes" / recipe
        for path in source.glob("*.py"):
            shutil.copy(path, work / path.name)
        hooks = work / "hooks"
        hooks.mkdir()
        (hooks / "sitecustomize.py").write_text(
            "from recipe_fakes import install\ninstall()\n"
        )
        # A laptop's own proxy settings stay out of the recipe's environment.
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("CROWDCENT_") and key.lower() not in _PROXY_VARIABLES
        }
        env.update(
            {
                "PYTHONPATH": os.pathsep.join((str(hooks), str(ROOT / "tests"))),
                "CROWDCENT_API_KEY": "test-only",
                "COOKBOOK_TEST_SCENARIO": scenario,
                "OMP_NUM_THREADS": "2",
                "OPENBLAS_NUM_THREADS": "2",
                "POLARS_MAX_THREADS": "2",
            }
        )
        if cloud:
            env["CROWDCENT_RUN_ID"] = "test-run"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "marimo",
                "export",
                "html",
                str(work / f"{recipe}.py"),
                "--no-sandbox",
                "-o",
                str(work / "report.html"),
                *(["--", *args] if args else []),
            ],
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.output = result.stdout + result.stderr
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((work / "report.html").is_file())
        else:
            self.assertNotEqual(
                result.returncode, 0, "An API failure became a successful report"
            )
        calls_path = work / "calls.jsonl"
        calls = (
            [json.loads(line) for line in calls_path.read_text().splitlines()]
            if calls_path.exists()
            else []
        )
        return work, calls

    def test_hello_writes_a_run_artifact(self):
        work, _ = self.export("hello_cloud")
        self.assertEqual(
            json.loads((work / "out/hello.json").read_text()),
            {"greeting": "hello", "run": "test-run"},
        )

    def test_ranking_trains_predicts_and_serializes_a_submission(self):
        work, calls = self.export("hyperliquid_ranking")
        self.assertIn({"kind": "submission", "rows": 8, "slot": "1"}, calls)
        self.assertTrue((work / "out/predictions.csv").exists())

    def test_ranking_preview_does_not_submit(self):
        _, calls = self.export("hyperliquid_ranking", cloud=False)
        self.assertFalse(any(call["kind"] == "submission" for call in calls))

    def test_performance_renders_scored_history_and_an_empty_account(self):
        for scenario in ("normal", "empty"):
            with self.subTest(scenario=scenario):
                self.export("track_your_performance", scenario=scenario)

    def test_simulation_runs_with_defaults_parameters_and_nullable_stats(self):
        for scenario, args in (
            ("normal", ()),
            ("null_stats", ("--n_long=20", "--leverage=1.5")),
            ("missing_benchmark", ()),
        ):
            with self.subTest(scenario=scenario):
                _, calls = self.export(
                    "simulate_the_meta_model", scenario=scenario, args=args
                )
                run = next(
                    call
                    for call in calls
                    if call.get("endpoint", "").endswith("simulator/run/")
                )
                self.assertEqual(run["payload"]["config"]["n_long"], 20 if args else 10)
                self.assertNotIn("leverage", run["payload"]["config"])

    def test_optuna_fits_and_saves_both_artifacts(self):
        work, _ = self.export(
            "optuna_tuning", args=("--trials=2", "--depth_max=2", "--name=smoke")
        )
        self.assertTrue((work / "out/models/smoke.joblib").exists())
        self.assertEqual(
            len((work / "out/trials/smoke.csv").read_text().splitlines()),
            3,
        )

    def test_zoo_family_writes_a_folder_its_manifest_describes(self):
        import hashlib

        for family, model_files in (
            ("ridge", {"model": "weights.npz"}),
            ("xgboost", {"model": "model.ubj"}),
            ("mlp", {"model": "weights.npz"}),
        ):
            with self.subTest(family=family):
                work, _ = self.export(
                    "zoo_models", args=(f"--family={family}", "--version=3")
                )
                zoo = work / "out/zoo"
                manifest = json.loads((zoo / "manifest.json").read_text())
                self.assertEqual(manifest["ref"], f"{manifest['name']}@3")
                self.assertEqual(manifest["supersedes"], f"{manifest['name']}@2")
                self.assertEqual(manifest["features"], ["feature_0", "feature_1"])
                self.assertEqual(
                    (manifest["challenge"], manifest["data_version"]),
                    ("hyperliquid-ranking", "test"),
                )
                self.assertEqual(
                    {key: entry["name"] for key, entry in manifest["files"].items()},
                    {
                        **model_files,
                        "oof": "oof.parquet",
                        "oof_csv": "oof.csv",
                        "check": "check.csv",
                    },
                )
                self.assertEqual(
                    sorted(p.name for p in zoo.iterdir()),
                    sorted(
                        [
                            *(e["name"] for e in manifest["files"].values()),
                            "manifest.json",
                        ]
                    ),
                )
                for entry in manifest["files"].values():
                    data = (zoo / entry["name"]).read_bytes()
                    self.assertEqual(
                        (entry["bytes"], entry["sha256"]),
                        (len(data), hashlib.sha256(data).hexdigest()),
                    )
                self.assertEqual(
                    manifest["size_bytes"],
                    sum(e["bytes"] for e in manifest["files"].values()),
                )
                evaluation = manifest["evaluation"]
                self.assertEqual(len(evaluation["folds"]), 4)
                self.assertEqual(evaluation["purge_days"], 31)
                for score in (
                    *evaluation["scores"].values(),
                    evaluation["corr_to_meta_30d"],
                ):
                    self.assertIsInstance(score, float)
                oof = (zoo / "oof.csv").read_text().splitlines()
                self.assertEqual(oof[0], "id,date,pred_10d,pred_30d,fold")
                self.assertEqual(
                    {line.rsplit(",", 1)[1] for line in oof[1:]},
                    {"1", "2", "3", "4", "5"},
                )

    def test_zoo_mlp_saves_plain_number_arrays(self):
        import numpy as np

        work, _ = self.export("zoo_models", args=("--family=mlp",))
        with np.load(work / "out/zoo/weights.npz", allow_pickle=False) as weights:
            self.assertEqual(
                sorted(weights.files),
                ["b0", "b1", "b2", "w0", "w1", "w2", "x_mean", "x_scale"],
            )
            self.assertEqual(weights["w0"].shape, (2, 64))

    def test_zoo_blend_refuses_members_trained_on_other_data(self):
        work, _ = self.export("zoo_models", args=("--family=blend",), success=False)
        self.assertIn("hl-ridge-baseline@1 was trained on other data", self.output)
        self.assertFalse((work / "out/zoo/manifest.json").exists())

    def test_zoo_waits_for_the_form_in_an_interactive_notebook(self):
        _, calls = self.export("zoo_models", cloud=False)
        self.assertEqual(calls, [])

    def test_zoo_refuses_an_unknown_family_before_downloading(self):
        _, calls = self.export("zoo_models", args=("--family=forest",), success=False)
        self.assertEqual(calls, [])

    def test_zoo_quickstart_predicts_with_the_chosen_zoo_model_and_submits(self):
        for args, model in (
            (("--model=hl-xgb-baseline",), "hl-xgb-baseline"),
            (("--model=hl-ridge-baseline",), "hl-ridge-baseline"),
            (("--model=hl-mlp-baseline",), "hl-mlp-baseline"),
            (("--model=hl-lstm-baseline",), "hl-lstm-baseline"),
        ):
            with self.subTest(model=model):
                work, calls = self.export("zoo_quickstart", args=args)
                self.assertIn({"kind": "submission", "rows": 8, "slot": "1"}, calls)
                self.assertEqual(
                    [
                        c["path"]
                        for c in calls
                        if c.get("path", "").endswith("/download/")
                    ],
                    [f"/zoo/{model}@1/download/"],
                )
                self.assertFalse(
                    any(
                        c["kind"] == "download" and "training" in c["endpoint"]
                        for c in calls
                    )
                )
                predictions = (work / "out/predictions.csv").read_text().splitlines()
                self.assertEqual(predictions[0], "id,pred_10d,pred_30d")
                self.assertEqual(len(predictions), 9)

    def test_zoo_quickstart_blend_loads_each_member_and_submits(self):
        # With no model named, the quickstart opens on the blend.
        for args in ((), ("--model=hl-blend",)):
            with self.subTest(args=args):
                work, calls = self.export("zoo_quickstart", args=args)
                self.assertIn({"kind": "submission", "rows": 8, "slot": "1"}, calls)
                self.assertEqual(
                    [c["path"] for c in calls if c.get("path", "").endswith("/download/")],
                    ["/zoo/hl-ridge-baseline@1/download/", "/zoo/hl-xgb-baseline@1/download/"],
                )
                predictions = (work / "out/predictions.csv").read_text().splitlines()
                self.assertEqual(len(predictions), 9)

    def test_zoo_quickstart_preview_does_not_submit(self):
        _, calls = self.export("zoo_quickstart", cloud=False)
        self.assertFalse(any(call["kind"] == "submission" for call in calls))

    def test_zoo_quickstart_refuses_weights_that_fail_their_checksum(self):
        _, calls = self.export("zoo_quickstart", scenario="tampered", success=False)
        self.assertFalse(any(call["kind"] == "submission" for call in calls))

    def test_numerai_runs_with_default_and_explicit_account_and_empty_account(self):
        for scenario, args in (
            ("normal", ()),
            ("partial", ()),
            ("empty", ("--account=nobody",)),
        ):
            with self.subTest(scenario=scenario):
                _, calls = self.export(
                    "numerai_dashboard", scenario=scenario, args=args
                )
                self.assertTrue(
                    any(
                        call.get("variables", {}).get("username")
                        == ("nobody" if args else "crowdcent")
                        for call in calls
                    )
                )

    def test_numerai_is_called_directly_with_plain_urllib3(self):
        # The recipe calls Numerai like any laptop would, and nothing else.
        _, calls = self.export("numerai_dashboard")
        self.assertTrue(any(call["kind"] == "numerai" for call in calls))
        self.assertFalse([call for call in calls if call["kind"] != "numerai"], calls)

    def test_interactive_forms_do_not_call_remote_services(self):
        for recipe in ("simulate_the_meta_model", "numerai_dashboard", "optuna_tuning"):
            with self.subTest(recipe=recipe):
                _, calls = self.export(recipe, cloud=False)
                self.assertEqual(calls, [])

    def test_upstream_failure_fails_the_export(self):
        for recipe in (
            "hyperliquid_ranking",
            "track_your_performance",
            "simulate_the_meta_model",
            "optuna_tuning",
            "numerai_dashboard",
            "zoo_models",
            "zoo_quickstart",
        ):
            with self.subTest(recipe=recipe):
                self.export(recipe, scenario="api_failure", success=False)

    def test_bad_optuna_output_name_is_rejected_before_downloading(self):
        _, calls = self.export(
            "optuna_tuning", args=("--name=../../outside",), success=False
        )
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
