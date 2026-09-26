"""
config_channel_02.py — PabUPO-II channel widening, run 2 (dhruva).

Differs from config_channel.py in ONE thing: the flexible set is 22 -> 32.
PARTIAL_T, MPNN_TEMPERATURE and everything else are unchanged, so any
difference in outcome is attributable to the residue set.

What was added (+10): 87, 91, 95, 206, 259, 261, 293, 294, 297, 331
  - 87/91/95, 206, 293/294/297 make the channel-lining stretches CONTIGUOUS
    (86-96, 204-211, 292-298). Run 1 left isolated residues frozen between
    free ones, which constrains backbone movement more than the count suggests.
  - 259, 261, 331 are the only non-catalytic residues CAVER found lining
    tunnel 1 that run 1 missed (--shell 5.0).

Catalytic residues stay pinned: 52, 85, 137, 205, 212, 215, 296, 339.
Note this caps what run 2 can achieve — 12_bottleneck_residues.py showed the
parent's constriction is formed by PHE215 (2.66 A) and GLU212 (2.81 A), both
catalytic. Freeing those is a separate, riskier experiment.

Run 1 result to beat (channel_01, 22 flexible):
  parent 0.983 A | 16/20 folded designs widened | median +0.042 | best +0.111

Use it:
    export PIPELINE_BASE_CONFIG=partial_diffusion.dhruva_configs.config_channel_02
    python partial_diffusion/scripts/00_submit_all.py --pilot     # sanity check
    python partial_diffusion/scripts/00_submit_all.py             # full run
"""
import os
from pathlib import Path

# ===========================================================================
# ★ EVERY RUN — who you are and a unique name for this run
# ===========================================================================
YOUR_NAME = "dhruva"
EXPERIMENT = "channel_02"   # run 2: wider flexible set (32 vs 22)
                                              #    number or name each time, or a
                                              #    re-run will just resume the old one

# ===========================================================================
# ● PER ENZYME — input structure and ligands (only change for a new enzyme)
# ===========================================================================
# NOTE: .parent.parent, not .parent — this file lives one level deeper than
# config.py (in dhruva_configs/), so it needs an extra hop to reach
# partial_diffusion/. Getting this wrong makes INPUT_PDB resolve to
# partial_diffusion/inputs/ instead of the repo's inputs/ and the config fails
# to import. Several of the older per-person configs have exactly that bug.
PIPELINE_ROOT = Path(__file__).resolve().parent.parent
LIB_ROOT      = PIPELINE_ROOT.parent / "lib"

# The FULL enzyme structure, already prepped: heme on chain B, substrate on
# chain C, unique substrate atom names. (Use fix_pdb_chains.py if it isn't.)
INPUT_PDB = str(PIPELINE_ROOT.parent / "inputs" / "PabUPO-II_withHEMEFE_and_NNBT.pdb")  # ●

HEME_NAME      = "HEM"    # ● heme residue name as it appears in the PDB
SUBSTRATE_NAME = "UNL"    # ● substrate residue name in the PDB
LIGAND_NAMES   = [HEME_NAME, SUBSTRATE_NAME]   # heme first — leave as is

# The MSA RF3 folds designs against. Build it ONCE per enzyme with
#     python partial_diffusion/scripts/00_make_msa.py
# which writes inputs/<pdb_stem>_A.a3m.gz — found automatically by the line
# below, so a new enzyme needs no edit here. Set an explicit path to override.
#
# Empty ("" — i.e. no MSA file present) means RF3 folds single-sequence. That
# is a legitimate choice, but pLDDT runs markedly lower, so drop PLDDT_CUT to
# ~0.70 or the gate will reject nearly every design for the wrong reason.
_msa_default    = PIPELINE_ROOT.parent / "inputs" / f"{Path(INPUT_PDB).stem}_A.a3m.gz"
NATIVE_MSA_PATH = str(_msa_default) if _msa_default.exists() else ""   # ●

# ===========================================================================
# ◆ PER EXPERIMENT — THE MAIN KNOB: which residues are allowed to change
# ===========================================================================
# Residue numbers (chain A) that RFD3 may MOVE and MPNN may REDESIGN. Everything
# else is frozen at the crystal structure + native sequence. This is how you
# target a region (here: the substrate channel) without disturbing the fold.
# Widen the entrance/middle → list the channel-lining residues that make it narrow.
FLEXIBLE_RESIDUES = [
    86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 204,
    206, 207, 208, 209, 210, 211, 257, 258, 259, 261, 292, 293,
    294, 295, 297, 298, 331, 334, 335, 336,
]  # CAVER-derived: residues lining tunnel 1 (the main channel)

