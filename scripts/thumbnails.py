"""Build, review and check cookbook thumbnails from actual notebook outputs."""

import argparse
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import tomllib
import warnings
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {"__marimo__", "__pycache__"}


def metadata(source):
    block = re.search(r"(?ms)^# /// script\n(.*?)^# ///$", source)
    if not block:
        raise ValueError("Missing PEP 723 script metadata.")
    return tomllib.loads(
        "\n".join(line.removeprefix("# ") for line in block[1].splitlines())
    )


def preview(source):
    card = metadata(source)["tool"]["marimo"]["opengraph"]
    if any(
        not isinstance(card.get(k), str) or not card[k].strip()
        for k in ("title", "description")
    ):
        raise ValueError("Every recipe needs an OpenGraph title and description.")
    return card


def project_files(folder):
    for path in sorted(folder.rglob("*")):
        parts = path.relative_to(folder).parts
        if any(part.startswith(".") or part in IGNORED for part in parts):
            continue
        if path.is_symlink():
            raise ValueError(f"Recipe files cannot be symlinks: {path}")
        if path.is_file():
            yield path


def recipes(root=ROOT):
    found = {}
    for folder in sorted((root / "recipes").iterdir()):
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        notebook = folder / f"{folder.name}.py"
        source = notebook.read_text()
        preview(source)
        spec = metadata(source).get("tool", {}).get("crowdcent", {}).get("thumbnail")
        if not isinstance(spec, dict) or not all(
            isinstance(spec.get(k), str) and spec[k].strip()
            for k in ("title", "output", "label")
        ):
            raise ValueError(
                f"{folder.name}: declare [tool.crowdcent.thumbnail] with title, output and label."
            )
        output = Path(spec["output"])
        if output.is_absolute() or ".." in output.parts or "\\" in str(output):
            raise ValueError(
                f"{folder.name}: thumbnail output must stay inside the notebook's output directory."
            )
        if spec["output"] != "figure" and output.suffix not in {".csv", ".json"}:
            raise ValueError(
                f"{folder.name}: choose figure, a CSV table or a JSON artifact."
            )
        if spec["output"] == "figure" and not (
            isinstance(spec.get("figure"), str) and spec["figure"].isidentifier()
        ):
            raise ValueError(
                f"{folder.name}: name the notebook's Plotly figure variable with figure."
            )
        if not isinstance(spec.get("args", []), list) or not all(
            isinstance(a, str) and a.startswith("--") for a in spec.get("args", [])
        ):
            raise ValueError(f"{folder.name}: thumbnail args must be CLI arguments.")
        found[folder.name] = spec
    if not found:
        raise ValueError("No recipes found.")
    return found


def fingerprint(slug, root=ROOT):
    paths = [
        root / "recipes" / slug / f"{slug}.py",
        assets(slug, root) / "output.json",
        root / "pyproject.toml",
        root / "uv.lock",
    ]
    paths += sorted((root / "scripts").glob("thumbnail*"))
    digest = hashlib.sha256()
    for path in paths:
        if path.is_file():
            digest.update(
                path.relative_to(root).as_posix().encode()
                + b"\0"
                + path.read_bytes()
                + b"\0"
            )
    return digest.hexdigest()


def notebook_fingerprint(slug, root=ROOT):
    """Presentation edits can reuse a capture; computation/dependency edits cannot."""
    digest = hashlib.sha256()
    notebook = root / "recipes" / slug / f"{slug}.py"
    info = metadata(notebook.read_text())
    spec = info["tool"]["crowdcent"]["thumbnail"]
    settings = {
        "dependencies": info["dependencies"],
        "args": spec.get("args", []),
        "output": spec["output"],
        "figure": spec.get("figure", 0),
    }
    digest.update(json.dumps(settings, sort_keys=True).encode())
    for path in project_files(notebook.parent):
        content = path.read_bytes()
        if path == notebook:
            content = re.sub(rb"(?ms)^# /// script\n.*?^# ///\n", b"", content)
        digest.update(
            path.relative_to(notebook.parent).as_posix().encode()
            + b"\0"
            + content
            + b"\0"
        )
    return digest.hexdigest()


def assets(slug, root=ROOT):
    return root / "recipes" / slug / "__marimo__" / "assets" / slug


def saved_output(slug, root=ROOT):
    path = assets(slug, root) / "output.json"
    if path.stat().st_size > 1_000_000:
        raise ValueError(f"{slug}: saved preview output exceeds 1 MB.")
    captured = json.loads(path.read_text())
    if captured.get("schema") != 1 or captured.get("data") != "real":
        raise ValueError(f"{slug}: a real notebook output snapshot is required.")
    if captured.get("notebook_sha256") != notebook_fingerprint(slug, root):
        raise ValueError(
            f"{slug}: notebook changed; run --capture --recipe {slug} to refresh its real output."
        )
    dt.datetime.fromisoformat(captured["captured_at"])
    if not captured.get("label"):
        raise ValueError(f"{slug}: the snapshot needs an account/source label.")
    return captured


