# Channel discovery pipeline

Two-stage structural screening for heme peroxygenases (UPOs). Given a folder of
receptor structures, it (1) finds the heme-proximal active-site pocket and docks
a substrate into it, then (2) maps the substrate-access tunnels leading to that
pocket and compares their shape across structures.

The two stages live in their own folders and run **in order** — the tunnel stage
consumes the pocket stage's output:

```
channel_discovery/
├── fpocket_pipeline/   # STAGE A — pocket detection + docking
├── caver_pipeline/     # STAGE B — tunnel detection + clustering (needs Stage A output)
└── tools/              # preflight_inputs.py, check_cif_parse.py — screen inputs first
```

Each stage has its own detailed README:
[`fpocket_pipeline/README.md`](fpocket_pipeline/README.md) and
[`caver_pipeline/README.md`](caver_pipeline/README.md). This document is the
top-level map: what to run, in what order, and why. Nothing here needs a
scheduler; every command runs on a laptop or a single machine.

---

## Running on your own folder of structures

```bash
# Steps 1-2 run from the repository root.
# 1. Environment, once (see Requirements below).
./scripts/setup_docking_env.sh && conda activate channel_discovery
./scripts/fetch_third_party.sh                       # CAVER 3.0

# 2. Screen your inputs. A structure with no heme iron fails silently later.
python3 channel_discovery/tools/preflight_inputs.py /path/to/my_structures \
    --report preflight.tsv

# 3. Stage A, then Stage B -- the commands are under "Running the stages by hand".
```

Your structures can be `.pdb` or `.cif`. Stage A converts what it needs;
Stage B reads `.pdb` only, so convert CIFs first with
`caver_pipeline/python_scripts/cif_to_pdb.py`.

Key outputs, all relative to `channel_discovery/`:

| File | What it is |
|---|---|
| `fpocket_pipeline/outputs/pocket_selection.tsv` | per-structure PASS/FAIL + selected pocket + docking outcome |
| `caver_pipeline/results/tunnel_selection.csv` | per-structure tunnel metrics |
| `caver_pipeline/results/clustering/cluster_assignments.csv` | tunnel-shape cluster per structure |
| `preflight.tsv` (from step 2) | why any input was dropped |

---

## Why the order matters

`fpocket_pipeline` writes `outputs/pocket_selection.tsv` — a table listing, for
every structure, whether its active-site pocket passed quality checks (`PASS`/`FAIL`)
and which pocket number was selected. `caver_pipeline` reads that file via its
`--fpocket-dir` flag and:

- **skips** any structure that `FAIL`ed the pocket check (no tunnel analysis), and
- **filters** each structure's tunnels by proximity to the selected pocket.

So always run Stage A first, then point Stage B at its `outputs/` folder.
`--fpocket-dir` also expects the `<stem>_out/` directories to sit *in that same
directory* as the TSV — Stage B reads
`<fpocket-dir>/<stem>_out/pockets/pocket<N>_vert.pqr` to locate each pocket.

**Everything is anchored on the heme iron.** A structure with no heme Fe is
recorded `FAIL ("no heme")` and then skipped by the entire tunnel stage. Bare
predicted structures (AlphaFold, ESMFold, RFdiffusion/ProteinMPNN output)
usually have no cofactor, so a whole batch can fail without erroring.
`tools/preflight_inputs.py` catches this in seconds, before any compute is spent:

```bash
python3 tools/preflight_inputs.py /path/to/my_structures --report preflight.tsv
```

---

## Requirements

| Tool | Used by | Notes |
|------|---------|-------|
| Python ≥ 3.8 with `numpy`, `scipy`, `matplotlib` | both stages | pocket filtering, tunnel filtering, all plots |
| `rdkit`, `vina`, `meeko` | Stage A docking only | the `vina` **Python bindings**, not the CLI |
| `fpocket` | Stage A | `conda install -c bioconda fpocket` (Linux + macOS) |
| Java ≥ 1.8 | Stage B | runs CAVER. Built against Java 8; tested on 8 and 17 |
| CAVER 3.0 | Stage B | GPLv3, **not** redistributed here — `scripts/fetch_third_party.sh`, or set `$CAVER_HOME` |

