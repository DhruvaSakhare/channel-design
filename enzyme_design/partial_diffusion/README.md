# Partial Diffusion Pipeline

Remodel an existing UPO (or any enzyme) for a new substrate while keeping key
residues fixed. Starts from your full enzyme structure, adds controlled noise,
then denoises — producing variants that retain the overall fold but adapt the
active site.

```
Full enzyme PDB  →  RFD3 partial diffusion  →  LigandMPNN (sequences)  →  RF3 (fold & score)
```

> **Widening a substrate channel?** There is a dedicated workflow with CAVER
> measurement in the loop — a fast pilot gate, a channel-width filter between
> RFD3 and MPNN, and before/after scoring of the folded designs. Start at
> [`CHANNEL_README.md`](CHANNEL_README.md). What was tried and why it is built
> that way is in [`CHANNEL_WIDENING_LOG.md`](CHANNEL_WIDENING_LOG.md).

---

## De novo vs. partial diffusion

| | De novo (`../`) | Partial diffusion (this folder) |
|---|---|---|
| Input PDB | Small theozyme (fixed residues + ligands only) | Full enzyme structure |
| What RFD3 does | Designs a new scaffold from scratch | Remodels the existing fold |
| Use when | No starting structure | You have a good UPO fold to adapt |
| Key setting | `FREE_MIN` / `FREE_MAX` / `LENGTH` | `PARTIAL_T` |

---

## What you need before starting

1. Your full enzyme PDB in `../inputs/` (that directory is yours and ships
   empty — our own structures live in `../examples/`) with:
   - Solvent and non-essential HETATMs removed
   - Heme on its own chain (e.g. chain B)
   - Your substrate on its own chain (e.g. chain C), positioned ~4–5 Å above the iron
   - **Each ligand must be on a unique chain separate from the protein**
2. A SMILES string (or CCD code) for your substrate
3. The residue numbers of the catalytic residues coordinating the heme iron

### Preparing the PDB in PyMOL

If your PDB has all atoms on chain A, separate the ligands first:

```python
# in PyMOL
load your_enzyme.pdb
alter resn HEM, chain="B"
alter resn UNK, chain="C"   # replace UNK with your substrate residue name
alter resn UNK, resi="1"
sort
save your_enzyme_fixed.pdb
```

Verify the result — you should see exactly three chain letters:
```bash
grep -E "^(ATOM|HETATM)" your_enzyme_fixed.pdb | cut -c22 | sort -u
# expected: A  B  C
```

### Extract SMILES from your substrate PDB

If you don't have the SMILES string yet, run:
```bash
python partial_diffusion/scripts/00_smiles_from_pdb.py
```
Copy the printed SMILES into `SUBSTRATE_SMILES` in `config.py`.

### Build the MSA for your enzyme

RF3 folds every design against a multiple sequence alignment of the **native**
enzyme. Build it once per enzyme, on the login node:

```bash
python partial_diffusion/scripts/00_make_msa.py
```

This reads chain A out of `INPUT_PDB`, runs a ColabFold/MMseqs2 search, and
writes `<pdb_stem>_A.a3m.gz` beside your structure. `config.py` finds it by name, so
**a new enzyme needs no config edit** — build the MSA and it is picked up.

It talks to `https://api.colabfold.com` over plain HTTP with no extra
dependencies, so it works on a login node with network access. Nothing to
install. If you have local ColabFold databases, `--backend local --db <dir>`
uses those instead and avoids the public server entirely.

One query per enzyme is normal, courteous use of a free shared service — don't
script it in a loop.