def validate_png(data):
    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        if image.format != "PNG" or image.size != (1200, 630) or len(data) > 1_000_000:
            raise ValueError("expected a 1200 × 630 PNG under 1 MB")
        image.verify()
    with Image.open(io.BytesIO(data)) as image:
        image.load()


def check(slugs, root=ROOT):
    errors = []
    for slug in slugs:
        try:
            saved_output(slug, root)
            directory = assets(slug, root)
            data = (directory / "opengraph.png").read_bytes()
            receipt = json.loads((directory / "capture.json").read_text())
            validate_png(data)
            if receipt.get("schema") != 1 or receipt.get("data") != "real":
                raise ValueError("missing real-data capture metadata")
            if receipt.get("source_sha256") != fingerprint(slug, root):
                raise ValueError(
                    "thumbnail is stale; regenerate it after changing source or renderer"
                )
            if receipt.get("image_sha256") != hashlib.sha256(data).hexdigest():
                raise ValueError("image does not match its capture metadata")
            dt.datetime.fromisoformat(receipt["captured_at"])
            if not receipt.get("label"):
                raise ValueError("missing source label")
        except (OSError, ValueError, KeyError) as exc:
            errors.append(f"{slug}: {exc}")
    if errors:
        raise ValueError("\n".join(errors))


def read_only_client(cache):
    """A capture guard, not a sandbox: recipes are trusted code. Data stays real."""
    import crowdcent_challenge as cc

    request = cc.ChallengeClient._request
    download = cc.ChallengeClient._download_file
    if os.environ.get("COOKBOOK_API_URL"):
        cc.ChallengeClient.DEFAULT_BASE_URL = os.environ["COOKBOOK_API_URL"]

    def guarded(self, method, endpoint, *args, **kwargs):
        if method.upper() not in {"GET", "HEAD"} and not (
            method.upper() == "POST" and endpoint.endswith("/simulator/run/")
        ):
            raise RuntimeError(
                "Thumbnail capture refuses API writes, including submissions."
            )
        return request(self, method, endpoint, *args, **kwargs)

    def cached(self, endpoint, dest_path, description):
        # The destination's extension picks the format, so the cache keeps it.
        suffix = Path(dest_path).suffix
        digest = hashlib.sha256((self.base_url + endpoint + suffix).encode()).hexdigest()
        path = cache / f"{digest}{suffix}"
        if not path.exists():
            download(self, endpoint, str(path), description)
        shutil.copyfile(path, dest_path)

    cc.ChallengeClient._request = guarded
    cc.ChallengeClient._download_file = cached


def worker(slug, work, cache):
    import polars as pl
    import plotly.graph_objects as go

    spec = recipes()[slug]
    read_only_client(cache)
    warnings.filterwarnings(
        "error",
        category=UserWarning,
        message=r".*(is unavailable|rounds are incomplete):",
    )
    os.environ.pop("CROWDCENT_RUN_ID", None)
    os.environ.pop("MARIMO_SCRIPT_EDIT", None)
    sys.path.insert(0, str(work))
    notebook = work / f"{slug}.py"
    sys.argv = [str(notebook), *spec.get("args", [])]
    _, definitions = runpy.run_path(str(notebook))["app"].run()
    captured = {"figures": [], "datasets": {}}
    if spec["output"] == "figure":
        figure = definitions.get(spec["figure"])
        if not isinstance(figure, go.Figure) or not figure.data:
            raise ValueError(
                f"{slug}: notebook produced no figure named {spec['figure']}."
            )
        captured["figures"] = [json.loads(figure.to_json())]
    for path in sorted([*work.glob("*.parquet"), *work.glob("*.csv")]):
        frame = (
            pl.scan_parquet(path)
            if path.suffix == ".parquet"
            else pl.scan_csv(path, try_parse_dates=True)
        )
        through = (
            frame.select(pl.col("date").max()).collect().item()
            if "date" in frame.collect_schema()
            else None
        )
        captured["datasets"][path.name] = {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "through": str(through)[:10] if through else None,
        }
    (work / "capture-output.json").write_text(json.dumps(captured))


