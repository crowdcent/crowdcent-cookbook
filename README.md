# CrowdCent Cookbook

Open-source [marimo](https://marimo.io) notebooks for the
[CrowdCent Challenge](https://crowdcent.com) and quantitative finance.

Browse the cookbook:

```bash
uvx marimo run recipes/
```

Open a recipe for editing:

```bash
uvx marimo edit recipes/numerai_dashboard.py
```

Each notebook declares its own dependencies with
[PEP 723](https://peps.python.org/pep-0723/), so there is no shared
environment to assemble first. The same `.py` file runs locally and on
CrowdCent Cloud. Dashboard-style recipes can also declare
`[tool.crowdcent.cloud] default_view = "app"` to open as an app in Cloud while
keeping the editor one toggle away.

## Recipes

- `hyperliquid_ranking.py` trains a ranking model and submits predictions.
- `numerai_dashboard.py` charts public Numerai performance.
- `hello_cloud.py` shows the CrowdCent Cloud runtime and output directory.

## Contributing

Copy a nearby recipe, edit it in marimo, and open a pull request. The short
checklist and metadata format are in [CONTRIBUTING.md](./CONTRIBUTING.md).

## License

[MIT](./LICENSE)
