# Validation

The headline result of this project is a widened substrate channel. The more
useful result is the two measurement bugs we found on the way, because both
were large enough to have produced a confident wrong answer.

## The two negative controls

We found both by measuring the same structure twice and getting different
numbers. Each is quantified, each has a mechanism, and each is fixed in
`enzyme_design/lib/caver_utils.py` rather than in a convention someone has to
remember.

### 1. Comparing holo designs against apo crystals

RF3 folds enzyme + heme + substrate, so every design comes out **holo**. The
CAVER reference crystals (`5FUJ_heme`, `9HE9_heme`, `5OXU_heme`) are **apo** —
heme and metals only.

| quantity | value |
|---|---|
| Cost of a bound substrate in bottleneck radius | **~0.45 Å** |
| Spread across the three real reference structures | **0.077 Å** |

**The artifact is roughly six times the signal.** Every comparison of a design
against those references made before this was found was measuring how much of
the channel the substrate occupied, not how wide the protein's channel is.

MroUPO shows the size of the trap concretely: measured with its docked NNBT it
looks like 0.745 Å, and measured apo it is 1.058 Å — the widest channel of
anything here. The same structure, read two ways, supports opposite conclusions
about whether it needs widening at all.

**Fix:** `caver_utils.py` strips the substrate by default, keeping heme,
crystallographic metals and ions, which are part of the fold. Scripts refuse to
compare a baseline measured one way against designs measured the other.

### 2. CAVER's output depends on the input *filename*

Byte-identical input, run under eight different filenames:

| condition | spread in bottleneck radius |
|---|---|
| Same bytes, 8 different filenames | **0.0885 Å** |
| Same bytes, same filename, 6 repeats | **0.0000 Å** |

Again larger than the 0.077 Å difference between real structures. The cause is
inside CAVER 3.0's randomised tunnel search, which seeds from the input name.

**Fix:** every structure is staged as `structure.pdb` before measurement, so
the name is constant by construction and runs are exactly reproducible.

> Both bugs were originally present in `channel_discovery/` and are fixed only
> in the design-side wrapper. See [KNOWN_ISSUES.md](../KNOWN_ISSUES.md).

## Benchmark against public crystals

Measured apo, canonical staging. The three references are public PDB entries,
so these numbers can be reproduced against data we did not generate.

| structure | bottleneck |
|---|---|
| 5FUJ (reference UPO) | 0.975 Å |
| **PabUPO-II parent** | **0.983 Å** |
| 9HE9 (PabUPO-II crystal) | 1.032 Å |
| 5OXU (reference UPO) | 1.050 Å |
| MroUPO | 1.058 Å |

That the parent sits inside the range spanned by three independent crystal
structures is the check that the measurement is calibrated at all.

## Design result

`channel_01` — 22 CAVER-derived flexible residues, 15 shrink positions:

| stage | outcome |
|---|---|
| RFD3 backbones | **10/10 widened**, mean +0.057 Å |
| Passed pLDDT / PAE / ipSAE | **174/200** — forbidding six bulky residue types did not destabilise the fold |
| Folded designs measured | **16/20 widened**, median +0.042 Å |
| Best design | **1.094 Å (+11.3%)** at pLDDT 0.96 |

The best design is wider than all three reference UPO crystals. Roughly
two-thirds of the gain made at the backbone stage survives sequence design and
refolding, which is the number worth carrying to the next experiment.

> **⚠ This is a preliminary sample, not a representative one.** Those 20 designs
> all come from backbone `model_0` — alphabetically first, therefore correlated.
> The full 174-design rescore is outstanding. We report the number we have and
> the caveat that goes with it rather than the number that sounds better.

## Mechanistic checks

Geometry measured from coordinates, not taken from annotations:

- **Cys52 SG sits 2.35 Å from the heme iron** — a real coordination bond,
  recovering the known UPO catalytic architecture from the structure alone.
- The parent's constriction is formed by **PHE215 (2.66 Å)** and
  **GLU212 (2.81 Å)**, both catalytic.

That second result is a finding, not a detail: **the ceiling on widening this
channel is catalytic.** Going much further means touching the active site, so
the next lever is `PARTIAL_T`, not more flexible residues.

## Software validation

| claim | how it is checked |
|---|---|
| Every shipped config runs | `tests/test_configs.py` imports all of them. This began as a real failure: 11 team configs had `PIPELINE_ROOT` one level too deep and raised `FileNotFoundError` on import, so they could not be run at all. Now 100% import. |
| Ligands are visible to ligand-aware steps | `tests/test_input_structures.py`. One config pointed at a structure whose substrate was written as `ATOM`; CAVER finds 0 tunnels there and 40 in the corrected file. |
| Boltz-2 output still feeds the channel clustering | `tests/test_affinity_contract.py` runs the real join on fixtures. |
| Resuming a batch does not double-count | `tests/test_boltz_resume.py`, written against a reproduced failure. |
| No cluster path or user id can return | `tests/test_no_machine_paths.py`. |

## What is not validated

Stated plainly, because the gaps matter more than the claims:

- **No wet-lab validation.** Every number here is computational. No design has
  been expressed or assayed.
- The 174-design rescore is unfinished, so the design result rests on a
  correlated sample of 20.
- `channel_02` (32 flexible residues) has not been compared against
  `channel_01`. If the pass rate holds but the median gain does not improve,
  the constriction is backbone-limited.
- The `--noise 0.02` threshold in `08_probe_channel.py` is a guess; residual
  noise between near-identical structures was never measured.
