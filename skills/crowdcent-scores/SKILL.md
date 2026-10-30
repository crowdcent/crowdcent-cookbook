---
name: crowdcent-scores
description: Read and explain a member's live CrowdCent Hyperliquid Ranking scores. Use for "read my scores", "how am I doing", "why did my score drop" or "compare with the meta-model". Counts how much evidence the scores hold and names at most three things to try. Read-only.
license: MIT
compatibility: Needs crowdcent-challenge==0.2.16 and a CrowdCent API key with Challenge access. Runs in a CrowdCent Cloud notebook or on a laptop.
metadata:
  label: Scores
---

# Read live scores

1. **Read the record** with the client: `list_submissions()` for the scores
   and `list_inference_data()` for the meta-model's score on the same dates.
   Use evaluated submissions only. Say how many are still pending.
2. **Count the evidence.** Daily scores of a 30-day target overlap, so about 30
   scored dates make one independent 30d result, and about 10 make one 10d
   result. Call nothing a trend before 3 independent results. Before that, say
   it is too early to tell and when it will not be.
3. **Compare with the meta-model** on the same dates. Average the difference
   over blocks of 10 dates (10d) or 30 dates (30d). Call it real only when it
   is about two standard errors from zero.
4. **Answer in one sentence first,** then a short table per slot: scored
   dates, independent results, mean Spearman per horizon, the gap to the
   meta-model, and the latest percentile.
5. **Name at most three things to try,** and offer the crowdcent-hillclimb
   skill when one is worth a climb.

Never rank slots on fewer than 3 independent results, and never change
anything. This skill only reads.
