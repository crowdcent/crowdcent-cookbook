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

If a recipe calls an external API, name the host in the pull request. New
recipes appear as community recipes with no credentials or network access.
CrowdCent reviews those permissions separately.

## Recipe checklist

- The notebook passes `marimo check --strict`.
- Dependencies are declared in its PEP 723 block.
- The repository contains no keys, tokens, wallet data, or private datasets.
- A browser-only fallback labels generated data as sample data.
- Live data failures raise an error instead of rendering an empty report.
- Outputs stay small and use `CROWDCENT_OUT_DIR` when present.

Thumbnails are optional. Maintainers can generate them with
`marimo export thumbnail`.
