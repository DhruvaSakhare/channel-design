# Channel widening — how to run it

Widen an enzyme's substrate channel without breaking its fold or active site.
CAVER measures the channel; RFD3 / LigandMPNN / RF3 rebuild it; CAVER measures
again to say whether it worked.

This is the channel-specific layer on top of the partial diffusion pipeline —
see [`README.md`](README.md) for the base pipeline, and
[`CHANNEL_WIDENING_LOG.md`](CHANNEL_WIDENING_LOG.md) for what was tried, what
broke, and why things are the way they are.

---

## The loop

```
              00_caver_channel.py          measure the parent
                       │                   → FLEXIBLE_RESIDUES, baseline.json
                       ▼
  ┌──────────  00_submit_all.py --pilot     1 backbone, RFD3 only, ~15 min
  │                    │
  │            08_probe_channel.py          WIDER? NARROWER? what to change
  │                    │
  └── adjust config ◄──┘  (loop until WIDER)
                       │
                       ▼
              00_submit_all.py             full run:
                       │                     RFD3 → 02b CAVER filter
                       │                     → MPNN (SHRINK_RESIDUES)
                       │                     → RF3 → score
                       ▼
              07_caver_rescore.py          did the folded designs stay open?
              09_compare_to_parent.py      did the core survive?
              10 / 11 / 12                 plots and diagnosis
```

## Every run starts here

```bash
cd <your clone>/enzyme_design
conda activate protein-design        # see envs/design.md
export PIPELINE_BASE_CONFIG=partial_diffusion.dhruva_configs.config_channel_02
```

**That export is not optional.** Without it everything silently falls back to
`partial_diffusion/config.py` — a different person's experiment, a different
residue list, and possibly a directory you cannot write to. It does not survive
reconnecting. Put it in `~/.bashrc`. Always check before submitting:

```bash
python -c "
import importlib, os
C = importlib.import_module(os.environ['PIPELINE_BASE_CONFIG'])
print(C.EXPERIMENT, '|', len(C.FLEXIBLE_RESIDUES), 'flex |', C.WORK)
"
```

---

## Step 0 — measure the parent (once per enzyme)

```bash
python partial_diffusion/scripts/00_caver_channel.py \
    inputs/PabUPO-II_withHEMEFE_and_NNBT.pdb \
    --exclude 52,85,137,205,212,215,296,339      # your catalytic residues
```

Writes next to the input PDB:

| file | what it is |
|---|---|
| `<stem>_baseline.json` | the bottleneck radius to beat, and how it was measured |
| `<stem>_flex.json` | channel-lining residues, ready for `--flexible` |
| `<stem>_channel.pdb` | tunnel axis as dummy atoms (placeholder — currently unused) |

It splits lining residues two ways, and the split matters:

- **sidechain-lining** — MPNN can swap these for something smaller
- **backbone-only** — the wall is the mainchain; no sequence change touches
  them, only RFD3 moving the backbone

## Step 1 — pilot (when changing config)

```bash
python partial_diffusion/scripts/00_submit_all.py --pilot
```

One backbone, RFD3 only, minutes instead of hours. Pilots auto-name themselves
`probe_001`, `probe_002`, … — reusing a name would make RFD3 skip and you would
silently re-measure the *old* backbone.

```bash
NEW=$(ls -dt "$PIPELINE_WORK_ROOT"/*/probe_* | head -1)
python partial_diffusion/scripts/08_probe_channel.py $NEW/diffusion_out/*.cif.gz \
    --baseline inputs/PabUPO-II_withHEMEFE_and_NNBT_baseline.json
```

Prints `WIDER` / `NARROWER` / `UNCHANGED`, suggests the next change, and logs
every attempt. See the trend with `--history`.

Skip the pilot when only the residue list changed and the chain is known good.

## Step 2 — full run

```bash
python partial_diffusion/scripts/00_submit_all.py
```

Chains five jobs. Default scale is **10 backbones → ~200 designs**, deliberately
small; scale up with `--n_batches 10` once a run looks healthy (same
`EXPERIMENT` reuses existing backbones rather than wasting them).

```bash
bstat                                     # monitor
W="$PIPELINE_WORK_ROOT/example/channel_02"
find $W/mpnn_out -name "*.fa" | wc -l     # sequences written
find $W/rf3_out -name "*.cif.gz" | wc -l  # folded models
```

## Step 3 — did it work?

