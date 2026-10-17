---
name: run-pipeline
description: Run or verify the channel-design enzyme pipeline on a single GPU or a cluster. Use when asked to run the pipeline, submit a design run, verify the install works here, check that paths and checkpoints resolve, re-run a stage, diagnose a failed or stuck job, or produce channel measurements. Covers the single-GPU path (run_local.py), which is the default, and the LSF path (00_submit_all.py) used for the original campaign.
---

# Running this pipeline

This pipeline spends real GPU time on a shared machine and produces numbers
that go on a public wiki and into a competition. Both facts shape how you
should work: **go cheap before expensive, and never report a number you did
not measure.**

Read `.claude/RESPONSIBLE_AI_USE.md` if you have not. The rule that matters
most here: do not invent results. If a run failed, say it failed.

**Measured results are not in this repository.** They are reported on the
wiki, deliberately in one place only. If you need a number, measure it or read
it out of a run's own CSV — do not reconstruct one from a document.

---

## 1. First, is this machine set up?

Always do this before anything else. It is free and it catches most problems.

```bash
uv run --extra tests pytest -q                      # ~1s, no setup needed
source envs/site.env                                # if it exists; else see §2
python enzyme_design/partial_diffusion/site.py
python enzyme_design/lib/paths.py
```

`pytest` should report **0 failed**; one skip is normal. The pass count grows
as tests are added, so a different total is not a problem — only failures are.

In `site.py`'s output every line should print `[env]` rather than `[default]`,
and every path should exist. If `envs/site.env` does not exist:

```bash
cp envs/site.env.example envs/site.env
```

Fill in the real paths. **Ask the user for them — do not guess a cluster path,
and never copy one from another machine into a file.** Then confirm:

```bash
ls -l "$RFD3_CKPT" "$MPNN_CKPT" "$RF3_CKPT"
```

## 2. Setting up an environment, if it is missing

`./setup.sh` does all of it and needs no conda: it installs `uv` if missing,
syncs every dependency from the committed `uv.lock`, downloads and
checksum-verifies CAVER, and builds fpocket from source.

```bash
./setup.sh --check        # report what is present; installs nothing
./setup.sh                # CPU half: tests + channel measurement
```

**Run `--check` first and read it**, rather than installing on top of a cluster
that already has these. If an environment is already there, use it.

**On a cluster with an existing environment for the design stages, use it.**
Not because the interfaces differ — they do not; the `mpnn`, `rfd3` and `rf3`
commands this pipeline calls are `rc-foundry`'s, verified against the published
wheel — but because the checkpoints are already there and re-downloading them
wastes hours.

Installing fresh: `uv sync --extra design`. Note `rc-foundry` requires Python
3.12 exactly. `uv sync --extra docking` covers pocket detection and docking.

**Four things no Python package manager installs**, because they are not Python
packages. Check for them rather than trying to pip them:

| | how to get it | needed by |
|---|---|---|
| `fpocket` | built from source by `./setup.sh`; works on Linux x86_64, **fails on macOS** (its bundled qhull, upstream issue). On macOS: `conda install -c bioconda fpocket` | the pocket stage only |
| Java | the system JDK; 8 and 17 are both tested | CAVER |
| CAVER 3.0 | `./setup.sh` or `./scripts/fetch_third_party.sh` — downloaded and checksum-verified | all tunnel measurement |
| model weights | `foundry install base-models --checkpoint-dir <dir>` | the design stages |

## 3. See the whole flow before planning a run

`docs/walkthrough-gpu.md` opens with a diagram of the entire path — setup,
verify, prepare, measure the parent, pilot, full run, interpret. Read it first;
it shows where the cheap checks sit relative to the expensive stages, and which
step answers which question.

## 4. The order of operations, cheapest first

Never skip ahead. Each step rules out a class of failure that would otherwise
surface hours into a run.