# ◆ PER EXPERIMENT — force the channel WIDER by design, not by hope.
# Freeing a residue does NOT widen the channel by itself: MPNN designs a
# well-packed sequence, which usually means keeping the native bulky sidechain
# (e.g. it leaves F292 as Phe). At SHRINK_RESIDUES, the bulky types are simply
# not on the table, so MPNN has to pick something small — the widening is
# written into the sequence and survives folding.
#
# This is the CAVER-derived sidechain-lining subset of FLEXIBLE_RESIDUES —
# specifically NOT the backbone-only liners (90, 94, 204, 209, 210, 211, 334).
# Those seven are narrow because of the mainchain trace itself; no sidechain
# choice changes where a backbone atom sits, so constraining their type there
# is a no-op at best. Only RFD3 moving the backbone can widen those.
#
# 03_mpnn_submit.py enforces: SHRINK_RESIDUES ⊆ FLEXIBLE_RESIDUES, and
# SHRINK_RESIDUES ∩ _CATALYTIC_PINS == empty — the second check exists because
# a teammate's MroUPO config hit exactly that overlap: a residue in both loses
# its pin silently (FIXED_ATOMS only applies to non-flexible residues) while
# also having its native type forbidden. Here it's a hard error instead.
SHRINK_RESIDUES = [
    86, 87, 88, 89, 91, 92, 93, 95, 96, 206, 207, 208,
    257, 258, 259, 261, 292, 293, 294, 295, 297, 298, 331, 335,
    336,
]
OMIT_AA_AT_SHRINK = ["PHE", "TRP", "TYR", "LEU", "MET", "ILE"]  # bulky types forbidden there

# ● PER ENZYME — catalytic / structural residues that are held rigid get EXTRA
# sidechain atoms pinned (not just backbone) so active-site geometry is preserved.
# Keys are residue numbers; values are the atom names to pin. Backbone (N,CA,C,O)
# is included here; the extra atoms lock sidechain orientation. Never put a
# FLEXIBLE residue in here. If RFD3 errors on a big FIXED_ATOMS dict, simplify all
# values to "CA" (lightest pin) or reduce this dict to just residue 52.
_CATALYTIC_PINS = {                            # ●
    52:  "N,CA,C,O,CB,SG",   # proximal catalytic Cys (heme thiolate) — essential
    85:  "N,CA,C,O,CB",      # aromatic tripod, orients substrate toward heme
    137: "N,CA,C,O,CB",      # aromatic tripod
    215: "N,CA,C,O,CB",      # aromatic tripod
    205: "N,CA,C,O,CB",      # acid-base pair (H2O2 cleavage)
    212: "N,CA,C,O,CB",      # acid-base pair
    296: "N,CA,C,O,CB,SG",   # disulfide, stabilises active-site frame
    339: "N,CA,C,O,CB,SG",   # disulfide
}

# ◆ PER EXPERIMENT — how aggressive the remodel is
# PARTIAL_T = amount of noise (Å) added to the FLEXIBLE residues before denoising.
#   3–5  = very gentle: shapes stay close to native, low risk, modest widening
#   8–12 = more backbone freedom: bigger changes, lower pass yield
# Bigger is NOT better — partial diffusion stays near the input by design, so
# real widening also comes from MPNN shrinking the lining (sequence lever).
PARTIAL_T = 10

# ◆ PER EXPERIMENT — channel placeholder. OFF.
#
# Tried a dummy-atom "keep this space open" ligand along the CAVER tunnel axis,
# so RFD3 packs AROUND the channel instead of into it. Took 3 rounds of bug
# fixes to even get RFD3 to accept the file (column alignment, atom-serial
# ordering, then a CCD-template mismatch that forced rewriting it as monatomic
# xenon — see CHANNEL_WIDENING_LOG.md §6). Backed out by request: it rests on
# assumptions about RFD3's internals we can't fully verify, and there's a
# cleaner lever for the same goal — SHRINK_RESIDUES below, which uses a real
# documented LigandMPNN flag instead of tricking RFD3 with a fake ligand.
# The generator script (00_caver_channel.py) still writes the file if you want
# to revisit this; just isn't wired in by default.
CHANNEL_PLACEHOLDER = ""
CHANNEL_PLACEHOLDER_RESNAME = "XE"

# ◆ PER EXPERIMENT — which ligands RFD3 holds fixed while denoising.
# Defaults to LIGAND_NAMES (heme + substrate). The placeholder resname is
# appended automatically when CHANNEL_PLACEHOLDER is set.
RFD3_LIGAND_NAMES = None   # ◆ None = use LIGAND_NAMES

