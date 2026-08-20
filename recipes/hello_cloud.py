# /// script
# dependencies = ["marimo"]
#
# [tool.marimo.opengraph]
# title = "Hello, Cloud"
# description = "See the CrowdCent Cloud runtime from inside a notebook and write your first output file."
# ///

import marimo

__generated_with = "0.23.15"
app = marimo.App()


@app.cell
def _():
    """Hello, CrowdCent Cloud.

    Prints what the runtime provides, then writes a file.
    """
    return


@app.cell
def _():
    import json
    import os
    import pathlib
    return


@app.cell
def _():
    print("=== data and outputs ===")
    for path in (
        os.environ.get("CROWDCENT_DATA_DIR", "/data"),
        os.environ.get("CROWDCENT_OUT_DIR", "./out"),
    ):
        print(f"  {path:14} {'yes' if pathlib.Path(path).exists() else 'no'}")
    return


@app.cell
def _():
    runtime = "CrowdCent Cloud" if os.environ.get("CROWDCENT_RUN_ID") else "local"
    print(f"\n=== runtime ===\n  {runtime}")
    return


@app.cell
def _():
    if os.environ.get("CROWDCENT_RUN_ID"):
        print("\nNetwork access is limited to the hosts declared by this recipe.")
    else:
        print("\nRunning locally; CrowdCent's network policy is not active.")
    return


@app.cell
def _():
    out = pathlib.Path(os.environ.get("CROWDCENT_OUT_DIR", "./out"))
    out.mkdir(parents=True, exist_ok=True)
    (out / "hello.json").write_text(
        json.dumps(
            {
                "greeting": "hello from CrowdCent",
                "run": os.environ.get("CROWDCENT_RUN_ID"),
            },
            indent=2,
        )
    )
    print(f"\nwrote {out / 'hello.json'}")
    return


if __name__ == "__main__":
    app.run()
