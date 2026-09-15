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

## Checklist

- The same cells run in a browser tab, in a Cloud run, and on a laptop. No
  `sys.platform` or import-guard branches.
- A write to CrowdCent (a submission, an order) waits for a
  `mo.ui.run_button`. A fetch that takes more than a moment waits for a
  `mo.ui.form` submit, so opening a notebook is cheap.
- Helpers hold the plumbing; the notebook holds the story. If a cell needs a
  comment to explain what it does, move that code into a helper.
- A form a Cloud run should answer reads its arguments first:
  `answered = dict(mo.cli_args()) or form.value`, then
  `mo.stop(not answered, ...)`. A run told `trials=100` goes straight
  through; a browser tab has no arguments and waits for the form.
- Live data failures raise. A recipe never renders a sample and calls it a
  report.
- Outputs go under `CROWDCENT_OUT_DIR` when it is set and stay small.
- No keys, tokens, wallet data, or private datasets. Name any external host
  in the pull request; new recipes appear as community recipes with no
  credentials or network access until CrowdCent reviews them.
