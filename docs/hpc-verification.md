# Verifying this on the HPC

Everything in this repository has been checked on a laptop. Two things have
**not**, and cannot be:

1. The de-machined configuration has never launched a real LSF job. Paths now
   resolve from `site.py` and the environment instead of being hardcoded, and
   "imports cleanly" is not "submits a working job".
2. There is no full dependency lock for the two GPU environments, because a
   real lock has to come from a machine where the environment works.

This document is the procedure for closing both. Work top to bottom; each step
is cheap and the expensive one is last.

---

## 0. Get the code onto the cluster

```bash
ssh <you>@login.hpc.dtu.dk
cd "$SCRATCH"              # your own scratch space
git clone <gitlab url> channel-design
cd channel-design
```

## 1. Tests (2 minutes, login node, no GPU)

```bash
module load python3                 # or activate any python >= 3.10
pip install --user -r envs/requirements-tests.txt
python3 -m pytest tests/ -q
```

**Expect:** `119 passed, 1 skipped`.

If `test_no_machine_paths.py` fails here, something machine-specific came back
in during the transfer — read what it names before going further.

## 2. Point at the cluster's installs

```bash
cp envs/dtu-hpc.env.example envs/site.env
```

Edit `envs/site.env` and replace every `<...>`. The values the original runs
used were:

| variable | value |
|---|---|
| `CONDA_SH` | your conda's `etc/profile.d/conda.sh` |
| `PROTEIN_ENV` | the `protein-design` env path |
| `RFD3_CKPT` | `<foundry>/ckpt/rfd3_latest.ckpt` |
| `MPNN_CKPT` | `<foundry>/ckpt/ligandmpnn_v_32_010_25.pt` |
| `RF3_RELEASE` | the RF3 release tree |
| `RF3_CKPT` | `$RF3_RELEASE/ckpt/rf3_latest.pt` |
| `PIPELINE_WORK_ROOT` | your own scratch, **not** a shared team dir |

Then:

```bash
source envs/site.env
python3 enzyme_design/partial_diffusion/site.py
python3 enzyme_design/lib/paths.py
```

**Expect:** every line tagged `[env]` rather than `[default]`, and every path
one that exists. This is the single most likely thing to be wrong, and it costs
nothing to check.

```bash
ls -l "$RFD3_CKPT" "$MPNN_CKPT" "$RF3_CKPT"
```

## 3. Dry run (no jobs submitted)

```bash
cd enzyme_design
PIPELINE_BASE_CONFIG=partial_diffusion.configs.config_smoketest \
  python3 partial_diffusion/scripts/00_submit_all.py --dry-run
```

**Expect:** the full list of commands the pipeline would submit, with real
checkpoint paths and your scratch directory. Read them. Nothing runs.

## 4. Pilot run (one backbone, RFD3 only — the real test)

```bash
PIPELINE_BASE_CONFIG=partial_diffusion.configs.config_smoketest \
  python3 partial_diffusion/scripts/00_submit_all.py --pilot
bjobs
```

**Expect:** jobs submitted, and output under `$PIPELINE_WORK_ROOT/example/`.

> Remember that `caver_filter` and `rf3_prep` can report `signal 9` /
> `TERM_EXTERNAL_SIGNAL` while having completed successfully — check whether
> the output files exist before concluding it failed.
> See [KNOWN_ISSUES.md](../KNOWN_ISSUES.md#5-some-failed-jobs-actually-succeeded).

**If this works, the de-machining is verified.** That is the thing worth
knowing.

## 5. Channel pipeline end to end (CPU only)

```bash
cd ..
conda activate bio_docking        # or: conda env create -f envs/docking.yml
./scripts/fetch_third_party.sh    # unpack CAVER into third_party/caver
./scripts/smoke_test.sh
```

**Expect:** `TIER 1 AND TIER 2 PASSED`. If it says `TIER 2 SKIPPED`, it is
telling you which of fpocket / Java / CAVER it could not find.

## 6. Generate the real lockfiles

Only once the environments above actually work — a lock from a broken env is
worse than none.

```bash
conda activate bio_docking
pip freeze > envs/requirements-docking.lock.txt
conda list --explicit > envs/docking.conda-explicit.txt

conda activate channel-design-boltz
pip freeze > envs/requirements-boltz.lock.txt
```

Add a header line to each recording the platform and date, e.g.
`# linux-64, CUDA 12.8, generated 2026-10-01`, then commit:

```bash
git add envs/*.lock.txt envs/docking.conda-explicit.txt
git commit -m "Add verified dependency locks generated on DTU HPC"
git push
```

Once these exist, update the README's dependency table: the two GPU
environments are then fully locked rather than direct-pinned.

---

## What to report back

| step | result |
|---|---|
| 1. tests | `119 passed`? |
| 2. site.py | all `[env]`, all paths exist? |
| 3. dry run | commands look right? |
| 4. pilot | jobs ran, output written? |
| 5. smoke test | Tier 2 passed? |
| 6. locks | committed? |

If any step fails, the error text plus which step it was is enough to fix it.
