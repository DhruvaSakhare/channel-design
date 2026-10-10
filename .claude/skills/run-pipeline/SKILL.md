---
name: run-pipeline
description: Run or verify the channel-design enzyme pipeline on a cluster or a single GPU. Use when asked to run the pipeline, submit a design run, verify the install works here, check that paths and checkpoints resolve, re-run a stage, diagnose a failed or stuck job, or produce channel measurements. Covers the LSF path (00_submit_all.py) and the single-GPU path (run_local.py).
---

# Running this pipeline

This pipeline spends real GPU time on a shared machine and produces numbers
that go on a public wiki and into a competition. Both facts shape how you
should work: **go cheap before expensive, and never report a number you did
not measure.**

Read `.claude/RESPONSIBLE_AI_USE.md` if you have not. The rule that matters
most here: do not invent results. If a run failed, say it failed.

## Before anything else: is this machine set up?

Do this first, always. It is free and it catches most problems.

```bash
source envs/site.env            # if it exists; else see step 2 below
python enzyme_design/partial_diffusion/site.py
python enzyme_design/lib/paths.py
```

Every line should print `[env]` rather than `[default]`, and every path should
exist. If `site.env` does not exist yet:

```bash
cp envs/dtu-hpc.env.example envs/site.env
```

and fill in the real paths. **Ask the user for them — do not guess a cluster
path, and never write one from another machine into a file.** Then verify:

```bash
ls -l "$RFD3_CKPT" "$MPNN_CKPT" "$RF3_CKPT"
```

## The order of operations, cheapest first

Never skip ahead. Each step rules out a class of failure that would otherwise
surface hours into a run.

| # | command | costs | proves |
|---|---|---|---|
| 1 | `pytest -q` | seconds, CPU | the checkout is sound (expect ~146 passed) |
| 2 | `python enzyme_design/partial_diffusion/site.py` | nothing | paths and checkpoints resolve |
| 3 | `run_local.py --check` | nothing | GPU visible, `rfd3`/`mpnn` on PATH, all three checkpoints present |
| 4 | `00_submit_all.py --dry-run` | nothing | the exact commands that would run |
| 5 | `00_submit_all.py --pilot` | one backbone | the pipeline works end to end here |
| 6 | `00_submit_all.py` | the full run | the actual experiment |

**Stop and report after step 5.** A pilot that produced a backbone is the
evidence that setup is correct. Do not proceed to a full run on your own
initiative — see below.

## Ask the user before

- **Submitting a full run** (step 6). It consumes shared GPU hours. Say what it
  will cost in jobs and roughly how long, and wait.
- **Re-running a stage that already has output.** Check for the output first;
  re-running overwrites or duplicates work.
- **Deleting or overwriting anything under `$PIPELINE_WORK_ROOT`.** Those are
  results somebody may not have copied out yet.
- **Any `git commit` or `git push`.** This repository is a judged artifact.

## Interpreting what happened

**`signal 9` / `TERM_EXTERNAL_SIGNAL` is not necessarily failure.** The
`caver_filter` and `rf3_prep` jobs report it while having completed their work —
the cleanup loop takes down the shell before `exit 0`. **Check whether the
output files exist before calling it a failure or re-running anything.**

**The CAVER gate fails open on purpose.** If `02b_caver_filter.py` says it did
nothing — no CAVER, no baseline, nothing survived — that is designed behaviour,
not a crash. MPNN then runs on unfiltered backbones. Report it, because the run
is then missing its channel-width gate, but do not treat it as an error to fix
mid-run.

**Check jobs with `bjobs`**, and read the logs under `$PIPELINE_WORK_ROOT/logs/`
before concluding anything.

## Running it

**On a cluster (LSF):**

```bash
PIPELINE_BASE_CONFIG=partial_diffusion.configs.config_smoketest \
  python partial_diffusion/scripts/00_submit_all.py --pilot
```

**On one GPU, no scheduler:**

```bash
python partial_diffusion/scripts/run_local.py --check
python partial_diffusion/scripts/run_local.py --stages prep-caver_filter   # pilot-ish
python partial_diffusion/scripts/run_local.py                             # all stages
```

`--stages` accepts names as well as numbers; names are stable, numbers shift if
a stage is inserted. Stages in order: `prep rfd3 process caver_filter mpnn rf3
score collect`.

## Choosing or writing a config

Shipped examples are in `enzyme_design/partial_diffusion/configs/`. Select one
with `PIPELINE_BASE_CONFIG=partial_diffusion.configs.<name>`.

For a new enzyme, copy `config_template.py` to `config.py` (gitignored — it is
the user's working copy) and edit only the tagged lines. **Do not invent a
`FLEXIBLE_RESIDUES` list.** It comes from measuring the parent:

```bash
python partial_diffusion/scripts/00_caver_channel.py <structure.pdb>
```

That writes the tunnel-lining residues and the baseline bottleneck. Choosing
those residues by eye defeats the point of the pipeline.

## Traps that have each cost somebody a run

Full list with verification commands: `KNOWN_ISSUES.md`. The ones that bite
most often:

- **A ligand written as `ATOM` instead of `HETATM` is invisible.** CAVER finds
  zero tunnels and every ligand-aware step misses the substrate. Check with
  `grep " UNL " file.pdb | cut -c1-6 | sort -u` before blaming anything else.
- **Never compare a holo structure against an apo one.** A bound substrate
  costs ~0.45 Å of bottleneck radius, against a 0.077 Å spread between real
  reference structures. `lib/caver_utils.py` enforces this; do not work around
  it.
- **CAVER output depends on the input filename.** Structures are staged as
  `structure.pdb` for that reason. Do not rename them to be helpful.
- **`MPNN_TEMPERATURE` below ~0.2 makes every design identical.** If sequences
  look suspiciously similar, check it before concluding the method failed.
- **A residue in both `_CATALYTIC_PINS` and `FLEXIBLE_RESIDUES` gets no pin
  at all.** The pin looks active and is dead code.

## Reporting back

State plainly: which command ran, whether it succeeded, where the output is,
and what the measured numbers are. If you did not measure something, say so.
If a stage was skipped — including the CAVER gate failing open — say that too.

Do not summarise a run as successful because it exited 0. Check that the
expected files exist and that the numbers are there.
