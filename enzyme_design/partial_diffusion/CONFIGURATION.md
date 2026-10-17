# Configuration reference

Every setting in `partial_diffusion/config.py`, what it does, and how to choose
a value. Start from [README.md](README.md) if you have not run the pipeline yet.

---

Edit **`partial_diffusion/config.py`** — the only file you need to change.

| Variable | Description |
|---|---|
| `YOUR_NAME` | Your first name, lowercase — determines your output folder |
| `EXPERIMENT` | Output folder name — **unique per run** |
| `INPUT_PDB` | Full enzyme structure (ligands on separate chains) |
| `HEME_NAME` | Heme residue name in PDB (`HEM`, `HEC`, `HEA`) |
| `SUBSTRATE_NAME` | Substrate residue name in PDB |
| `FLEXIBLE_RESIDUES` | **The main knob** — residue numbers free to move/redesign; everything else is held rigid + native (see below) |
| `_CATALYTIC_PINS` | Catalytic/structural residues → extra sidechain atoms to pin (preserves active-site geometry) |
| `CATRES` | *Derived* from `FLEXIBLE_RESIDUES` — don't edit by hand |
| `FIXED_ATOMS` | *Derived* from `FLEXIBLE_RESIDUES` + `_CATALYTIC_PINS` — don't edit by hand |
| `PARTIAL_T` | Angstroms of noise added before denoising (see tuning guide) |
| `CONTIG` | Auto = whole chain — override only for de-novo loop rebuild |
| `SUBSTRATE_SMILES` | SMILES of substrate (leave blank if using `SUBSTRATE_CCD`) |
| `SUBSTRATE_CCD` | CCD code of substrate (leave blank if using `SUBSTRATE_SMILES`) |
| `NATIVE_MSA_PATH` | MSA RF3 folds against. *Auto-discovered* as `<pdb_stem>_A.a3m.gz` beside `INPUT_PDB`, then in `../inputs/` — build it with `00_make_msa.py`, don't edit. `""` = single-sequence (lower `PLDDT_CUT` to match) |
| `PLDDT_CUT` | Min enzyme pLDDT to pass (default 0.70) |
| `PAE_CUT` | Max enzyme–substrate PAE in Å to pass (default 12.0) |
| `IPSAE_CUT` | Min substrate ipSAE to pass (default 0.40) |
| `RFD3_BATCH_SIZE` | Backbones per RFD3 batch |
| `RFD3_N_BATCHES` | Batches to run — total backbones = BATCH_SIZE × N_BATCHES |
| `RF3_NUM_STEPS` | RF3 diffusion steps (50=fast, 200=production) |
| `RF3_GROUP_SIZE` | Designs per RF3 array task (default 10) |
| `QUEUE` | **GPU** queue for RFD3 / MPNN / RF3 folding. From `site.py`, no default — set `PIPELINE_QUEUE` or pass `--queue` |
| `CPU_QUEUE` | **CPU** queue for prep / the CAVER gate / scoring — no GPU. From `site.py`, no default — `PIPELINE_CPU_QUEUE` or `--cpu-queue` |

## Targeted remodeling — choosing what changes

The template is driven by one list, **`FLEXIBLE_RESIDUES`**. Every residue **not**
in it is held **rigid** (its backbone is pinned in RFD3) **and native** (its
sequence is kept in MPNN). Every residue **in** it is free to move and be
redesigned. `CATRES` and `FIXED_ATOMS` are built from this automatically:

```
FLEXIBLE_RESIDUES ──► RFD3 pins the backbone of everything ELSE  → only these move
                 └──► MPNN keeps the native sequence of everything ELSE → only these redesigned
```

So "keep most of the enzyme fixed, change only region X" is just: put region X's
residue numbers in `FLEXIBLE_RESIDUES`. Two things to get right:

- **Use the correct residue numbers for *your* structure.** Verify with
  `00_prep_pdb.py --check` (catalytic residues) and, ideally, a channel/pocket
  analysis (e.g. CAVER) for the residues that line the region you're targeting.
- **Keep catalytic/structural residues OUT of `FLEXIBLE_RESIDUES`** and list them
  in `_CATALYTIC_PINS` so their sidechain geometry is preserved.

Because most of the fold is frozen at the crystal structure, RF3 has little room
to get the fold wrong — this both targets your change and tends to give **higher
pLDDT** than noising the whole chain.

> **Smoke-test first.** Pinning hundreds of residues via `FIXED_ATOMS` is a heavy
> constraint; before spending GPU on 100 backbones, run one batch
> (`--n_batches 1`) and confirm RFD3 produces backbones without erroring. If it
> chokes on the large `FIXED_ATOMS`, simplify the pin atoms to `"CA"` in
> `_CATALYTIC_PINS`'s default, or reduce the pinned set.

