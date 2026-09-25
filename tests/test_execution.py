"""Exercise the recipes' real UI gates under Cloud's marimo HTML exporter.

Keep the button/form cells verbatim, replacing training and API calls with
local inputs and recorded outputs. No credentials or recipe dependencies
are needed beyond marimo.
"""

import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


RECIPES = Path(__file__).resolve().parents[1] / "recipes"
SETUP = """
import marimo
app = marimo.App()

@app.cell
def _():
    import json
    import os
    from pathlib import Path
    import marimo as mo
    return json, mo, os, Path
"""


def control_cells(recipe, control):
    """Read the cells that create or consume a particular notebook control."""
    source = (RECIPES / recipe / f"{recipe}.py").read_text()
    cells = []
    for node in ast.parse(source).body:
        if not isinstance(node, ast.FunctionDef):
            continue
        defines = {
            name.id
            for statement in node.body
            if isinstance(statement, ast.Return) and statement.value is not None
            for name in ast.walk(statement.value)
            if isinstance(name, ast.Name)
        }
        uses = {arg.arg for arg in node.args.args}
        if control in defines | uses:
            cells.append("@app.cell\n" + ast.get_source_segment(source, node))
    if len(cells) != 2:
        raise AssertionError(f"Expected two cells for {recipe}'s {control}")
    return "\n\n".join(cells)


class ExecutionTests(unittest.TestCase):
    def export(self, source, artifact, *, run_id=None, args=()):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            notebook = work / "notebook.py"
            notebook.write_text(textwrap.dedent(SETUP) + source)
            env = dict(os.environ)
            env.pop("CROWDCENT_RUN_ID", None)
            if run_id is not None:
                env["CROWDCENT_RUN_ID"] = run_id
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "marimo",
                    "export",
                    "html",
                    str(notebook),
                    "--no-sandbox",
                    "-o",
                    str(work / "report.html"),
                    *(["--", *args] if args else []),
                ],
                cwd=work,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((work / "report.html").is_file())
            output = work / artifact
            return json.loads(output.read_text()) if output.exists() else None

    def submission(self, **kwargs):
        inputs = """
@app.cell
def _(json, Path):
    from types import SimpleNamespace
    client = SimpleNamespace(submit_predictions=lambda **values:
        Path("submission.json").write_text(json.dumps(values)))
    predictions = [{"id": "example", "pred_10d": 0.5, "pred_30d": 0.6}]
    return client, predictions
"""
        return self.export(
            inputs + control_cells("hyperliquid_ranking", "submit"),
            "submission.json",
            **kwargs,
        )

    def search(self, **kwargs):
        output = """

@app.cell
def _(json, Path, search):
    Path("search.json").write_text(json.dumps(search))
    return
"""
        return self.export(
            control_cells("optuna_tuning", "search_form") + output,
            "search.json",
            **kwargs,
        )

    def test_cloud_run_submits_without_clicking(self):
        self.assertEqual(
            self.submission(run_id="run-1"),
            {"df": [{"id": "example", "pred_10d": 0.5, "pred_30d": 0.6}], "slot": 1},
        )

    def test_opening_notebook_does_not_submit(self):
        self.assertIsNone(self.submission())

    def test_empty_run_id_does_not_submit(self):
        self.assertIsNone(self.submission(run_id=""))

    def test_cloud_run_tunes_with_defaults(self):
        self.assertEqual(
            self.search(run_id="run-1"),
            {
                "trials": 30,
                "depth_max": 8,
                "lr_min": 0.01,
                "lr_max": 0.3,
                "target": "target_10d",
                "name": "best",
            },
        )

    def test_cloud_parameters_override_defaults(self):
        search = self.search(
            run_id="run-1", args=("--trials=5", "--lr_max=0.2", "--name=study")
        )
        self.assertEqual(search["trials"], 5)
        self.assertEqual(search["lr_max"], 0.2)
        self.assertEqual(search["name"], "study")
        self.assertEqual(search["target"], "target_10d")
        self.assertEqual(search["depth_max"], 8)

    def test_opening_notebook_waits_for_tuning_form(self):
        self.assertIsNone(self.search())

    def test_explicit_cli_parameters_still_work_outside_cloud(self):
        search = self.search(args=("--trials=5",))
        self.assertEqual(search["trials"], 5)
        self.assertEqual(search["depth_max"], 8)


if __name__ == "__main__":
    unittest.main()
