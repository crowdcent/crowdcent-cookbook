# Contributing

A recipe is one folder under `recipes/` holding a marimo notebook of the same
name, plus any helper modules it imports. Copying the closest recipe is
faster than starting empty.

```bash
cp -r recipes/hello_cloud recipes/my_recipe
mv recipes/my_recipe/hello_cloud.py recipes/my_recipe/my_recipe.py
uv sync
uv run marimo edit --sandbox recipes/my_recipe/my_recipe.py
```

Before opening a pull request:

```bash
uv run marimo check --strict --ignore-scripts recipes
uv sync --locked --group thumbnails
uv run python -m unittest discover -s tests
uv run python scripts/thumbnails.py --check --preview
```

## The notebook

Keep one PEP 723 block at the top with `dependencies` and an OpenGraph
`title` and `description`. A recipe that is mostly a dashboard may open in
Cloud's app view:

```toml
[tool.crowdcent.cloud]
default_view = "app"
```

This is a presentation default only. Nothing a notebook declares about itself
grants credentials or network access.

## Recipe card previews

Every recipe needs a 1200 × 630 PNG generated from a real notebook result.
The small output snapshot, image, and capture receipt are committed together
under `recipes/<name>/__marimo__/assets/<name>/`. The snapshot contains only
the selected chart or small artifact, source/date labels, and input hashes;
raw datasets and credentials stay out of Git.

### Review or change the presentation (no key needed)

```bash
uv sync --locked --group thumbnails
uv run python scripts/thumbnails.py --check --preview
# To render again, after editing thumbnail styles or labels:
uv run playwright install chromium
uv run python scripts/thumbnails.py --preview
# --recipe numerai_dashboard limits either command to one recipe.
```

The gallery is `out/thumbnails/index.html`: open it directly, resize it to
check mobile readability, and click a card to download its PNG. It is one
self-contained HTML file and works offline. Rendering uses the committed
real output snapshots, never the notebook APIs; the browser blocks network
requests. Neither CI nor a contributor reviewing a fork needs an API key.

### Add a recipe or refresh its data

Declare the thumbnail beside the notebook's OpenGraph metadata:

```toml
[tool.crowdcent.thumbnail]
title = "Cumulative payouts"
output = "figure"
figure = "cumulative"
label = "Account · crowdcent"
args = ["--account=crowdcent"]
```

`output` is `figure` (a Plotly chart named by `figure`), a relative `.csv`
table, or a small `.json` artifact under `CROWDCENT_OUT_DIR`. Name the actual
figure variable in the notebook; no thumbnail-only computation is needed.
Optional presentation settings include `badge`, `x_label`, `y_label`,
`y_suffix`, `legend`/`legend_prefix`, and CSV `sort`/`columns`. Keep labels accurate and
readable at card size; preserve plotted values. Set `needs_api_key = true`
for CrowdCent data and `account_label = true` when the chart shows that key
owner's performance.

```bash
# Public Numerai data: no key needed, but this DOES contact the API.
uv run python scripts/thumbnails.py --capture --recipe numerai_dashboard --preview

# CrowdCent recipes: use your normal key from the environment.
# Set COOKBOOK_CAPTURE_ACCOUNT=jrai only when capturing jrai's results.
uv run python scripts/thumbnails.py --capture --recipe track_your_performance --preview
```

`--capture` executes trusted recipe code using its declared PEP 723
requirements. It does real downloads, fitting, and backtesting. CrowdCent
recipes need `CROWDCENT_API_KEY`; account previews also require
`COOKBOOK_CAPTURE_ACCOUNT` with the key owner's public account name. For a
local API, set `COOKBOOK_API_URL`. The capture guard rejects client writes,
including submissions, and does not set the Cloud run ID. This guard is
accidental-write protection, not a sandbox for untrusted notebooks.

Only explicitly selected output becomes public. Review `output.json` as
well as the image before committing, especially for account data. Missing
or empty output and API failures stop capture; there is no synthetic-data
fallback. A failed capture/render leaves existing assets untouched. The
footer records the account/source and latest data date (or capture date
for an artifact with no dates). A date is provenance, not a freshness SLA.

Commit `output.json`, `opengraph.png`, and `capture.json` together. Notebook
computation, helper, parameter, or dependency edits require a new capture.
Presentation or renderer changes can reuse the snapshot and only need a
render. Do not edit hashes or mark fixture data as a real capture.

