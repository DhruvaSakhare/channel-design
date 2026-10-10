# Notes for AI assistants

Read **[README.md](README.md)** first — it explains what this repository is for,
how to install/use the tool, and the license.

## Responsible & honest use
@.claude/RESPONSIBLE_AI_USE.md

## Running the pipeline

Before running or submitting anything, use the **`run-pipeline`** skill
(`.claude/skills/run-pipeline/SKILL.md`). It has the order of operations —
cheap checks before expensive runs — what to ask the user before spending
shared GPU time, and the failure modes that look like crashes but are not.

Two things that are true of this repository specifically:

- **Results go on a public wiki and into a competition.** Never report a
  number you did not measure, and never summarise a run as successful just
  because it exited 0.
- **`config.py` is gitignored** — it is the user's working copy of
  `config_template.py`. Do not commit it.
