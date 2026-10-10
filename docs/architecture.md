# Architecture

## The four components

```
                    FASTA (sequences)
                          │
        ┌─────────────────▼──────────────────┐
        │ boltz/                             │  GPU
        │ Boltz-2: holo structure + affinity │
        └────────┬──────────────────┬────────┘
                 │ PDB              │ CSV: accession, ligand_iptm,
                 │                  │      affinity_pred_value
        ┌────────▼────────┐         │
        │ docking/        │         │
        │ AutoDock Vina   │         │
        └────────┬────────┘         │
                 │ poses            │
        ┌────────▼──────────────────▼────────┐
        │ channel_discovery/                 │  CPU
        │ Stage A  fpocket → pocket + docking│
        │ Stage B  CAVER   → tunnels, clusters│
        └────────┬───────────────────────────┘
                 │ FLEXIBLE_RESIDUES, baseline bottleneck
        ┌────────▼───────────────────────────┐
        │ enzyme_design/                     │  GPU
        │ RFD3 partial diffusion             │
        │   → LigandMPNN  (sequences)        │
        │   → RF3         (fold + score)     │
        │   → CAVER rescore  (did it widen?) │
        └────────────────────────────────────┘
```

The loop closes: CAVER picks which residues to free, gates backbones before
they cost GPU time, and scores the folded designs.

## Two different questions

It is easy to look at this and wonder why AutoDock Vina is here at all, given
that the tunnel analysis never uses a docked pose. They answer different
questions, and a candidate enzyme has to pass both:

| | the question | answered by |
|---|---|---|
| **Chemistry** | can the substrate *react* here — does it fit the active site in a productive orientation? | Vina + `analyze_poses.py` |
| **Access** | can the substrate *get* here — is the tunnel to that site wide enough? | CAVER |

`analyze_poses.py` is explicit about the first: the ligand's ring centroid must
be within a cutoff of the heme iron *and* closer to it than the hydroxyl
oxygens. NNBT has to present its ring to the iron to be oxidised, so a pose
that fits but sits hydroxyls-first is useless. No amount of tunnel widening
rescues a substrate that cannot be attacked once it arrives.

**So docking belongs to discovery, not to the design loop.** Stage A screens
*many* candidate enzymes — which of these can process this substrate at all?
Once one is chosen and the question becomes "widen its tunnel", there is
nothing to re-dock: the chemistry is already known to work.

That is why `--skip-docking` is a supported way to run Stage A. The tunnel
stage needs the **pocket location** as its anchor, not the pose. fpocket finds
the pocket, `pocket_box.py` turns it into a Vina search box *if* you are
docking, and `pocket_selection.tsv` goes to Stage B either way. Which in turn
is why the whole tunnel half runs without vina, and therefore without the boost
headers vina needs to build.

There are two affinity signals available for the screening question, and they
are alternatives rather than a pipeline: Vina's physics-based score, and
Boltz-2's learned `affinity_pred_value`. The latter is what
`cluster_affinity_violin.py` consumes.

## Two real hand-offs

Everything else inside a component is a function call. These two cross a
boundary, so they are the ones that can break silently.

**1. The CSV contract (Boltz-2 → channel clustering).**
`boltz_template_batch.py` writes `accession, ligand_iptm, affinity_pred_value`;
`cluster_affinity_violin.py` reads exactly those and joins `accession` against
`stem` in `cluster_assignments.csv`, keeping rows with `ligand_iptm >= 0.8`.
Because it is a plain CSV, any affinity predictor can be swapped in.
Guarded by `tests/test_affinity_contract.py`.

**2. The path link (enzyme_design → channel_discovery).**
The design stages measure channels with CAVER configuration and the mmCIF
converter that live in `channel_discovery/`. Before publication both sat inside
one directory and the link was a relative path. They are now separate top-level
components, so the link is resolved in one place —
`enzyme_design/lib/paths.py` — with environment overrides.
Guarded by `tests/test_paths.py`.

## Configuration layers

An experiment is portable; a filesystem is not. The two are kept apart, which
is why a config can be published without publishing somebody's scratch
directory.

| layer | file | holds |
|---|---|---|
| **Experiment** | `partial_diffusion/configs/config_*.py` | enzyme, `FLEXIBLE_RESIDUES`, substrate SMILES, cutoffs. Committed. |
| **Machine** | `partial_diffusion/site.py` | install paths, checkpoints, queues, work root. Defaults are repo-relative; every value takes an environment override. |
| **Your overrides** | `envs/site.env` (gitignored) | copied from `envs/dtu-hpc.env.example` |

Select a config with `PIPELINE_BASE_CONFIG`; see what resolved with:

```bash
python enzyme_design/partial_diffusion/site.py
python enzyme_design/lib/paths.py
```

## Stage scripts

`enzyme_design/partial_diffusion/scripts/` is numbered in execution order —
`00_*` prepare, `01`–`06` run the design loop, `07`–`12` analyse. Each is
independently runnable, and each reads the config named by
`PIPELINE_BASE_CONFIG`. `00_submit_all.py --dry-run` prints the whole GPU
command list without submitting anything, which is the cheapest way to see what
the pipeline would do.

## Where the CPU/GPU line falls

This matters for anyone evaluating the project without a cluster:

| needs a GPU | runs on a laptop |
|---|---|
| `boltz/`, and the RFD3 → MPNN → RF3 stages | `docking/`, all of `channel_discovery/`, every analysis script `07`–`12`, and the whole test suite |

The channel measurement half — where the validation work lives — has no GPU
dependency at all.
