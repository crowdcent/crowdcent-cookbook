# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "marimo",
# ]
#
# [tool.marimo.opengraph]
# title = "Hello, Cloud"
# description = "Tell a Cloud run from a tab, and leave a file behind for the run report."
# ///

import marimo

__generated_with = "0.24.1"
app = marimo.App()


@app.cell
def _():
    import json
    import os
    import pathlib

    import marimo as mo

    return json, mo, os, pathlib


@app.cell
def _(mo):
    mo.md("""
    # Hello, Cloud

    One notebook, three places to run it: this tab, a Cloud machine, or your
    own laptop. A Cloud run names itself in the environment and gives the
    notebook an output directory. Files written there come back with the run.

    Press **Run** to execute this notebook on a Cloud machine, then open the
    run and look for `hello.json`.
    """)
    return


@app.cell
def _(mo, os):
    run_id = os.environ.get("CROWDCENT_RUN_ID")
    mo.md(f"This is Cloud run `{run_id}`." if run_id else "This is not a Cloud run.")
    return (run_id,)


@app.cell
def _(json, os, pathlib, run_id):
    out = pathlib.Path(os.environ.get("CROWDCENT_OUT_DIR", "out"))
    out.mkdir(exist_ok=True)
    (out / "hello.json").write_text(json.dumps({"greeting": "hello", "run": run_id}))
    print(f"wrote {out / 'hello.json'}")
    return


if __name__ == "__main__":
    app.run()