```bash
# how many passed pLDDT / PAE / ipSAE
cat $W/best_designs/best_designs.csv | wc -l

# the actual question: did the channel stay open?
python partial_diffusion/scripts/07_caver_rescore.py \
    --designs $W/best_designs \
    --baseline inputs/PabUPO-II_withHEMEFE_and_NNBT_baseline.json
```

174 designs takes 1.5–3 h, so use `--limit 20` for a quick read or submit it as
a batch job. Winners land in `best_designs/widened/`.

```bash
# did the core survive, or did RF3 drift?
python partial_diffusion/scripts/09_compare_to_parent.py $W/best_designs/*.cif
```

`pinRMSD` should be small (the 300+ pinned residues), `flexRMSD` larger (the
channel), `pinID%` ~100 (MPNN kept them native).

## Step 4 — look at it

```bash
# profile overlay, mirrored cross-section style
python partial_diffusion/scripts/10_plot_channels.py \
    --rescore-dir $W/scores --parent-caver inputs/caver_PabUPO-II_withHEMEFE_and_NNBT/out \
    --mirror --normalize --smooth 1.5 --top 6 --out $W/scores/profiles.png

# cluster designs by channel SHAPE (not just bottleneck)
python partial_diffusion/scripts/11_cluster_channels.py \
    --rescore-dir $W/scores --parent-caver inputs/caver_PabUPO-II_withHEMEFE_and_NNBT/out \
    --n-clusters 4 --out-dir $W/scores/clusters

# what is physically blocking the channel, and was it flexible?
python partial_diffusion/scripts/12_bottleneck_residues.py \
    --caver-out $W/scores/caver_rescore/<design>/out --shell 5.0 --propose
```

`--smooth` affects the drawing only; quoted bottleneck numbers are always raw.

---

## Two measurement rules the code enforces

Both were found by measuring the same structure twice and getting different
answers. Do not "fix" either one.

**1. Always measure apo.** RF3 folds enzyme + heme + substrate, so designs come
out holo; the CAVER reference crystals are apo. A bound substrate costs ~0.45 Å
of bottleneck radius — roughly **6× the spread between real UPO structures**.
Every script here strips the substrate by default and refuses to compare a
baseline measured one way against designs measured the other.

> `channel_discovery/` does **not** strip. Any run there comparing designs to
> those references carries this artifact.

**2. Never let CAVER see the real filename.** CAVER 3.0 returns a different
tunnel set for byte-identical input under a different name — 0.09 Å of spread
across 8 filenames, again larger than the difference between real structures.
`caver_utils.run_caver` stages everything as `structure.pdb`. Same bytes + same
name is perfectly reproducible.

---

## Reference numbers

Measured apo, canonical staging:

| structure | bottleneck |
|---|---|
| 5FUJ (reference) | 0.975 Å |
| **PabUPO-II parent** | **0.983 Å** |
| 9HE9 (= PabUPO-II crystal) | 1.032 Å |
| 5OXU (reference) | 1.050 Å |
| MroUPO | 1.058 Å |

### Run history

| run | flexible | shrink | result |
|---|---|---|---|
| `channel_01` | 22 | 15 | 10/10 backbones widened (mean +0.057). 174/200 passed gates. Of first 20 folded: **16/20 widened, median +0.042, best 1.094 Å (+0.111)** |
| `channel_02` | 32 | 25 | in progress — only the residue set changed |

**The ceiling is catalytic.** `12_bottleneck_residues.py` shows the parent's
constriction is formed by PHE215 (2.66 Å) and GLU212 (2.81 Å), both catalytic.
Cys52 is 2.35 Å from the heme iron — a real coordination bond, verified from
coordinates, not annotation. Widening past a point means touching the chemistry.

---

## Things that will bite you

| symptom | cause |
|---|---|
| wrong residue list in the submit header | `PIPELINE_BASE_CONFIG` not exported |
| `Permission denied` writing scores | same — it resolved to someone else's `WORK` |
| `mpnn: command not found` | conda env not active in this shell |
| `caver_filter` / `rf3_prep` "killed by signal 9" | **cosmetic.** They finish their work first; the job scripts' cleanup loop takes down the shell before `exit 0`. Check the output files exist before assuming failure |
| probe measures an old backbone | reused `EXPERIMENT`; RFD3 skipped |
| a CLI flag "doesn't exist" | check the *installed* package source, not upstream docs. The deployed `mpnn` is a custom build — see the log, §7c |