**If you skip this step**, RF3 folds single-sequence. That is a legitimate
choice, but pLDDT comes out markedly lower, so you must drop `PLDDT_CUT` to
around `0.70` — otherwise the gate rejects nearly every design for a reason
that has nothing to do with your designs. See
[MSA vs. single-sequence folding](CONFIGURATION.md#msa-vs-single-sequence-folding).

Check which mode you're in before a long run:
```bash
python -c "import partial_diffusion.config as C; print(C.NATIVE_MSA_PATH or 'SINGLE-SEQUENCE')"
```

---

## Setup (one-time)

**Step 1 — configure your run**

Start from the annotated template, `config_template.py` — copy it to `config.py` and edit the tagged
sections (`★ EVERY RUN`, `◆ PER EXPERIMENT`, `● PER ENZYME`, `✗ DON'T EDIT`):

```bash
cd partial_diffusion
cp config_template.py config.py
```

The key fields:

```python
YOUR_NAME         = "yourname"                 # ★ your first name, lowercase
EXPERIMENT        = "pab_upo_II_tunnel_01"      # ★ UNIQUE per run
INPUT_PDB         = "inputs/your_enzyme_fixed.pdb"  # ● prepped structure
SUBSTRATE_NAME    = "UNL"                        # ● substrate residue name in PDB
SUBSTRATE_SMILES  = "CC1CCC(...)..."             # ● substrate SMILES
PARTIAL_T         = 5                            # ◆ noise level (see tuning guide)

# ◆ THE MAIN KNOB — which residues may move (RFD3) and be redesigned (MPNN).
# Everything NOT listed is held rigid + native. CATRES and FIXED_ATOMS are
# derived from this automatically — you don't edit them by hand.
FLEXIBLE_RESIDUES = [195, 257,258,259,260,261,262, 292,295, 335,336]
```

See [Targeted remodeling](CONFIGURATION.md#targeted-remodeling--choosing-what-changes) for
how `FLEXIBLE_RESIDUES` works and how to choose it.

#### Easier: pick the flexible residues visually in PyMOL

Instead of typing residue numbers into `config.py`, you can select them in PyMOL
and have the pipeline write `config.py` for you. This is the recommended way for
the team — no hand-counting residues.

**On your laptop (in PyMOL):**

1. Open your prepped structure (heme on chain B, substrate on chain C — the same
   PDB you'd feed the pipeline).
2. Select the residues you want **flexible** (free to move + redesign) and name
   the selection `flexible`. Either click residues in the GUI and rename the
   selection to `flexible`, or type e.g.:
   ```
   select flexible, chain A and resi 195+257-262+292+295+335-336
   ```
3. Load and run the helper, then call it:
   ```
   run partial_diffusion/mark_flexible.py
   mark_flexible
   ```
   (Optional args: `mark_flexible <selection>, <chain>, <out_prefix>`.)

   This writes two files: `<name>.pdb` and `<name>_flex.json` (the residue list).

**On the cluster:**

Copy those two files over, then generate the config automatically:
```bash
python partial_diffusion/scripts/00_from_pymol.py <name>.pdb <name>_flex.json \
    --experiment my_run_01 --your-name yourname \
    --substrate-name UNL --substrate-smiles "CC..."
```
This copies the PDB into `inputs/`, and writes a ready `config.py` with
`FLEXIBLE_RESIDUES` and `INPUT_PDB` filled in (`CATRES`/`FIXED_ATOMS` are derived
from them automatically). Review the file, then continue with Step 2 below.

> The PDB must already be prepped (protein on chain A, heme on B, substrate on C
> with unique atom names). `00_from_pymol.py` warns if it doesn't see those.

**Step 2 — check your PDB**

Run this before submitting any jobs — it verifies all CATRES are found, shows
ligand positions, and identifies the proximal heme coordination residue:

```bash
cd <your clone>/enzyme_design
conda activate protein-design        # see envs/design.md
python partial_diffusion/scripts/00_prep_pdb.py --check
```

---

## Running the pipeline

**On a single GPU, use `scripts/run_local.py`.** It runs every stage in order
with no scheduler, and it is the path to start from:

```bash
python partial_diffusion/scripts/run_local.py --check      # what is missing
python partial_diffusion/scripts/run_local.py --dry-run    # print, don't run
python partial_diffusion/scripts/run_local.py              # run the stages
```

`--stages` runs part of it; names are stable where numbers shift if a stage is
inserted. Stages in order: `prep rfd3 process caver_filter mpnn rf3 score
collect`. The pilot — one backbone, RFD3 only, minutes rather than hours — is
`--stages prep-caver_filter`.

**On an LSF cluster**, `00_submit_all.py` submits the same stages as chained job
arrays so the RF3 folds run in parallel. See [CLUSTER.md](CLUSTER.md).

---

## Where everything else is

| | |
|---|---|
| [CONFIGURATION.md](CONFIGURATION.md) | every `config.py` setting; choosing `FLEXIBLE_RESIDUES`; tuning `PARTIAL_T`; MSA vs single-sequence; production settings |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | the errors you are likely to hit, and what each actually means |
| [CLUSTER.md](CLUSTER.md) | the LSF driver: submitting, chaining, monitoring, wall times, queues |
| [CHANNEL_README.md](CHANNEL_README.md) | the channel-widening workflow, with CAVER in the loop |
| [CHANNEL_WIDENING_LOG.md](CHANNEL_WIDENING_LOG.md) | what was tried, what failed, and why it is built this way |

---

## Outputs

All outputs go to `$PIPELINE_WORK_ROOT/<your_name>/<experiment>/`
(default `enzyme_design/work/`, see `partial_diffusion/site.py`):

```
<experiment>/
├── configs/          RFD3 + RF3 input JSONs
├── submit/           LSF submit scripts
├── cmds/             Per-task command files
├── logs/             Job stdout/stderr (named by job ID)
├── diffusion_out/    RFD3 backbones (.cif.gz + .json)
│   └── passing/      Filtered backbones that passed quality checks
├── mpnn_out/         LigandMPNN FASTA sequences (one folder per backbone)
├── rf3_out/          RF3 folded complexes + .score files
├── scores/           Metrics CSVs + plots (PAE vs pLDDT, ranked pLDDT)
└── best_designs/     Passing CIFs + best_designs.csv
```

The three metrics that matter in `best_designs.csv`:

| Metric | Meaning | Pass threshold |
|---|---|---|
| `enzyme_plddt` | Fold confidence (0–1) | > 0.80 |
| `substrate_min_pae` | Substrate placement confidence (Å) | < 8.0 |
| `substrate_ipsae` | Enzyme–substrate interface confidence (0–1) | > 0.50 |

`heme_min_pae` and `heme_ipsae` are also reported as a secondary check that
heme coordination geometry was maintained.