| # | command | costs | proves |
|---|---|---|---|
| 1 | `pytest -q` | seconds, CPU | the checkout is sound (§1) |
| 2 | `site.py` | nothing | paths and checkpoints resolve (§1) |
| 3 | `run_local.py --check` | nothing | GPU visible, `rfd3`/`mpnn` on PATH, all three checkpoints present |
| 4 | `run_local.py --dry-run` | nothing | the exact commands that would run |
| 5 | `run_local.py --stages prep-caver_filter` | one backbone | RFD3 runs, and the CAVER gate runs on its output. Not end-to-end: MPNN and RF3 are deliberately not reached |
| 6 | `run_local.py` | the full run | the actual experiment |

```bash
python partial_diffusion/scripts/run_local.py --check
python partial_diffusion/scripts/run_local.py --dry-run
python partial_diffusion/scripts/run_local.py --stages prep-caver_filter   # the pilot
python partial_diffusion/scripts/run_local.py                             # all stages
```

`--stages` takes names as well as numbers; names are stable where numbers shift
if a stage is inserted. Stages in order: `prep rfd3 process caver_filter mpnn
rf3 score collect`.

**Stop and report after step 5.** A pilot that produced a backbone *and* a gate
verdict on it is the evidence that setup is correct. Do not proceed to a full
run on your own initiative — see §6.

**On an LSF cluster**, the same ladder is `00_submit_all.py --dry-run`, then
`--pilot`, then the bare command, and it additionally needs two queue names:

```bash
PIPELINE_BASE_CONFIG=partial_diffusion.configs.config_smoketest \
  python partial_diffusion/scripts/00_submit_all.py --pilot
```

Prefer `run_local.py` unless the user asks for the cluster or needs the
parallel RF3 array. Cluster specifics — chaining, monitoring, wall times — are
in `enzyme_design/partial_diffusion/CLUSTER.md`.

The pilot covers the same stages in either driver: `00_submit_all.py --pilot`
and `run_local.py --stages prep-caver_filter` both stop after the gate. If you
find them disagreeing, that is a bug and `tests/test_stage_parity.py` should
have caught it.

## 5. Changing the queue (LSF only)

`site.py` owns queue names, not the configs. Three ways, highest precedence
first:

```bash
00_submit_all.py --queue <gpu-queue> --cpu-queue <cpu-queue>    # this one run
export PIPELINE_QUEUE=<gpu-queue> PIPELINE_CPU_QUEUE=<cpu-queue>    # this shell
# or put both in envs/site.env, which setup.sh reads
```

**There is no default.** `00_submit_all.py` exits 2 without a queue rather than
guessing — a queue name is specific to the cluster, and the old default pointed
at the most contended queue on the cluster this was written for. `--dry-run`
works without one. `run_local.py` never needs one.

**Ask the user for their queue names; do not guess one.** `bqueues` lists what
a cluster has. Any GPU queue works as far as this pipeline knows.

