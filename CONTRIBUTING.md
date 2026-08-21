# Contributing

Add one marimo notebook to `recipes/`. Copying the closest existing recipe is
usually faster than starting with an empty file.

```bash
cp recipes/hello_cloud.py recipes/my_recipe.py
uv sync
uv run marimo edit recipes/my_recipe.py
```

Before opening a pull request:

```bash
uv run marimo check --strict recipes
```

[`marimo check`](https://marimo.io/blog/marimo-check) checks notebook
structure, dataflow, syntax, and formatting.

## Metadata

Keep one PEP 723 block at the top of the notebook. It needs:

- `dependencies`
- an OpenGraph `title` and `description`

Recipes that are primarily dashboards may open in CrowdCent Cloud's app view:

```toml
[tool.crowdcent.cloud]
default_view = "app"
```

Omit the table, or use `"editor"`, for the normal editor-first view. This is
only a presentation default. It cannot grant credentials, network access,
verification, or any other execution permission.

If a recipe calls an external API, name the host in the pull request. New
recipes appear as community recipes with no credentials or network access.
CrowdCent reviews those permissions separately.

## Recipe checklist

- The notebook passes `marimo check --strict`.
- Dependencies are declared in its PEP 723 block.
- The repository contains no keys, tokens, wallet data, or private datasets.
- The same cells run in the browser, in a Cloud run, and on a laptop. No
  `sys.platform` or import-guard branches; a recipe is its tutorial, plainly.
- Live data failures raise an error instead of rendering an empty report.
- Anything that writes to CrowdCent (a submission, an order) sits behind a
  `mo.ui.run_button`. Opening a notebook never submits.
- Outputs stay small and use `CROWDCENT_OUT_DIR` when present.

Thumbnails are optional. Maintainers can generate them with
`marimo export thumbnail`.
