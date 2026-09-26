# Changelog — channel widening work

Session log of everything added or modified, and why. For *how to run* it see
[`enzyme_design/partial_diffusion/CHANNEL_README.md`](enzyme_design/partial_diffusion/CHANNEL_README.md);
for the full debugging history see
[`enzyme_design/partial_diffusion/CHANNEL_WIDENING_LOG.md`](enzyme_design/partial_diffusion/CHANNEL_WIDENING_LOG.md).

---

## The short version

The pipeline could remodel an enzyme but had no way to tell whether the change
did what it was for. CAVER existed in `channel_discovery/` but was disconnected
from `enzyme_design/partial_diffusion/`. This wires the two together — CAVER now picks which
residues to free, gates backbones before they cost GPU time, and scores the
folded designs — and fixes two measurement bugs that made the existing
comparisons unreliable.

**Result on PabUPO-II:** parent bottleneck 0.983 Å → best design **1.094 Å
(+11.3%)**, wider than all three reference UPO crystals, at pLDDT 0.96.

---

## Two measurement bugs (these invalidated existing comparisons)

**1. apo vs holo.** RF3 folds enzyme + heme + substrate, so designs come out
*holo*; the CAVER reference crystals are *apo*. A bound substrate costs ~0.45 Å
of bottleneck radius. The spread across the three real references is 0.077 Å —
**the artifact is ~6× the signal**. Every comparison of designs against those
references was measuring ligand occupancy, not channel shape.

**2. CAVER depends on the input filename.** Byte-identical input under 8
different filenames gave 0.0885 Å of spread — again larger than the difference
between real structures. Same bytes + same name is perfectly reproducible
(0.0000 over 6 repeats). Cause is inside CAVER 3.0's randomized tunnel search.

Both are handled in `enzyme_design/lib/caver_utils.py`: strip the substrate by default, stage
every structure as `structure.pdb`. Scripts refuse to compare a baseline
measured one way against designs measured the other.

> Neither is fixed in `channel_discovery/` itself. Any run there comparing
> designs to those references still carries both.

---

## New files

| file | purpose |
|---|---|
| `enzyme_design/lib/caver_utils.py` | run CAVER, read tunnel geometry / lining residues / path. Enforces both measurement rules |
| `enzyme_design/partial_diffusion/scripts/00_caver_channel.py` | measure the parent → `FLEXIBLE_RESIDUES`, baseline, tunnel placeholder |
| `enzyme_design/partial_diffusion/scripts/02b_caver_filter.py` | drop collapsed backbones between RFD3 and MPNN (cheap CPU gate before expensive GPU work) |
| `enzyme_design/partial_diffusion/scripts/07_caver_rescore.py` | rank folded designs by real Δ-bottleneck vs the parent |
| `enzyme_design/partial_diffusion/scripts/08_probe_channel.py` | measure ONE backbone, verdict + what to change, logs each attempt |
| `enzyme_design/partial_diffusion/scripts/09_compare_to_parent.py` | did the core survive? Pinned vs flexible RMSD, separately |
| `enzyme_design/partial_diffusion/scripts/10_plot_channels.py` | channel profile overlay (`--mirror`, `--normalize`, `--smooth`) |
| `enzyme_design/partial_diffusion/scripts/11_cluster_channels.py` | cluster designs by channel *shape*, not just bottleneck |
| `enzyme_design/partial_diffusion/scripts/12_bottleneck_residues.py` | what is physically blocking the channel, and was it flexible? |

## Modified

| file | change |
|---|---|
| `enzyme_design/partial_diffusion/scripts/00_submit_all.py` | `--pilot` (1 backbone, RFD3 only); `--flexible` / `--placeholder` / `--mpnn-temp` overrides; pilots auto-name to avoid the resume trap; CAVER filter split into its own CPU job |
| `enzyme_design/partial_diffusion/scripts/03_mpnn_submit.py` | `--temperature`; `SHRINK_RESIDUES` / `OMIT_AA_AT_SHRINK`; two hard safety checks |
| `enzyme_design/partial_diffusion/scripts/01_rfd3_partial_submit.py` | optional channel-placeholder ligand (currently off) |
| `enzyme_design/partial_diffusion/config_template.py` | new knobs at backwards-compatible defaults |

`--flexible` rebuilds `CATRES` and `FIXED_ATOMS`, which are *derived* from
`FLEXIBLE_RESIDUES`. Overriding the list alone would leave RFD3 pinning the
residues you just freed.

## Configs

| file | what |
|---|---|
| `enzyme_design/partial_diffusion/configs/config_pabupo2_channel_01.py` | run 1 — 22 CAVER-derived flexible, 15 shrink |
| `enzyme_design/partial_diffusion/configs/config_pabupo2_channel_02.py` | run 2 — 32 flexible, 25 shrink; only the residue set differs |
| _(not published -- a near-duplicate of the two above)_ | PabUPO-II helix 86-107, sotiris's own choice, with the new machinery |

