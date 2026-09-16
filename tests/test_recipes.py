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

    def export(self, recipe, *, args=(), scenario="normal", cloud=True, success=True):
        work = Path(self.enterContext(tempfile.TemporaryDirectory()))
        source = ROOT / "recipes" / recipe
        for path in source.glob("*.py"):
            shutil.copy(path, work / path.name)
        hooks = work / "hooks"
        hooks.mkdir()
        (hooks / "sitecustomize.py").write_text(
            "from recipe_fakes import install\ninstall()\n"
        )
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("CROWDCENT_")
        }
        env.update(
            {
                "PYTHONPATH": os.pathsep.join((str(hooks), str(ROOT / "tests"))),
                "CROWDCENT_API_KEY": "test-only",
                "CROWDCENT_OUT_DIR": str(work / "artifacts" / "output"),
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
            json.loads((work / "artifacts/output/hello.json").read_text()),
            {"greeting": "hello", "run": "test-run"},
        )

    def test_ranking_trains_predicts_and_serializes_a_submission(self):
        work, calls = self.export("hyperliquid_ranking")
        self.assertIn({"kind": "submission", "rows": 8, "slot": "1"}, calls)
        self.assertTrue((work / "artifacts/output/predictions.csv").exists())

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
        self.assertTrue((work / "artifacts/output/models/smoke.joblib").exists())
        self.assertEqual(
            len((work / "artifacts/output/trials/smoke.csv").read_text().splitlines()),
            3,
        )

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