# ◆ PER EXPERIMENT — how many backbones to generate (total = BATCH_SIZE × N_BATCHES)
RFD3_BATCH_SIZE = 10   # backbones per GPU call
RFD3_N_BATCHES  = 1    # ◆ 10 backbones (100 RF3 folds) — deliberately small.
# --pilot only checks RFD3's backbone. Nothing past it — SHRINK_RESIDUES, RF3,
# the score gates — has ever run once. Jumping straight to a big N_BATCHES here
# repeats exactly the problem this whole effort started from: burning GPU hours
# before finding out something downstream doesn't work. This validates the
# WHOLE chain cheaply first. Once 07_caver_rescore.py looks sane on this batch,
# scale up explicitly:
#     python partial_diffusion/scripts/00_submit_all.py --n_batches 10
# (reuses this EXPERIMENT's dir, so these 10 backbones count toward the total
# rather than being wasted — don't bump EXPERIMENT to do this.)

# ---------------------------------------------------------------------------
# ✗ DON'T EDIT — helpers that build CATRES / FIXED_ATOMS / CONTIG for you
# ---------------------------------------------------------------------------
def _chain_resids(pdb_path, chain="A"):
    ids = set()
    with open(pdb_path) as f:
        for line in f:
            if line[:4] == "ATOM" and line[21] == chain:
                ids.add(int(line[22:26].strip()))
    if not ids:
        raise RuntimeError(f"No ATOM records for chain {chain} in {pdb_path}")
    return sorted(ids)

def _build_fixed_atoms(pdb_path, flexible, chain="A"):
    # Pin the backbone of every residue EXCEPT the flexible ones; catalytic
    # residues get their extra sidechain atoms. Result: RFD3 only moves the channel.
    flex = set(flexible)
    return {f"{chain}{r}": _CATALYTIC_PINS.get(r, "N,CA,C,O")
            for r in _chain_resids(pdb_path, chain) if r not in flex}

def _build_catres(pdb_path, flexible, chain="A"):
    # Keep the native sequence of every residue EXCEPT the flexible ones →
    # MPNN only redesigns the channel.
    flex = set(flexible)
    return [f"{chain}{r}" for r in _chain_resids(pdb_path, chain) if r not in flex]

def _auto_contig(pdb_path, chain="A"):
    r = _chain_resids(pdb_path, chain)
    return f"{chain}{r[0]}-{r[-1]}"

# ---------------------------------------------------------------------------
# ✗ DON'T EDIT — run snapshot override
# Every run freezes its settings to <WORK>/configs/run_config.json. Queued jobs
# read that frozen copy, so editing this file to launch a DIFFERENT run can't
# corrupt a run that's already in flight. When the snapshot exists, the values
# below come from it instead of being recomputed.
# ---------------------------------------------------------------------------
_SNAPSHOT_PATH = os.environ.get("PIPELINE_RUN_CONFIG")
if _SNAPSHOT_PATH:
    import json as _json
    with open(_SNAPSHOT_PATH) as _f:
        _overrides = _json.load(_f)
    _PATH_KEYS = {
        "WORK", "CONFIGS_DIR", "SUBMIT_DIR", "LOGS_DIR", "CMDS_DIR",
        "SCORES_DIR", "DIFFUSION_DIR", "MPNN_DIR", "RF3_DIR", "BEST_DIR",
    }
    for _k, _v in _overrides.items():
        globals()[_k] = Path(_v) if _k in _PATH_KEYS else _v

CATRES      = _overrides["CATRES"]      if (_SNAPSHOT_PATH and "CATRES" in _overrides)      else _build_catres(INPUT_PDB, FLEXIBLE_RESIDUES)
FIXED_ATOMS = _overrides["FIXED_ATOMS"] if (_SNAPSHOT_PATH and "FIXED_ATOMS" in _overrides) else _build_fixed_atoms(INPUT_PDB, FLEXIBLE_RESIDUES)
# CONTIG = which residues exist in the design. Auto = whole chain (no de-novo
# rebuild). To REBUILD a loop from scratch (bigger change than partial diffusion),
# override, e.g. "A14-256,4-8,A263-348" rebuilds residues 257-262 with 4-8 new ones.
CONTIG      = _overrides["CONTIG"]      if (_SNAPSHOT_PATH and "CONTIG" in _overrides)      else _auto_contig(INPUT_PDB)  # ◆ override for de-novo loop rebuild

# ===========================================================================
# ● PER ENZYME — substrate chemistry for RF3 (fill in SMILES OR CCD, not both)
# ===========================================================================
HEME_CCD         = "HEM"
SUBSTRATE_SMILES = "CC1CCC(N(C[C@@H](C)O)C[C@@H](C)O)CC1"  # ● SMILES of your substrate (NNBT here)
SUBSTRATE_CCD    = ""    # ● CCD code instead, if your substrate is in the CCD