### What happens on a pull request and on main

The `validate` workflow discovers every recipe, checks its declarations,
real-output snapshot, source hashes, image hash, PNG dimensions and decoding,
then executes recipe tests with isolated API fixtures. It also renders all
snapshots without credentials and uploads a downloadable `thumbnail-gallery`
artifact. The same workflow runs on pull requests, main, and manual dispatch.
Make `validate` a required status check on main so missing/stale thumbnails
block merging. The committed check runs **before** regeneration, so CI
cannot silently repair an incomplete pull request and let it through.

Images reach main in the same merge as their notebooks. Cloud loads the
commit-pinned PNG with its recipe on the next catalog refresh (currently
up to five minutes); no Django deployment or asset-publishing bot is needed.
API keys, repository write permissions, schedules, and generated commits
are unnecessary. Fresh market/account data is captured deliberately and
reviewed in a normal pull request; pushes do not rerun live training.

## Execution checks

CI executes every complete notebook using `marimo export html`, the same
entry point Cloud uses. Tests exercise the real client, model fitting,
plots, unattended defaults, interactive gates, artifact files, empty data,
and failures, with network calls replaced by controlled API responses.
Update those responses when an upstream API changes; fixtures are test
inputs only and must never become recipe fallbacks.

Before release, also check browser previews and a hosted run. Local exports
cannot prove hosted package installation, network policy, credit charging,
artifact delivery, or the next occurrence of a schedule.

## Checklist

- The same cells run in a browser tab, in a Cloud run, and on a laptop. No
  `sys.platform` or import-guard branches.
- In an interactive notebook, a write to CrowdCent waits for a
  `mo.ui.run_button`. A fetch that takes more than a moment waits for a
  `mo.ui.form` submit, so opening a notebook is cheap. Recipes intended for
  unattended execution use `os.environ.get("CROWDCENT_RUN_ID")` to pass
  these UI gates during Cloud runs, including scheduled runs. For example,
  `mo.stop(not os.environ.get("CROWDCENT_RUN_ID") and not submit.value)`.
  Describe automatic submissions in the notebook's introduction.
- Helpers hold the plumbing; the notebook holds the story. If a cell needs a
  comment to explain what it does, move that code into a helper.
- Name a helper for what it does, never like a package. The browser installs
  any import it cannot find from PyPI, so `numerai.py` would be looked up
  there; `numerai_graphql.py` is unmistakably the file beside the notebook.
- A form with complete defaults can run unattended without parameters:
  `answered = dict(mo.cli_args()) or form.value`, then
  `mo.stop(not answered and not os.environ.get("CROWDCENT_RUN_ID"), ...)`
  and `config = {**DEFAULTS, **(answered or {})}`. Use the same `DEFAULTS`
  to initialize the form. Run parameters override those defaults; an
  interactive notebook without arguments waits for the form. A run uses
  defaults saved in the code, not unsaved widget values from a session.
- Use the run ID for Cloud execution context. Cloud runs execute through
  `marimo export html`; in marimo 0.24.1, `mo.running_in_notebook()` is
  still `True` and `mo.app_meta().mode` is `"edit"` during export.
- Live data failures raise. A recipe never renders a sample and calls it a
  report.
- Outputs go under `CROWDCENT_OUT_DIR` when it is set and stay small.
- No keys, tokens, wallet data, or private datasets. Name any external host
  in the pull request; new recipes appear as community recipes with no
  credentials or network access until CrowdCent reviews them.
- Reach the network through a client that honours the proxy environment. A
  Cloud run or session cannot open connections itself, not even DNS: it
  reaches its allowed hosts only through the proxy named in `https_proxy`.
  `requests`, `httpx`, `urllib.request` and `uv` read that variable on their
  own. `urllib3` (`urllib3.request`, `PoolManager`), `aiohttp` without
  `trust_env=True` and `duckdb`'s `httpfs` do not, and fail with a name
  resolution error; see `numerai_dashboard/numerai_graphql.py` for a urllib3
  client that builds its `ProxyManager` from the variable. A browser tab has
  no proxy: it posts through the site's relay, `/cloud/relay/<host>/`, which
  the same helper shows.