Create the environment once:

```bash
./scripts/setup_docking_env.sh        # builds a conda env named channel_discovery
```

or by hand:

```bash
conda create -n channel_discovery -c conda-forge -c bioconda \
    python=3.12 fpocket openjdk=8 "numpy<2.0" scipy matplotlib
conda activate channel_discovery
```

Add the docking stack only if you need Stage A steps 3–4 — see
[`scripts/setup_docking_env.sh`](../scripts/setup_docking_env.sh) for the exact working recipe
(`swig`/`boost-cpp`, `numpy<2.0` first, `BOOST_INCLUDE`/`BOOST_LIB` exported
before `pip install vina==1.2.7`, `meeko==0.7.1` pinned).

> **Docking is optional.** Nothing outside Stage A steps 3–4 imports Vina.
> `--skip-docking` runs the pocket stage on numpy alone and still writes the
> `pocket_selection.tsv` that Stage B needs, so the entire tunnel half of this
> project runs without it.

> **fpocket and CAVER are not bundled.** Neither is redistributed with this
> repository: fpocket is platform-specific and a committed binary would not be
> reproducible, and CAVER 3.0 is GPLv3. Install fpocket from bioconda and run
> `scripts/fetch_third_party.sh` for CAVER, or point `$CAVER_HOME` at a copy
> you already have.

---

## Running the stages by hand

For a laptop run, or to re-run one piece. Run from `channel_discovery/`. Put
your receptor `.pdb`/`.cif` files in `fpocket_pipeline/inputs/`; three test
structures (`5FUJ_heme`, `5OXU_heme`, `9HE9_heme`) are already included there
and in `caver_pipeline/input_files/`.

```bash
# ── STAGE A — pockets + docking ──────────────────────────────────────────────
cd fpocket_pipeline
python3 pipeline.py inputs/ -l ligands/NNBT.sdf --prepare
#   → writes outputs/pocket_selection.tsv and docking_out/*.pdbqt
cd ..

# ── STAGE B — tunnels + clustering ───────────────────────────────────────────
cd caver_pipeline
# CAVER reads *.pdb from input_files/ — copy your receptors there if they are
# not already present (the three test structures are).
cp ../fpocket_pipeline/inputs/*.pdb input_files/

python3 python_scripts/run_batch.py --fpocket-dir ../fpocket_pipeline/outputs
#   → runs CAVER on every PASS structure, writes results/tunnel_selection.csv

python3 python_scripts/cluster_tunnels.py --fpocket-dir ../fpocket_pipeline/outputs
#   → clusters tunnel shapes, writes results/clustering/cluster_assignments.csv
```

That is the full path from raw structures to clustered substrate-access channels.

---

## Stage A — pocket detection and docking (`fpocket_pipeline`)

Orchestrated by `pipeline.py`, which runs five steps in sequence:

0. **prepare** (`--prepare`) — convert each `.pdb`/`.cif` receptor to `.pdbqt`.
   Only structures with a matching `.pdbqt` reach docking.
1. **fpocket** — detect pockets in every structure.
2. **filter** — for each structure, select the first pocket that is both
   heme-proximal and passes the metric thresholds.
3. **dock** — targeted AutoDock Vina docking into the selected pocket, with the
   box auto-derived from the pocket's alpha spheres and clipped to the heme Fe.
4. **analyze** — check each pose's orientation relative to the heme iron.

```bash
cd fpocket_pipeline
python3 pipeline.py inputs/ -l ligands/NNBT.sdf --prepare
```

Useful variants:

```bash
# Only detect + filter pockets, no docking (no vina/rdkit/meeko needed)
python3 pipeline.py inputs/ --skip-docking

# Re-run without redoing fpocket (outputs/ already populated)
python3 pipeline.py inputs/ -l ligands/NNBT.sdf --skip-fpocket

# Write somewhere other than the defaults
python3 pipeline.py /path/to/structures -l ligands/NNBT.sdf --prepare \
    --outputs-dir /path/to/outputs --docking-out /path/to/docking_out
```

