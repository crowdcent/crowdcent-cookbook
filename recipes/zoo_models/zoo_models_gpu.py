# /// script
# dependencies = [
#     "crowdcent-challenge>=0.2.16",
#     "jax[cuda12]",
#     "marimo",
#     "numpy",
#     "polars",
#     "pyarrow",
# ]
# ///
"""Run zoo_models.py on a GPU machine, for the families that train with JAX.

zoo_models.py declares no CUDA framework, so it still opens in a Browser tab.
This script adds JAX with CUDA and runs the same notebook, so a GPU family
gets the same folds, scores and manifest as every other zoo model:

    family=lstm version=1
"""

from zoo_models import app

if __name__ == "__main__":
    app.run()
