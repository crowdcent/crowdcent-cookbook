"""The public preview contract: discover every recipe and render without credentials."""

import datetime as dt
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from PIL import Image
import plotly.graph_objects as go

from scripts import thumbnails as t
from scripts.thumbnail_render import styled, source_date

SOURCE = """# /// script
# dependencies = ["marimo"]
# [tool.marimo.opengraph]
# title = "A recipe"
# description = "A real output."
# [tool.crowdcent.thumbnail]
# title = "A chart"
# output = "figure"
# figure = "figure"
# label = "Public data"
# ///

import marimo
app = marimo.App()
"""


class ThumbnailTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.root / "scripts").mkdir()
        (self.root / "scripts/thumbnail.css").write_text("body {}")
        (self.root / "pyproject.toml").write_text("")
        (self.root / "uv.lock").write_text("")
        self.recipe("one")

    def recipe(self, slug):
        folder = self.root / "recipes" / slug
        folder.mkdir(parents=True)
        (folder / f"{slug}.py").write_text(SOURCE)
        return folder

    def snapshot(self, slug="one"):
        directory = t.assets(slug, self.root)
        directory.mkdir(parents=True, exist_ok=True)
        snapshot = {
            "schema": 1,
            "data": "real",
            "label": "Public data",
            "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "notebook_sha256": t.notebook_fingerprint(slug, self.root),
            "figures": [
                {"data": [{"type": "scatter", "x": ["2026-01-01"], "y": [0.1]}]}
            ],
            "datasets": {},
        }
        (directory / "output.json").write_text(json.dumps(snapshot))
        Image.new("RGB", (1200, 630)).save(directory / "opengraph.png")
        receipt = {
            **{
                key: snapshot[key] for key in ("schema", "data", "label", "captured_at")
            },
            "source_sha256": t.fingerprint(slug, self.root),
            "image_sha256": hashlib.sha256(
                (directory / "opengraph.png").read_bytes()
            ).hexdigest(),
        }
        (directory / "capture.json").write_text(json.dumps(receipt))
        return directory

    def test_discovery_includes_new_recipe_and_refuses_missing_declaration(self):
        self.recipe("seven")
        self.assertEqual(set(t.recipes(self.root)), {"one", "seven"})
        notebook = self.root / "recipes/seven/seven.py"
        notebook.write_text(
            SOURCE.replace("[tool.crowdcent.thumbnail]", "[tool.other]")
        )
        with self.assertRaisesRegex(ValueError, "seven.*declare"):
            t.recipes(self.root)

    def test_missing_thumbnail_and_snapshot_fail(self):
        with self.assertRaises(ValueError):
            t.check(t.recipes(self.root), self.root)

    def test_check_needs_no_api_or_notebook_execution(self):
        self.snapshot()
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("requests.Session.request", side_effect=AssertionError("network")),
            patch("subprocess.run", side_effect=AssertionError("execution")),
        ):
            t.check(t.recipes(self.root), self.root)

    def test_changed_notebook_or_helper_requires_new_real_capture(self):
        self.snapshot()
        (self.root / "recipes/one/helper.py").write_text("VALUE = 2\n")
        with self.assertRaisesRegex(ValueError, "notebook changed"):
            t.check(["one"], self.root)

    def test_presentation_edit_reuses_snapshot_but_requires_render(self):
        self.snapshot()
        notebook = self.root / "recipes/one/one.py"
        notebook.write_text(
            SOURCE.replace('title = "A chart"', 'title = "Better heading"')
        )
        t.saved_output("one", self.root)
        with self.assertRaisesRegex(ValueError, "thumbnail is stale"):
            t.check(["one"], self.root)

    def test_changed_renderer_or_dependency_lock_requires_render(self):
        self.snapshot()
        (self.root / "uv.lock").write_text("changed environment")
        with self.assertRaisesRegex(ValueError, "thumbnail is stale"):
            t.check(["one"], self.root)

    def test_invalid_png_and_replaced_image_are_refused(self):
        directory = self.snapshot()
        (directory / "opengraph.png").write_bytes(b"\x89PNG\r\n\x1a\nnot an image")
        with self.assertRaises(ValueError):
            t.check(["one"], self.root)
        Image.new("RGB", (1200, 630), "white").save(directory / "opengraph.png")
        with self.assertRaisesRegex(ValueError, "does not match"):
            t.check(["one"], self.root)

    def test_artifact_cannot_escape_output_directory(self):
        notebook = self.root / "recipes/one/one.py"
        notebook.write_text(
            SOURCE.replace('output = "figure"', 'output = "../secret.json"')
        )
        with self.assertRaisesRegex(ValueError, "stay inside"):
            t.recipes(self.root)

    def test_failed_render_does_not_publish_any_selected_assets(self):
        self.snapshot()
        directory = t.assets("one", self.root)
        before = {p.name: p.read_bytes() for p in directory.iterdir()}
        with (
            patch("sys.argv", ["thumbnails.py"]),
            patch.object(t, "recipes", return_value={"one": {}}),
            patch.object(t, "saved_output", return_value={}),
            patch("playwright.sync_api.sync_playwright"),
            patch.object(t, "generate", side_effect=ValueError("render failed")),
        ):
            with self.assertRaisesRegex(ValueError, "render failed"):
                t.main()
        self.assertEqual(before, {p.name: p.read_bytes() for p in directory.iterdir()})

    def test_worker_executes_cli_parameters_and_extracts_named_real_figure(self):
        notebook = self.root / "one.py"
        notebook.write_text(
            SOURCE
            + """
@app.cell
def _():
    import marimo as mo
    import plotly.graph_objects as go
    mo.stop(not mo.cli_args().get("value"))
    figure = go.Figure(go.Scatter(x=[1, 2], y=[0, mo.cli_args()["value"]]))
    figure
    return
"""
        )
        spec = {"output": "figure", "figure": "figure", "args": ["--value=42"]}
        with (
            patch.object(t, "recipes", return_value={"one": spec}),
            patch.object(t, "read_only_client"),
            patch("sys.argv", []),
            patch("sys.path", list(__import__("sys").path)),
            patch.dict("os.environ"),
        ):
            t.worker("one", self.root, self.root)
        result = json.loads((self.root / "capture-output.json").read_text())
        self.assertEqual(result["figures"][0]["data"][0]["y"], [0, 42])

    def test_styling_preserves_all_plotted_values(self):
        original = go.Figure(go.Scatter(x=["2026-01-01", "2026-01-02"], y=[-0.2, 0.1]))
        result = styled(original, {})
        self.assertEqual(tuple(original.data[0].x), tuple(result.data[0].x))
        self.assertEqual(tuple(original.data[0].y), tuple(result.data[0].y))
        self.assertEqual(source_date({"datasets": {}}, result), "2026-01-02")

    def test_large_charts_preserve_slot_identity_without_marker_clutter(self):
        original = go.Figure(
            [
                go.Scattergl(x=[1, 2], y=[20, 80], name=str(slot), mode="lines+markers")
                for slot in (2, 3, 1, 4, 5)
            ]
        )
        result = styled(original, {"legend_prefix": "Slot "})
        self.assertEqual(
            [t.name for t in result.data],
            ["Slot 2", "Slot 3", "Slot 1", "Slot 4", "Slot 5"],
        )
        self.assertEqual(len({t.line.color for t in result.data}), 5)
        for before, after in zip(original.data, result.data):
            self.assertEqual(tuple(before.y), tuple(after.y))
            self.assertEqual(after.mode, "lines")

    def test_capture_blocks_submissions_and_permits_real_simulator_reads(self):
        import crowdcent_challenge as cc

        request = Mock(return_value="real response")
        with (
            patch.object(cc.ChallengeClient, "_request", request),
            patch.object(cc.ChallengeClient, "_download_file"),
            patch.dict("os.environ", {"PYTHON_DOTENV_DISABLED": "1"}),
        ):
            t.read_only_client(self.root)
            client = cc.ChallengeClient(api_key="test-only")
            with self.assertRaisesRegex(RuntimeError, "refuses API writes"):
                client._request("POST", "/challenges/one/submissions/")
            request.assert_not_called()
            self.assertEqual(
                client._request("POST", "/challenges/one/simulator/run/"),
                "real response",
            )

    def test_shared_download_uses_identical_real_bytes_once(self):
        import crowdcent_challenge as cc

        def download(_self, _endpoint, dest, _description):
            Path(dest).write_bytes(b"actual downloaded bytes")

        with (
            patch.object(cc.ChallengeClient, "_request"),
            patch.object(
                cc.ChallengeClient,
                "_download_file",
                side_effect=download,
                autospec=True,
            ) as get,
            patch.dict("os.environ", {"PYTHON_DOTENV_DISABLED": "1"}),
        ):
            t.read_only_client(self.root)
            client = cc.ChallengeClient(api_key="test-only")
            for name in ("first", "second"):
                client._download_file("/training/3/download/", self.root / name, "data")
            self.assertEqual(get.call_count, 1)
            self.assertEqual(
                (self.root / "first").read_bytes(), (self.root / "second").read_bytes()
            )


if __name__ == "__main__":
    unittest.main()
