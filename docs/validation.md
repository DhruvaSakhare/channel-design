# Validation

What this software checks, and what it does not. **Measured results — the
design outcome, the benchmark measurements, and the magnitude of the two
measurement artifacts below — are reported on the
[wiki](https://2026.igem.wiki/dtu-denmark/) and deliberately not duplicated
here.** This page is about the code: which rules it enforces, which claims the
test suite covers, and where the gaps are.

## The two measurement artifacts

Both were found by measuring the same structure twice and getting different
numbers, and both were large enough to have produced a confident wrong answer.
Each is fixed in
`channel_discovery/caver_pipeline/python_scripts/staging.py` rather than in a
convention someone has to remember.

### 1. Comparing holo designs against apo crystals

RF3 folds enzyme + heme + substrate, so every design comes out **holo**. The
CAVER reference crystals (`5FUJ_heme`, `9HE9_heme`, `5OXU_heme`) are **apo** —
heme and metals only. A bound substrate occupies part of the channel, so
measuring a holo design against an apo reference reports how much of the
channel the substrate fills rather than how wide the protein's channel is.

The artifact is several times larger than the real difference between distinct
UPO crystal structures, so it can support the opposite conclusion from the
correct one about whether a channel needs widening at all.

**Fix:** `staging.py` strips the substrate by default, keeping heme,
crystallographic metals and ions, which are part of the fold. Scripts refuse to
compare a baseline measured one way against designs measured the other.

### 2. CAVER's output depends on the input *filename*

Byte-identical input, run under different filenames, gives a different
bottleneck radius — a spread larger than the difference between real
structures. The same bytes under the same filename is exactly reproducible. The
cause is inside CAVER 3.0's randomised tunnel search, which seeds from the
input name.

**Fix:** every structure is staged as `structure.pdb` before measurement, so
the name is constant by construction and runs are reproducible.

> Both artifacts were originally present in `channel_discovery/` as well. Both
> fixes now live in one shared module, used by `run_batch.py` and by the
> design-side wrapper `enzyme_design/lib/caver_utils.py`. The shared
> `run_batch.py` path is covered by tests but has not been re-measured against
> real CAVER. See [KNOWN_ISSUES.md](../KNOWN_ISSUES.md).

## Benchmark against public crystals

The three reference structures are public PDB entries, so the measurement can
be reproduced against data we did not generate. Measured apo, under canonical
staging, the parent sits inside the range spanned by the three independent
crystal structures — which is the check that the measurement is calibrated at
all. The values are on the wiki.

Reproduce them with:

```bash
python enzyme_design/partial_diffusion/scripts/00_caver_channel.py <structure.pdb>
```

## Mechanistic checks

Geometry measured from coordinates, not taken from annotations:

- The proximal cysteine's SG sits at coordination distance from the heme iron,
  recovering the known UPO catalytic architecture from the structure alone.
- The parent's constriction is formed by two residues that are both catalytic.

That second result is a finding, not a detail: **the ceiling on widening this
channel is catalytic.** Going much further means touching the active site, so
the next lever is `PARTIAL_T`, not more flexible residues.

## Software validation

This is the part that lives in the repository, because it is checked by code:

| claim | how it is checked |
|---|---|
| Every shipped config runs | `tests/test_configs.py` imports all of them. This began as a real failure: team configs had `PIPELINE_ROOT` one level too deep and raised `FileNotFoundError` on import, so they could not be run at all. Now 100% import. |
| Ligands are visible to ligand-aware steps | `tests/test_input_structures.py`. One config pointed at a structure whose substrate was written as `ATOM`; CAVER finds no tunnels there and many in the corrected file. |
| Boltz-2 output still feeds the channel clustering | `tests/test_affinity_contract.py` runs the real join on fixtures. |
| Resuming a batch does not double-count | `tests/test_boltz_resume.py`, written against a reproduced failure. |
| The two measurement rules are enforced on both entry points | `tests/test_channel_staging.py`. |
| The LSF and single-GPU drivers run the same stages | `tests/test_stage_parity.py`, written after they drifted. |
| No cluster path or user id can return | `tests/test_no_machine_paths.py`. |

Run the whole suite with `uv run --extra tests pytest -q`. It needs no GPU, no
cluster, no model weights and no network.

## Environments the pipeline has actually run in

Worth stating separately from the science, because "will this install" is the
first question a reader has and the honest answer used to be a shrug.

| | tested | note |
|---|---|---|
| CAVER 3.0 on **JDK 8** | yes | what it was built against, in 2013 |
| CAVER 3.0 on **JDK 17** | yes | openjdk 17.0.20.1, Red Hat build, on a Linux cluster. Measured the shipped `PabUPO-II_withHEMEFE_and_NNBT.pdb` to the same bottleneck, length and throughput as the Java 8 run, so the parent baseline reproduces on 17 |
| fpocket from source, **Linux x86_64** | yes | `scripts/fetch_third_party.sh` clones and builds it clean |
| fpocket from source, **macOS arm64** | no — fails | fpocket's bundled qhull. Upstream issue, not patchable here. Only the pocket stage needs it; tunnel measurement does not |
| `vina` wheel, **Linux x86_64** | yes | prebuilt wheel on PyPI |
| `vina` wheel, **macOS arm64** | no wheel | builds from source, needs `brew install boost` |

Both JDK rows matter for a reason beyond installation: CAVER's tunnel search is
randomised (see artifact 2 above), so "same input, different JVM, same numbers"
is a stronger reproducibility statement than it looks.

## What is not validated

Stated plainly, because the gaps matter more than the claims:

- **No wet-lab validation.** Every result is computational. No design has been
  expressed or assayed.
- The full rescore of the passing designs is unfinished, so the design result
  rests on a correlated sample from a single backbone.
- `channel_02` (more flexible residues) has not been compared against
  `channel_01`. If the pass rate holds but the median gain does not improve,
  the constriction is backbone-limited.
- The `--noise` threshold in `08_probe_channel.py` is a guess; residual noise
  between near-identical structures was never measured.
- The shared `staging.py` path has not been re-measured against real CAVER
  since the two rules were moved into it.
