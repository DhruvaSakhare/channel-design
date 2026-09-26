# Running the channel pipeline on DTU HPC (LSF)

## Do you need Vina?

Only for Stage A steps 3–4. Nothing else imports it — `pipeline.py` launches
`docking.py` as a subprocess, so `--skip-docking` runs the pocket stage with
numpy alone and still writes the `pocket_selection.tsv` that Stage B consumes.
The entire tunnel/channel half of this project runs without Vina.

If you do want docking: it is the **`vina` Python bindings**, not the CLI.
`conda install -c bioconda autodock-vina` gives you an executable and will not
satisfy `from vina import Vina`.

## Setup (once, on a login node)

```bash
# $PROJECT is defined inside config.sh, not in your shell — use the literal path.
cd /work3/s215098/BioBuilders2026/tools/channel_discovery/hpc

# Copying/rsyncing the repo can strip the execute bit. Without this every
# ./script below fails with "Permission denied".
chmod +x *.sh

vim config.sh          # set WORK / INPUTS (PROJECT already points here)
```

**The env already exists.** `CONDA_ENV` defaults to `bio_docking`, the shared
BioBuilders2026 team env at `$TEAM/software/miniforge3/envs/bio_docking`, and it
is already set up — completed runs are in `logs/`. In the normal case you skip
`00_setup_env.sh` entirely and go straight to the smoke test.

> ⚠️ **Do not run `00_setup_env.sh` against `bio_docking`.** If the env exists it
> skips the `conda create` but still runs every `conda install` and
> `pip install` into it — installing `openjdk=8` + `fpocket` and re-pinning
> `numpy<2.0`, `meeko==0.7.1`, `rdkit==2025.9.5`, `scipy==1.16.1` **for the
> whole team**. Only run it to build a *new* env:
>
> ```bash
> CONDA_ENV=my_channel_env ./00_setup_env.sh
> ./submit_all.sh -e my_channel_env ...      # and pass -e on every submit
> ```

`00_setup_env.sh` follows the recipe that already works: conda-forge
`swig`/`boost-cpp`, `numpy<2.0` installed first, `BOOST_INCLUDE`/`BOOST_LIB`
exported before `pip install vina==1.2.7`. It adds `matplotlib` (which
`bio_docking` originally lacked, but the whole caver stage needs), plus
`fpocket` and `openjdk=8`.

**Do not float the meeko version.** `docking.py` calls
`MoleculePreparation.prepare()` then `.write_pdbqt_string()`. That path still
works in 0.7.1 but only through a shim that emits a `DeprecationWarning` and is
slated for removal.

## Smoke test (do this before any array job)

Runs the 3 bundled structures end to end in an **interactive** session. It
catches env and path problems in ~minutes instead of after 300 queued tasks fail
identically. Get a session first — do not run it on a login node:

```bash
bsub -Is -q hpc -W 1:00 -n 4 -R "rusage[mem=4GB]" -R "span[hosts=1]" bash
cd /work3/s215098/BioBuilders2026/tools/channel_discovery/hpc && ./05_smoketest.sh
```

It writes to `$WORK/smoketest/` and wipes that directory on each run, so it
never touches real results. It fails loudly if Stage A produces no
`pocket_selection.tsv` or nothing passes the pocket filter.

## Run on your own folder of structures

Point `submit_all.sh` at the directory. Inputs may be `.pdb` or `.cif` — CIF is
converted for CAVER by `20_collectA.sh`. You do **not** need to stage files into
`$WORK` yourself; each task copies what it needs.

```bash
./submit_all.sh -i /path/to/my_structures -n 10     # test: 10 structures + references
./submit_all.sh -i /path/to/my_structures           # full set
```

Or set `INPUTS` in `config.sh` once and just run `./submit_all.sh`.

Options worth knowing (`--help` lists them all):