**Method caveat:** neither RFD3 nor MPNN *optimizes* for a specific geometry
(e.g. a wide channel) — they **sample** structures/sequences near your input.
The property you want emerges and must be **selected afterwards** (e.g. filter
outputs by CAVER tunnel radius). Partial diffusion also stays close to the native
by design, so a lot of a channel's width change comes from MPNN resizing
sidechains, not from backbone motion. For large geometry changes, rebuild a loop
de-novo via `CONTIG` (next section) rather than relying on more noise.

---


## Channel-driven workflow (CAVER in the loop)

Widening a substrate channel has its own workflow, with CAVER measurement in
the loop: the parent measured first to derive `FLEXIBLE_RESIDUES`, a
channel-width gate between RFD3 and MPNN, and before/after scoring of the
folded designs. It is documented in full in
[`CHANNEL_README.md`](CHANNEL_README.md), with the reasoning and the dead ends
in [`CHANNEL_WIDENING_LOG.md`](CHANNEL_WIDENING_LOG.md).

## MSA vs. single-sequence folding

`NATIVE_MSA_PATH` controls what RF3 conditions on at stage 4. It is resolved by
convention — `<pdb_stem>_A.a3m.gz` beside the structure if it exists, otherwise `""`
(single-sequence). Build it with `00_make_msa.py`; no config edit needed.

| | MSA | Single-sequence |
|---|---|---|
| Enzyme pLDDT | Higher | Markedly lower |
| Suggested `PLDDT_CUT` | 0.80–0.85 | ~0.70 |
| Best for | Confirming the scaffold survived diffusion | Discriminating between designs |

**Changing mode invalidates your cutoffs.** The single most common way to get
"0 passing designs" from a working pipeline is to fold single-sequence while
keeping an MSA-calibrated `PLDDT_CUT`.

Two things worth understanding about what the MSA is actually doing:

- **The alignment is of the native sequence, but the designs are mutants.**
  Because partial diffusion preserves length and numbering, the native `.a3m`
  is dimensionally compatible with every design and RF3 accepts it silently.
  At your `FLEXIBLE_RESIDUES` positions the alignment therefore argues for the
  *native* residue, not your designed one.
- **`enzyme_plddt` is chainwise.** It averages over the whole of chain A, which
  is mostly untouched native scaffold. With an MSA it will be high for nearly
  every design. It confirms diffusion didn't break the fold; it says little
  about your pocket. The metrics that actually discriminate designs are
  `substrate_min_pae` and `substrate_ipsae` — interface scores against a ligand,
  which has no MSA at all.

**Don't build one MSA per design.** An MSA is a database search result; a
handful of substitutions returns essentially the same homologs. You would spend
hundreds of queries against a free public server to regenerate the alignment you
already have.

## Tuning `PARTIAL_T`

`PARTIAL_T` is in **Angstroms** of coordinate noise added before denoising.

| Value | Effect |
|---|---|
| 3–5 | Very gentle — the flexible residues barely move; lowest risk to the fold |
| 5–10 | Conservative — small local adjustments, stays close to input |
| 10–15 | Moderate — noticeably different backbones, lower pass yield |
| 20+ | Aggressive — large changes; often reduces fold quality |

With a targeted `FLEXIBLE_RESIDUES` set, start around **5**. If the region barely
changes, raise it; if pLDDT is low, lower it (or shrink `FLEXIBLE_RESIDUES`).
Remember `PARTIAL_T` applies to the flexible residues — the rest stays put.

## Engineering specific regions (de-novo loop rebuild)

`FLEXIBLE_RESIDUES` lets a region *move*; to actually *rebuild* a loop from
scratch (a bigger change than partial diffusion can make), override `CONTIG`.
This is the stronger "backbone lever" for reshaping a channel or removing a
blocking loop. If the loop runs from A95 to A115:

```python
# In config.py — replaces the A95-A115 loop with 5-12 brand-new residues
CONTIG = "A4-94,5-12,A116-327"
```

The numeric range `5-12` (no chain prefix) tells RFD3 to design that many
residues from scratch. This is more targeted than increasing `PARTIAL_T` and
directly removes steric bulk from a specific region.

## Recommended settings for production runs

| Setting | Test | Production |
|---|---|---|
| `RFD3_BATCH_SIZE` | 2 | 10 |
| `RFD3_N_BATCHES` | 1 | 10 → 100 backbones |
| `MPNN_BATCH_SIZE` | 2 | 10 |
| `MPNN_NUMBER_OF_BATCHES` | 1 | 1 → 10 seqs/backbone |
| `RF3_NUM_STEPS` | 50 | 200 |
| `RF3_GROUP_SIZE` | 10 | 10 |

---

