---
name: crowdcent-hillclimb
description: Improve a CrowdCent Hyperliquid Ranking model step by step. Use for "climb the leaderboard", "hill-climb", "improve my model", "tune my model" or "try new features". Tries a few single changes a round, keeps only changes that beat the current model outside the noise, and never submits.
license: MIT
compatibility: Needs crowdcent-challenge==0.2.16 and a CrowdCent API key with Challenge access. Runs as CrowdCent Cloud runs (paid credits) or on a laptop.
metadata:
  label: Hill-climb
---

# Hill-climb a model

Improve the person's model in small rounds, and keep a change only when it is
clearly better than the current model on the same dates.

1. **Start from the live model.** Write it as `incumbent.py` with
   `predict(train, test)`, which returns the 10d and 30d predictions for the
   test rows. If the person has no model, use the hyperliquid_ranking recipe's
   XGBoost.
2. **Ask once.** Say how many rounds (at most 6), how many changes a round (at
   most 4), the machine size and the budget (default $5 of credits). Wait for
   one yes. Spend nothing before it.
3. **Freeze the data.** Download the latest training data once
   (`client.download_training_dataset("latest", ...)`) and use that one file
   for the whole climb.
4. **Run rounds.** Each candidate file changes exactly one thing in the
   incumbent: another model family, separate settings for 10d and 30d, fewer or
   new features, more weight on recent dates. Compare them all in one run of
   `scripts/evaluate.py`, as a Cloud run or on a laptop. Keep a `KEEP`, and
   then it becomes the incumbent. Drop `NOISE`, `WORSE` and `LEAK`. Note each
   round in `climb.md`.
5. **Stop** after 2 rounds in a row with no `KEEP`, after 6 rounds, at the
   budget, or when the person says so.
6. **Check once out of sample.** Run `evaluate.py --out-of-sample=1` with only
   the final incumbent against the starting model. Report that number as the
   honest gain, because the dev gain is the best of many tries.
7. **Report** what you tried, what won and the credits spent. Tell the person
   how to submit the winner themselves.

## Rules that keep it honest

- Train only on dates more than 31 days before the dates you score, because a
  30d target closes 31 days after its date.
- Compare date by date on the same dates. Judge the gain over 30-date blocks,
  not single dates, because daily scores of 30-day targets overlap.
- A model trained on targets shuffled within each date must lose its score.
  If it keeps most of it, the candidate leaks.
- Never tune on the last 180 dates, and score them only once per climb.
- Never submit, change a slot or touch a schedule.