`pipeline.py` re-enumerates **every** structure in `--outputs-dir` and rewrites
`pocket_selection.tsv` from that view. Two concurrent runs sharing one outputs
dir will clobber each other's table. If you split a large set across parallel
runs, give each its own `--outputs-dir` and merge the tables afterwards.

Re-runs are cheap: existing `.pdbqt` files and existing docking outputs are
detected and skipped.

**Key output:** `outputs/pocket_selection.tsv` — the PASS/FAIL + selected-pocket
table that Stage B depends on. See
[`fpocket_pipeline/README.md`](fpocket_pipeline/README.md) for every stage flag,
the filter thresholds, and the results-table column reference.

---

## Stage B — tunnel detection and analysis (`caver_pipeline`)

Run after Stage A. Point every command at the Stage A outputs with
`--fpocket-dir`.

**1. Detect and filter tunnels** — runs CAVER on each PASS structure, injects the
heme Fe as the tunnel starting point, and keeps only tunnels close to the
selected pocket:

```bash
cd caver_pipeline
python3 python_scripts/run_batch.py --fpocket-dir ../fpocket_pipeline/outputs
#   → results/<stem>/ and results/tunnel_selection.csv
```

`run_batch.py` globs `*.pdb` from `input_files/` only — it does **not** read
CIF. Convert first with `python_scripts/cif_to_pdb.py`. Add `--skip-existing` to make re-runs incremental,
so adding new structures only costs CAVER time for the new ones.

`--fpocket-dir` is optional: without it, every structure in `input_files/` is
processed with no PASS/FAIL skipping and no pocket-proximity filtering. Useful
for a quick standalone tunnel look, but not the intended screen.

**2. Cluster tunnel shapes across structures** — groups structures by the shape
profile of their best tunnel:

```bash
python3 python_scripts/cluster_tunnels.py --fpocket-dir ../fpocket_pipeline/outputs
#   → results/clustering/cluster_assignments.csv (+ dendrograms and overlays)
```

Set `--n-clusters` explicitly at any real scale. The default is
`len(structures)//3`, which for 1000 inputs means 333 clusters and an unreadable
figure; the palette only has 10 distinct colours, so keep it ≤ 10.

**3. (Optional) Downstream analyses** — these read `cluster_assignments.csv`, so
run them after step 2:

```bash
# Find a discriminating stretch of the channel to cluster on, then re-cluster:
python3 python_scripts/find_reference_region.py
python3 python_scripts/cluster_tunnels.py --region <LO> <HI> --out results/clustering_region

# Link predicted binding affinity to tunnel clusters (needs a Boltz-2 summary CSV):
python3 python_scripts/cluster_affinity_violin.py --summary-csv <boltz_summary.csv>

# Compare tunnel clusters against CUPP sequence clades (needs a CUPP clade file):
python3 python_scripts/cluster_clade_heatmap.py
```

Boltz-2 is a separate GPU step in a different env — see [`../boltz/`](../boltz/).

See [`caver_pipeline/README.md`](caver_pipeline/README.md) for the CAVER
parameters, the tunnel filters, clustering options, and region-restricted
clustering.

---

## Configuration

- **Stage A filter thresholds** (druggability, volume, Fe-proximity, …) are
  `pipeline.py` flags — see the fpocket README.
- **Stage B CAVER parameters** (probe radius, clustering threshold, …) live in
  `caver_pipeline/config.txt`, the shared template applied to every structure.
  Its `starting_point_residue` line is overwritten automatically per structure.

---

## Reference structures

`5FUJ_heme`, `5OXU_heme`, and `9HE9_heme` are characterised natural UPOs. They
serve two purposes:

- as **test data**, they exercise both stages end to end;
- as **references**, copy them into your input folder alongside your own
  structures. They calibrate the pocket thresholds — which were tuned on
  crystal structures — and anchor the tunnel clustering. "This design clusters
  with 5OXU" is a much stronger statement than "these designs form 8 groups".

Leave them out if you really only want your own structures.