def capture(slug, spec, work, cache):
    source_hash = notebook_fingerprint(slug)
    if spec.get("needs_api_key") and not os.environ.get("CROWDCENT_API_KEY"):
        raise ValueError(f"{slug}: set CROWDCENT_API_KEY in your environment.")
    if spec.get("account_label") and not os.environ.get("COOKBOOK_CAPTURE_ACCOUNT"):
        raise ValueError(
            f"{slug}: set COOKBOOK_CAPTURE_ACCOUNT to the key owner's public account name."
        )
    for path in project_files(ROOT / "recipes" / slug):
        target = work / path.relative_to(ROOT / "recipes" / slug)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    requirements = work / "capture-requirements.txt"
    requirements.write_text(
        "\n".join(metadata((work / f"{slug}.py").read_text())["dependencies"])
    )
    env = {
        **os.environ,
        "OMP_NUM_THREADS": "2",
        "OPENBLAS_NUM_THREADS": "2",
        "POLARS_MAX_THREADS": "2",
        "PYTHON_DOTENV_DISABLED": "1",
    }
    env.pop("PYTHONPATH", None)
    subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(ROOT),
            "--no-sync",
            "--with-requirements",
            str(requirements),
            "python",
            str(Path(__file__).resolve()),
            "--worker",
            slug,
            str(work),
            str(cache),
        ],
        cwd=work,
        env=env,
        check=True,
        timeout=900,
    )
    captured = json.loads((work / "capture-output.json").read_text())
    label = spec["label"]
    if spec.get("account_label"):
        label = f"Account · {os.environ['COOKBOOK_CAPTURE_ACCOUNT']}"
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    if spec["output"] != "figure":
        output = work / "out" / spec["output"]
        if output.suffix == ".json":
            captured["artifact"] = json.loads(output.read_text())
        else:
            import polars as pl

            frame = pl.read_csv(output)
            if spec.get("sort"):
                frame = frame.sort(spec["sort"], descending=True)
            captured["artifact"] = frame.head(6).to_dicts()
    # Save only the chart/artifact selected for public display, never raw inputs.
    captured.update(
        {
            "schema": 1,
            "data": "real",
            "notebook_sha256": source_hash,
            "captured_at": now,
            "label": label,
            "parameters": spec.get("args", []),
            "api_url": os.environ.get("COOKBOOK_API_URL", "https://crowdcent.com/api")
            if spec.get("needs_api_key")
            else None,
        }
    )
    if notebook_fingerprint(slug) != source_hash:
        raise ValueError(
            f"{slug}: source changed during capture; retry with a stable notebook."
        )
    if len(json.dumps(captured, indent=2).encode()) + 1 > 1_000_000:
        raise ValueError(
            f"{slug}: selected output exceeds 1 MB; choose a smaller artifact."
        )
    return captured


def generate(slug, spec, captured, browser):
    from thumbnail_render import render

    png, through = render(spec, captured, browser)
    validate_png(png)
    receipt = {
        "schema": 1,
        "data": "real",
        "source_sha256": fingerprint(slug),
        "image_sha256": hashlib.sha256(png).hexdigest(),
        "captured_at": captured["captured_at"],
        "data_through": through,
        "label": captured["label"],
    }
    return png, json.dumps(receipt, indent=2) + "\n"


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        worker(sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4]))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--recipe", help="One recipe folder; omit to process every recipe."
    )
    parser.add_argument(
        "--capture",
        action="store_true",
        help="Execute trusted notebooks against real data and replace their saved output snapshots; requires their normal credentials.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check committed previews without keys, network or notebook execution.",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Open the offline gallery after rendering, capture or validation.",
    )
    args = parser.parse_args()
    specs = recipes()
    if args.recipe and args.recipe not in specs:
        parser.error(f"Unknown recipe: {args.recipe}")
    selected = {args.recipe: specs[args.recipe]} if args.recipe else specs
    if args.capture and args.check:
        parser.error("--capture and --check cannot be combined.")
    if args.check:
        check(selected)
    else:
        from playwright.sync_api import sync_playwright

        pending = {}
        snapshots = {}
        with tempfile.TemporaryDirectory() as directory, sync_playwright() as p:
            base = Path(directory)
            cache = base / "downloads"
            cache.mkdir()
            browser = p.chromium.launch()
            try:
                for slug, spec in selected.items():
                    if args.capture:
                        work = base / slug
                        work.mkdir()
                        print(f"Capturing {slug}…", flush=True)
                        snapshots[slug] = capture(slug, spec, work, cache)
                    else:
                        snapshots[slug] = saved_output(slug)
                # No output is published until every selected notebook succeeded.
                for slug, captured in snapshots.items():
                    print(f"Rendering {slug}…", flush=True)
                    pending[slug] = generate(slug, selected[slug], captured, browser)
            finally:
                browser.close()
        # A failed capture leaves every existing asset untouched.
        for slug, (png, receipt) in pending.items():
            target = assets(slug)
            target.mkdir(parents=True, exist_ok=True)
            if args.capture:
                (target / "output.json").write_text(
                    json.dumps(snapshots[slug], indent=2) + "\n"
                )
                # Rendering fingerprint includes the newly saved output bytes.
                receipt = json.loads(receipt)
                receipt["source_sha256"] = fingerprint(slug)
                receipt = json.dumps(receipt, indent=2) + "\n"
            (target / "opengraph.png").write_bytes(png)
            (target / "capture.json").write_text(receipt)
        check(selected)
    from thumbnail_render import gallery

    path = gallery(specs, ROOT)
    print(f"Checked {len(selected)} thumbnail(s). Gallery: {path}")
    if args.preview:
        webbrowser.open(path.as_uri())


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        sys.exit(str(exc))