| Flag | Effect |
|---|---|
| `-i, --inputs DIR` | structures to process |
| `-w, --work DIR` | where outputs go (defaults to `$WORK`) |
| `-n, --limit N` | first N structures only, isolated in `<work>/testN/` |
| `-t, --tag NAME` | job-name prefix, for running two sets side by side |
| `-e, --env NAME` | conda env |
| `--no-references` | omit the three reference UPOs |
| `-y, --yes` | skip the confirmation prompt |

Before submitting it runs `preflight_inputs.py`, which drops anything the
pipeline would silently `FAIL` on — above all structures with **no heme iron**,
which everything here is anchored to. Predicted structures (AlphaFold, ESMFold,
RFdiffusion/ProteinMPNN output) usually have no cofactor, so this is the check
that stops a whole batch failing quietly. The verdict per structure lands in
`$WORK/preflight_report.tsv`. It needs no env and takes seconds, so it is never
worth skipping — you can also run it standalone:

```bash
python3 preflight_inputs.py /path/to/my_structures --report preflight.tsv
```

Reference structures are appended **after** the limit, so `-n 10` means 10 of
your designs *plus* the references, not 10 total. `--limit` runs also get their
own `<work>/testN` directory so they can never overwrite a full run.

`submit_all.sh` then prints a summary and asks to confirm before submitting.

Results, all under `$WORK`:

```
outputs/pocket_selection.tsv               Stage A: PASS/FAIL, pocket, docking outcome
results/tunnel_selection.csv               Stage B: per-structure tunnel metrics
results/clustering/cluster_assignments.csv Stage B: tunnel-shape cluster per structure
```

## The job chain

`submit_all.sh` submits four LSF jobs chained by dependency:

| Job | Script | Shape |
|---|---|---|
| `<TAG>A0…` | `10_stageA.sh` | array, 1 structure/task — fpocket, filter, dock, poses |
| `<TAG>Ac` | `20_collectA.sh` | single — merge shards into `outputs/`, prune, build CAVER inputs |
| `<TAG>B0…` | `30_stageB.sh` | array, 1 structure/task — CAVER tunnels |
| `<TAG>Bc` | `40_collectB.sh` | single — rebuild table, cluster across all structures |

`<TAG>` is `cd` + `--tag` + (`--limit` or `full`) — so a plain full run is
`cdfullA0`/`cdfullAc`/`cdfullB0`/`cdfullBc`, and `-n 10` gives `cd10A0`, etc.
Unique names per concurrent run matter: two runs sharing a name would each
satisfy the other's `-w` dependencies. Use `--tag` when running sets side by
side.

Arrays are split at LSF's `MAX_JOB_ARRAY_SIZE` (1000), hence the trailing index
— a 2400-structure run submits `<TAG>A0`, `<TAG>A1`, `<TAG>A2`.

The array→collect dependencies use `ended()`, not `done()`: `done()` on an array
requires *every* element to succeed, so one flaky task among hundreds would
leave the collect job pending forever. The collect scripts validate their own
inputs and exit non-zero if there is genuinely nothing to work with. The collect
jobs themselves stay on `done()`, since if a collect fails the next stage must
not run.

Monitor with `bstat` or `bjobs -A`. Logs in `hpc/logs/`, named
`stage{A,B}_<jobid>_<taskindex>.{out,err}` and `collect{A,B}_<jobid>.{out,err}`.

## Why the collect steps exist

Both stages write a combined table that every task would race on:

- `pipeline.py` enumerates **all** structures in `--outputs-dir` and rewrites
  `pocket_selection.tsv` from that view. Tasks sharing one dir clobber each
  other, so each gets its own shard dir and `20_collectA.sh` merges them.
  The merge must put `pocket_selection.tsv` and the `<stem>_out/` dirs in the
  *same* directory — that is what `--fpocket-dir` points at, and `run_batch.py`
  reads `<fpocket_dir>/<stem>_out/pockets/pocket<N>_vert.pqr` from it.