# ===========================================================================
# ◆ PER EXPERIMENT — pass/fail thresholds used to pick best_designs
# ===========================================================================
PLDDT_CUT = 0.80   # ◆ enzyme fold confidence   > this (0-1, higher = better fold)
PAE_CUT   = 8.0   # ◆ enzyme–substrate PAE     < this (Å,  lower = better placement)
IPSAE_CUT = 0.50   # ◆ enzyme–substrate ipSAE   > this (0-1, higher = better interface)

# ✗ DON'T EDIT — RF3 chain order (A=enzyme, B=heme, C=substrate)
RF3_ENZYME_CHAIN    = "A_1"
RF3_HEME_CHAIN      = "B_1"
RF3_SUBSTRATE_CHAIN = "C_1"

# ===========================================================================
# ◆ PER EXPERIMENT — scale (bigger = more sampling, more GPU time)
# ===========================================================================
MPNN_BATCH_SIZE        = 10   # ◆ sequences designed per backbone
MPNN_NUMBER_OF_BATCHES = 1    # ◆ × above = sequences per backbone

# ◆ PER EXPERIMENT — LigandMPNN sampling temperature.
# LigandMPNN defaults to 0.1, which is near-deterministic: with most positions
# pinned by --fixed_residues, the handful of free ones get essentially the same
# amino acid every time and your N sequences per backbone collapse to a few
# distinct ones. Raise this to actually explore the channel lining.
#   0.1        = LigandMPNN default, near-argmax — sequences repeat
#   0.2-0.3    = real diversity, still high-confidence  (recommended)
#   0.5+       = adventurous; expect more RF3 fold failures
MPNN_TEMPERATURE = 0.25
RF3_NUM_STEPS          = 100  # ◆ 50 = fast draft, 100 = normal, 200 = production
RF3_GROUP_SIZE         = 10   # folds per RF3 array task — leave as is

# ===========================================================================
# ● PER ENZYME / cluster — queues and install paths
# ===========================================================================
QUEUE       = "gpua100"   # ● GPU queue for RFD3/MPNN/RF3 folding (gpua100 or gpuv100)
CPU_QUEUE   = "hpc"       # ● CPU queue for prep/launcher/scoring — NO GPU. Check `bqueues`.
CONDA_SH    = "/dtu/blackhole/00/c27666/miniforge3/etc/profile.d/conda.sh"      # ✗
PROTEIN_ENV = "/dtu/blackhole/00/c27666/miniforge3/envs/protein-design"        # ✗
RFD3_CKPT   = "/dtu/projects/dbl/foundry/ckpt/rfd3_latest.ckpt"                 # ✗
MPNN_CKPT   = "/dtu/projects/dbl/foundry/ckpt/ligandmpnn_v_32_010_25.pt"        # ✗
RF3_RELEASE = "/dtu/projects/dbl/rf3/release"                                   # ✗
RF3_CKPT    = "/dtu/projects/dbl/rf3/release/ckpt/rf3_latest.pt"                # ✗

# ---------------------------------------------------------------------------
# ✗ DON'T EDIT — derived output paths
# ---------------------------------------------------------------------------
if not YOUR_NAME or YOUR_NAME == "your_name":
    raise RuntimeError("Set YOUR_NAME in config.py before running.")

SHARED_ROOT = Path("/work3/s215098/BioBuilders2026")
if not (_SNAPSHOT_PATH and "WORK" in _overrides):
    WORK          = SHARED_ROOT / YOUR_NAME / EXPERIMENT
    CONFIGS_DIR   = WORK / "configs"
    SUBMIT_DIR    = WORK / "submit"
    LOGS_DIR      = WORK / "logs"
    CMDS_DIR      = WORK / "cmds"
    SCORES_DIR    = WORK / "scores"
    DIFFUSION_DIR = WORK / "diffusion_out"
    MPNN_DIR      = WORK / "mpnn_out"
    RF3_DIR       = WORK / "rf3_out"
    BEST_DIR      = WORK / "best_designs"

def make_workdirs():
    if not SUBSTRATE_SMILES and not SUBSTRATE_CCD:
        raise RuntimeError("Set SUBSTRATE_SMILES or SUBSTRATE_CCD in config.py.")
    for d in (CONFIGS_DIR, SUBMIT_DIR, LOGS_DIR, CMDS_DIR,
              SCORES_DIR, DIFFUSION_DIR, MPNN_DIR, RF3_DIR, BEST_DIR):
        d.mkdir(parents=True, exist_ok=True)