**Do not edit `QUEUE` in a config to change a queue.** The configs no longer
define it, and if you find one that does, that is
`tests/test_no_config_shadows_site.py` failing — report it rather than working
around it. Confirm the queue from `00_submit_all.py`'s own banner (`GPU queue
:`) before the job leaves, and again with `bjobs -l` after.

## 6. Ask the user before

- **Submitting a full run** (step 6). It consumes shared GPU hours. Say what it
  will cost in jobs and roughly how long, and wait.
- **Re-running a stage that already has output.** Check for the output first;
  re-running overwrites or duplicates work.
- **Deleting or overwriting anything under `$PIPELINE_WORK_ROOT`.** Those are
  results somebody may not have copied out yet.
- **Any `git commit` or `git push`.** This repository is a judged artifact, and
  `origin` is the team's shared iGEM GitLab.

## 7. Choosing or writing a config

Shipped examples are in `enzyme_design/partial_diffusion/configs/`. Select one
with `PIPELINE_BASE_CONFIG=partial_diffusion.configs.<name>`. Every setting is
documented in `enzyme_design/partial_diffusion/CONFIGURATION.md`.

For a new enzyme, copy `config_template.py` to `config.py` (gitignored — it is
the user's working copy) and edit only the tagged lines.

**Do not invent a `FLEXIBLE_RESIDUES` list.** It comes from measuring the
parent:

```bash
python partial_diffusion/scripts/00_caver_channel.py <structure.pdb> --substrate UNL
```

That writes the tunnel-lining residues and the baseline bottleneck. Choosing
those residues by eye defeats the point of the pipeline.

Check a new structure before anything else — this names a ligand written as
`ATOM`, which is invisible to every ligand-aware step:

```bash
python partial_diffusion/scripts/00_prep_pdb.py --check
```

## 8. Traps that have each cost somebody a run

Full list with verification commands: `KNOWN_ISSUES.md`. Per-stage error
messages: `enzyme_design/partial_diffusion/TROUBLESHOOTING.md`. The ones that
bite most often:

- **A ligand written as `ATOM` instead of `HETATM` is invisible.** CAVER finds
  zero tunnels and every ligand-aware step misses the substrate. `00_prep_pdb.py
  --check` now names any non-amino-acid residue on an `ATOM` line, so run it on
  a structure you have not used before.
- **Name the substrate on an unfamiliar structure.** Without `--substrate`, the
  code identifies it by elimination, and the keep lists in `staging.py` cover
  what turns up on UPO crystals rather than everything the PDB contains. A
  glycan or a modified amino acid such as `MSE` removed by mistake leaves a hole
  that reads as extra channel width. Every script prints what it stripped —
  read that line.
- **Never compare a holo structure against an apo one.** A bound substrate
  narrows the measured bottleneck by more than the spread between real
  reference structures. `staging.py` enforces this for both entry points; do
  not work around it.
- **CAVER output depends on the input filename.** Structures are staged as
  `structure.pdb` for that reason. Do not rename them to be helpful.
- **`MPNN_TEMPERATURE` below ~0.2 makes every design identical.** If sequences
  look suspiciously similar, check it before concluding the method failed.
- **A residue in both `_CATALYTIC_PINS` and `FLEXIBLE_RESIDUES` gets no pin at
  all** — `_build_fixed_atoms` skips flexible residues, so the pin looks active
  and is dead code. `01_rfd3_partial_submit.py` now exits on this before any
  GPU time, and `tests/test_configs.py` fails if a shipped config has it. If
  you hit either, fix the config rather than bypassing the guard.

## 9. Interpreting what happened

**`signal 9` / `TERM_EXTERNAL_SIGNAL` is not necessarily failure.** The
`caver_filter` and `rf3_prep` jobs report it while having completed their work —
the cleanup loop takes down the shell before `exit 0`. **Check whether the
output files exist before calling it a failure or re-running anything.**

**The CAVER gate fails open on purpose.** If `02b_caver_filter.py` says it did
nothing — no CAVER, no baseline, nothing survived — that is designed behaviour,
not a crash. MPNN then runs on unfiltered backbones. Report it, because the run
is then missing its channel-width gate, but do not treat it as an error to fix
mid-run.

**The gate is loose by design.** It drops backbones more than `--tolerance`
(default 0.05 Å) narrower than the parent, which is "not worse", not "widened".
It is a cheap CPU cut before expensive GPU stages, not the ranking. The ranking
is `07_caver_rescore.py` on the folded designs, and it *ranks* rather than
discards — a design narrower than the parent stays in `best_designs/` and is
marked `widened=no` in the CSV. Fold quality (pLDDT/PAE/ipSAE in
`06_collect_best.py`) is the only thing that actually discards a folded design,
and it says nothing about the channel.

**Where the numbers live.** `diffusion_out/caver_filter.csv` for the backbone
gate, `scores/caver_rescore.csv` for the folded designs, `scores/rf3_metrics.csv`
for fold quality. These are written with CRLF line endings, so strip `\r`
before parsing in a shell (`tr -d '\r' < file | awk ...`).

**Check jobs with `bjobs`**, and read the logs under `$PIPELINE_WORK_ROOT/logs/`
before concluding anything.

## 10. Reporting back

State plainly: which command ran, whether it succeeded, where the output is,
and what the measured numbers are. If you did not measure something, say so.
If a stage was skipped — including the CAVER gate failing open — say that too.

Do not summarise a run as successful because it exited 0. Check that the
expected files exist and that the numbers are there.