**11 team configs were fixed.** All of sotiris's, most of kristine's, both of
donatela's had `PIPELINE_ROOT = Path(__file__).resolve().parent` — correct for
`config.py` but wrong one level deeper, so `INPUT_PDB` resolved to
`enzyme_design/partial_diffusion/inputs/` and the config raised `FileNotFoundError` on import.
They could not be run at all. Now 26/26 import.

---

## Findings worth keeping

**`MPNN_TEMPERATURE` was the "all designs look the same" bug.** LigandMPNN
defaults to 0.1, effectively argmax. With ~300 of 335 positions pinned, the few
free ones got the same residue nearly every time. Now 0.25.

**Nothing rewarded keeping the channel open.** RFD3 packs protein; an empty
channel is a void and compact packing wins. Tried a dummy-atom placeholder to
occupy the bore — took three rounds of bug fixes (column alignment, atom-serial
ordering, then `TUN` turning out to be a real 6-atom CCD code) and is currently
**off** by choice. `SHRINK_RESIDUES` is the cleaner lever.

**The ceiling is catalytic.** The parent's constriction is formed by PHE215
(2.66 Å) and GLU212 (2.81 Å) — both catalytic. Cys52's SG sits 2.35 Å from the
heme iron, a real coordination bond measured from coordinates, not taken from a
comment. Widening much past current levels means touching the active site.

**Verify CLI flags against the installed package, not upstream docs.** The
deployed `mpnn` is a custom build whose flag names differ from public
LigandMPNN. Trusting the public docs cost a full 10-backbone MPNN stage.

**Some "failed" jobs succeed.** `caver_filter` and `rf3_prep` report
`signal 9` / `TERM_EXTERNAL_SIGNAL` while completing their work — the job
scripts' cleanup loop takes down the shell before `exit 0`. Check the output
files exist before assuming failure.

---

## Results

Measured apo, canonical staging:

| structure | bottleneck |
|---|---|
| 5FUJ (reference) | 0.975 Å |
| **PabUPO-II parent** | **0.983 Å** |
| 9HE9 (= PabUPO-II crystal) | 1.032 Å |
| 5OXU (reference) | 1.050 Å |
| MroUPO | 1.058 Å |

**`channel_01`** (22 flexible, 15 shrink): 10/10 RFD3 backbones widened, mean
+0.057 Å. 174/200 designs passed pLDDT/PAE/ipSAE — forbidding six bulky residue
types did *not* destabilize the fold. Of the first 20 folded designs measured:
**16/20 widened, median +0.042 Å, best 1.094 Å (+0.111)**.

So roughly two-thirds of the backbone-stage gain survives MPNN sequence design
and RF3 refolding.

⚠️ Those 20 are all from backbone `model_0` — alphabetically first, therefore
correlated and **not representative**. The full 174-design rescore is still
outstanding.

---

## Open

1. Finish rescoring all 174 of `channel_01`.
2. Compare `channel_02` (32 flexible) against `channel_01`. If the pass rate
   holds but the median gain does not improve, the constriction is
   backbone-limited and the next lever is `PARTIAL_T`, not more residues.
3. Hand `KNOWN_ISSUES.md` to whoever owns the MroUPO bias code — three
   issues there, including an `INPUT_PDB` that CAVER finds zero tunnels in.
4. Tell whoever owns `channel_discovery/` about the two measurement bugs.
5. `--noise 0.02` in `08_probe_channel.py` is still a guess — residual noise
   between near-identical structures was never measured.

---

## Published as `channel-design`, September 2026

Assembled for the iGEM 2026 Best Software award. What changed in the process:

- Four components brought together into one repository: `boltz/`, `docking/`,
  `channel_discovery/`, `enzyme_design/` (previously `enzmsa/`).
- Third-party software de-vendored. CAVER 3.0 (GPLv3) and fpocket are fetched
  rather than committed; no binaries ship.
- Install paths, checkpoints and queues moved out of every config into
  `partial_diffusion/site.py`, with environment overrides and repo-relative
  defaults. 29 per-person configs reduced to 7 that differ scientifically.
- Model weights now documented from upstream (`RosettaCommons/foundry`) rather
  than assumed to exist at a private path.
- A CPU-only test suite: the CSV contract between components, every shipped
  config, cross-component path resolution, and two regression guards.
- Fixed: the Boltz batch driver duplicated summary rows on every `--resume`,
  which silently double-counted in the affinity clustering.
- Fixed: `config_mroupo_nnbt.py` pointed at a structure whose substrate was
  written as `ATOM`, where CAVER finds zero tunnels.
