# /// script
# requires-python = ">=3.11"
# dependencies = ["crowdcent-challenge==0.2.16", "numpy", "polars", "pyarrow", "scikit-learn", "xgboost"]
# ///
"""Compare candidate models with the incumbent on walk-forward folds, paired date by date.

    evaluate.py --data=training.parquet --incumbent=incumbent.py --candidates=a.py,b.py [--out-of-sample=1]

A candidate is a file with ``predict(train, test)`` that returns an array of
shape (len(test), 2): the 10d and 30d predictions for ``test``'s rows. The
test frame has no target columns.
"""

import datetime as dt
import importlib.util
import sys

import numpy as np
import polars as pl
from crowdcent_challenge.scoring import spearman_correlation

FOLDS, FOLD_DATES, BLOCK = 4, 180, 30
GAP = dt.timedelta(days=31)
TARGETS = ["target_10d", "target_30d"]


def folds(panel, out_of_sample):
    dates = panel.drop_nulls("target_30d")["date"].unique().sort()
    final = dates[-FOLD_DATES:]
    if out_of_sample:
        return [final]
    dev = dates.filter(dates < final[0] - GAP)[-FOLDS * FOLD_DATES :]
    return [dev[k * FOLD_DATES : (k + 1) * FOLD_DATES] for k in range(FOLDS)]


def daily(predict, panel, fold, shuffle=False):
    """One score a date: the mean of the 10d and 30d Spearman."""
    train = panel.filter(pl.col("date") < fold[0] - GAP).sort("date")
    if shuffle:
        rng = np.random.default_rng(0)
        _, starts = np.unique(train["date"].to_physical().to_numpy(), return_index=True)
        ends = [*starts[1:], train.height]
        order = np.concatenate([rng.permutation(np.arange(a, b)) for a, b in zip(starts, ends)])
        train = train.with_columns(train[t].gather(order) for t in TARGETS)
    test = panel.filter(pl.col("date").is_in(fold.implode())).drop_nulls(TARGETS).sort("date")
    preds = np.asarray(predict(train, test.drop(TARGETS)))
    scores = []
    for _, rows in test.with_row_index("i").group_by("date", maintain_order=True):
        i = rows["i"].to_numpy()
        scores.append(np.mean([spearman_correlation(rows[t].to_numpy(), preds[i, k]) for k, t in enumerate(TARGETS)]))
    return np.array(scores)


def block_t(days):
    """t of the mean over 30-date blocks: daily scores of 30-day targets overlap, so a per-date t calls noise a win."""
    blocks = np.array([b.mean() for d in days for b in np.array_split(d, max(1, len(d) // BLOCK))])
    spread = blocks.std(ddof=1)
    if spread < 1e-12:
        return float(np.sign(blocks.mean()) * np.inf) if blocks.mean() else 0.0
    return blocks.mean() / spread * np.sqrt(len(blocks))


def load(path):
    spec = importlib.util.spec_from_file_location("candidate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.predict


def main():
    args = dict(a.removeprefix("--").split("=", 1) for a in sys.argv[1:])
    panel = pl.read_parquet(args["data"])
    windows = folds(panel, args.get("out-of-sample") == "1")
    base = [daily(load(args["incumbent"]), panel, f) for f in windows]
    print(f"INCUMBENT score={np.mean(np.concatenate(base)):.4f}")
    for path in args["candidates"].split(","):
        predict = load(path)
        days = [daily(predict, panel, f) for f in windows]
        gain = [d - b for d, b in zip(days, base)]
        score = np.mean(np.concatenate(days))
        leak = np.mean(np.concatenate([daily(predict, panel, f, shuffle=True) for f in windows]))
        t = block_t(gain)
        # Fit on targets shuffled within each date, an honest model loses its score. One that keeps most of it has seen the answers.
        verdict = "LEAK" if score > 0.02 and leak > score / 2 else "KEEP" if t >= 2 else "WORSE" if t <= -2 else "NOISE"
        print(f"EVAL name={path} score={score:.4f} gain={np.mean(np.concatenate(gain)):+.4f} block_t={t:.2f} shuffled={leak:.4f} verdict={verdict}")


if __name__ == "__main__":
    main()
