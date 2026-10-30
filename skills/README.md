# Skills

A skill is a short instruction file that an AI agent follows from top to
bottom: Centaur in CrowdCent Cloud, or Claude Code, Cursor and Codex on a
laptop. Each skill is one folder in the [agentskills.io](https://agentskills.io)
`SKILL.md` format.

```
skills/<name>/
  SKILL.md         the instructions, with frontmatter
  scripts/*.py     optional PEP 723 scripts the instructions run
```

`SKILL.md` starts with this frontmatter:

```yaml
---
name: crowdcent-<name>          # the folder name
description: What it does and the phrases a person uses for it, in 1,024 characters or fewer.
license: MIT
compatibility: The released packages and keys it needs, and where it runs.
metadata:
  label: Short label        # what the chat shows
---
```

To add a skill:

1. Copy the closest folder, for example `skills/crowdcent-scores`.
2. Write short steps an agent can follow in order. Describe the method and let
   the agent write the code. Add a small script only for a part an agent would
   easily get wrong. Say where each step runs in CrowdCent Cloud and on a
   laptop.
3. Pin released packages only, such as `crowdcent-challenge==0.2.16`, in each
   script's PEP 723 block.
4. Say in the skill which steps cost credits and which change anything. A
   skill asks the person before it spends credits, and never submits on its own.
5. Run `uv run python -m unittest discover -s tests`. The tests check the
   frontmatter and the script headers.
