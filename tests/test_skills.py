"""Check every skill's frontmatter and script header, and run the hill-climb script on a small panel."""

import datetime as dt
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
SKILLS = sorted(p.parent for p in (ROOT / "skills").glob("*/SKILL.md"))
PEP_723 = re.compile(r"^# /// script$\n(?P<body>(^#(| .*)$\n)+)^# ///$", re.MULTILINE)
CLIENT = "crowdcent-challenge==0.2.16"

HONEST = """
import numpy as np
from sklearn.linear_model import Ridge

def predict(train, test):
    features = [c for c in train.columns if c.startswith("feature_")]
    X = train.select(features).to_numpy()
    out = [Ridge().fit(X, train[t].to_numpy()).predict(test.select(features).to_numpy()) for t in ("target_10d", "target_30d")]
    return np.column_stack(out)
"""

LEAKY = """
import polars as pl

def predict(train, test):
    answers = pl.read_parquet({data!r}).select("id", "date", "target_10d", "target_30d")
    return test.select("id", "date").join(answers, on=["id", "date"], how="left").select("target_10d", "target_30d").to_numpy()
"""


def frontmatter(path):
    text = path.read_text()
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, f"{path} has no frontmatter"
    fields = dict(line.split(":", 1) for line in match.group(1).splitlines() if ":" in line)
    return {k.strip(): v.strip() for k, v in fields.items()}, text[match.end() :]


def panel(path, dates=1150, ids=80):
    rng = np.random.default_rng(0)
    n = dates * ids
    f0 = rng.normal(size=n)
    frame = pl.DataFrame(
        {
            "id": [f"A{i}" for _ in range(dates) for i in range(ids)],
            "date": [dt.date(2021, 1, 1) + dt.timedelta(days=d) for d in range(dates) for _ in range(ids)],
            "feature_0": f0,
            **{f"feature_{k}": rng.normal(size=n) for k in range(1, 20)},
            "target_10d": 0.3 * f0 + rng.normal(size=n),
            "target_30d": 0.3 * f0 + rng.normal(size=n),
        }
    )
    frame.write_parquet(path)


class SkillTests(unittest.TestCase):
    def test_every_skill_has_valid_frontmatter(self):
        self.assertEqual([p.name for p in SKILLS], ["crowdcent-hillclimb", "crowdcent-scores"])
        for skill in SKILLS:
            with self.subTest(skill=skill.name):
                fields, body = frontmatter(skill / "SKILL.md")
                self.assertEqual(fields["name"], skill.name)
                self.assertLessEqual(len(fields["description"]), 1024)
                self.assertEqual(fields["license"], "MIT")
                self.assertIn(CLIENT, fields["compatibility"])
                self.assertTrue(fields.get("label"))
                for word in ("tournament", "holdout", "—", ";", "!"):
                    self.assertNotIn(word, body.lower())

    def test_every_script_pins_the_released_client(self):
        for script in sorted((ROOT / "skills").glob("*/scripts/*.py")):
            with self.subTest(script=script.name):
                body = "\n".join(line[2:] for line in PEP_723.search(script.read_text())["body"].splitlines())
                self.assertIn(CLIENT, tomllib.loads(body)["dependencies"])

    def test_evaluate_calls_the_same_model_noise_and_catches_a_leak(self):
        work = Path(self.enterContext(tempfile.TemporaryDirectory()))
        data = work / "training.parquet"
        panel(data)
        (work / "incumbent.py").write_text(HONEST)
        (work / "again.py").write_text(HONEST)
        (work / "leaky.py").write_text(LEAKY.format(data=str(data)))
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "skills/crowdcent-hillclimb/scripts/evaluate.py"),
                f"--data={data}",
                f"--incumbent={work / 'incumbent.py'}",
                f"--candidates={work / 'again.py'},{work / 'leaky.py'}",
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = [line for line in result.stdout.splitlines() if line.startswith("EVAL ")]
        self.assertIn("verdict=NOISE", lines[0])
        self.assertIn("verdict=LEAK", lines[1])