- `run_batch.py` writes `results/tunnel_selection.csv` the same way. Per-structure
  output in `results/<stem>/` is collision-free, so Stage B shares one results
  dir and `40_collectB.sh` rebuilds the combined CSV with `--skip-existing`
  (which recomputes nothing — it only re-emits the rows).

Clustering is a genuine gather step: it compares every structure against every
other, so it cannot be sharded.

## The one code change

`docking.py` now reads `VINA_CPU` / `VINA_SEED`:

```python
v = Vina(sf_name='vina',
         cpu=int(os.environ.get('VINA_CPU', 0)),
         seed=int(os.environ.get('VINA_SEED', 0)))
```

Vina's `cpu=0` default means *every core on the machine*. Under LSF you are
allocated a subset, so the default oversubscribes the node — slow for you,
antisocial for everyone else, and the kind of thing that gets jobs killed.
`10_stageA.sh` sets `VINA_CPU=$LSB_DJOB_NUMPROC`. Unset, behaviour is unchanged,
so this is safe on your laptop.

`VINA_SEED=42` also makes poses reproducible; drop it for independent replicates.

## Tuning

Everything in `config.sh` uses `${VAR:-default}`, so any of it can be overridden
from the environment for a one-off run:

```bash
N_CLUSTERS=5 EXHAUSTIVENESS=32 ./submit_all.sh -i /path/to/my_structures
```

| Setting | Default | Notes |
|---|---|---|
| `TEAM` | `/work3/s215098/BioBuilders2026` | shared team tree — **not** `$USER`-derived |
| `WORK` | `$TEAM/dhruva/channel_discovery_runs` | ~5–15 MB per structure. Files you create count against **your** `/work3` quota even inside the team dir |
| `INPUTS` | a `best_designs` dir | your receptor structures |
| `CONDA_ENV` | `bio_docking` | shared team env |
| `MAXPAR` | 40 | concurrent array elements. Stage A takes 4 cores each, so 40 = 160 cores — check `busers` before raising |
| `N_CLUSTERS` | 8 | keep ≤ 10; `submit_all.sh` scales it down automatically on small runs |
| `EXHAUSTIVENESS` | 8 | Vina's own default, right for a first-pass screen. Re-dock the shortlist at 32 |

- **Walltime** — Stage A is dominated by Vina and scales with
  `EXHAUSTIVENESS`. At the default of 8 the 4 h `#BSUB -W` in `10_stageA.sh` is
  ample; if you raise it to 32, time one structure interactively first and
  extend `-W` with headroom.
- **CAVER memory** — `-Xmx1200m` is hardcoded at `run_batch.py:218`. If large
  receptors OOM, raise that *and* the `rusage[mem]` in `30_stageB.sh` together.
  DTU's esub rejects a `-M` more than 1 GB above `rusage[mem]`, so move both.
- **Rerunning** — both stages skip completed work (`--skip-existing` for CAVER,
  existing-output checks in `pipeline.py`), so resubmitting after a timeout
  resumes rather than restarting. Adding new structures to the input folder only
  costs compute for the new ones.
- **Disk** — `20_collectA.sh` *moves* shards rather than copying (duplication at
  scale would exhaust a quota) and prunes fpocket's visualisation output
  (`.tcl`/`.pml`/VMD/PyMOL scripts, per-pocket `_atm.pdb`). Set
  `PRUNE_FPOCKET=0` to keep them for manual inspection.

## Boltz-2 affinities

`cluster_affinity_violin.py` wants a Boltz-2 summary CSV. That is your
`boltz_vina` env and a **GPU** queue (`gpuv100`/`gpua100` with
`#BSUB -gpu "num=1:mode=exclusive_process"`), not the `hpc` queue these scripts
use. Keep it a separate submission and feed the CSV in afterwards:

```bash
python3 python_scripts/cluster_affinity_violin.py --summary-csv <boltz_summary.csv>
```
