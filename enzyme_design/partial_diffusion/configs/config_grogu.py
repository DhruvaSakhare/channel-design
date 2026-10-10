"""
config_template.py — partial diffusion pipeline, Gogru tunnel engineering.

Copy this to `config.py`, edit the tagged sections, then run:
    python partial_diffusion/scripts/00_submit_all.py

WHAT THIS PIPELINE DOES (partial diffusion + targeted remodel):
  1. RFD3   : takes your crystal structure, lets ONLY the residues you list in
              FLEXIBLE_RESIDUES move, and denoises them → new channel shapes.
  2. MPNN   : designs sequences, keeping the native sequence everywhere EXCEPT
              the flexible residues → resizes the channel lining.
  3. RF3    : folds every design + substrate and scores fold/placement quality.
  4. score  : ranks designs; the good ones land in <WORK>/best_designs/.
  Then YOU filter the winners by tunnel geometry (CAVER) for your hypothesis.

THE CENTRAL IDEA — "keep most fixed, change only the channel":
  You edit ONE list, FLEXIBLE_RESIDUES. Everything NOT in it is held rigid
  (backbone pinned in RFD3) and native (sequence kept in MPNN). Everything IN it
  is free to move and be redesigned. CATRES and FIXED_ATOMS are built for you.

Tags below:  ★ EVERY RUN   ◆ PER EXPERIMENT   ● PER ENZYME   ✗ DON'T EDIT
"""
import os
from pathlib import Path

# ===========================================================================
# ★ EVERY RUN — who you are and a unique name for this run
# ===========================================================================
YOUR_NAME  = "example"                       # ★ your first name, lowercase
EXPERIMENT = "gogru_upo_tunnel_conservative_01"  # ★ UNIQUE per run — bump the
                                              #    number or name each time, or a
                                              #    re-run will just resume the old one

# ===========================================================================
# ● PER ENZYME — input structure and ligands (only change for a new enzyme)
# ===========================================================================
PIPELINE_ROOT = Path(__file__).resolve().parents[1]
LIB_ROOT      = PIPELINE_ROOT.parent / "lib"

# The FULL enzyme structure, already prepped: heme on chain B, substrate on
# chain C, unique substrate atom names. (Use fix_pdb_chains.py if it isn't.)
INPUT_PDB = str(PIPELINE_ROOT.parent / "examples" / "GroGu_prepped.pdb")  # ●

HEME_NAME      = "HEM"    # ● heme residue name as it appears in the PDB
SUBSTRATE_NAME = "UNL"    # ● substrate residue name in the PDB
LIGAND_NAMES   = [HEME_NAME, SUBSTRATE_NAME]   # heme first — leave as is

# The MSA RF3 folds designs against. Build it ONCE per enzyme with
#     python partial_diffusion/scripts/00_make_msa.py
# which writes <pdb_stem>_A.a3m.gz next to your structure — found automatically
# by the lines below, so a new enzyme needs no edit here. The search looks
# beside INPUT_PDB first, then in inputs/, so it works whether your structure
# is your own (inputs/) or one of the bundled examples (examples/).
# Set an explicit path to override.
#
# Empty ("" — i.e. no MSA file present) means RF3 folds single-sequence. That
# is a legitimate choice, but pLDDT runs markedly lower, so drop PLDDT_CUT to
# ~0.70 or the gate will reject nearly every design for the wrong reason.
_msa_name       = f"{Path(INPUT_PDB).stem}_A.a3m.gz"
_msa_candidates = [Path(INPUT_PDB).parent / _msa_name,
                   PIPELINE_ROOT.parent / "examples" / _msa_name]
NATIVE_MSA_PATH = next((str(p) for p in _msa_candidates if p.exists()), "")   # ●

# ===========================================================================
# ◆ PER EXPERIMENT — THE MAIN KNOB: which residues are allowed to change
# ===========================================================================
# Residue numbers (chain A) that RFD3 may MOVE and MPNN may REDESIGN. Everything
# else is frozen at the crystal structure + native sequence. This is how you
# target a region (here: the substrate channel) without disturbing the fold.
# Widen the entrance/middle → list the channel-lining residues that make it narrow.
#FLEXIBLE_RESIDUES = [                          # ◆ edit this to target a region
 #   E74, A76, T77, F80, V81, F125, F195, T196,  #selected by asking claude and then visually inspecting, all in the tunnel
  #  A199, E200, F203, S244, T245, E246, F282, 
   # G319, I320, D322, A323                                  
#]
FLEXIBLE_RESIDUES = [
    74, 76, 77, 80, 81, 125, 195, 196,   # E74 A76 T77 F80 V81 F125 F195 T196 — tunnel
]
# ● PER ENZYME — catalytic / structural residues that are held rigid get EXTRA
# sidechain atoms pinned (not just backbone) so active-site geometry is preserved.
# Keys are residue numbers; values are the atom names to pin. Backbone (N,CA,C,O)
# is included here; the extra atoms lock sidechain orientation. Never put a
# FLEXIBLE residue in here. If RFD3 errors on a big FIXED_ATOMS dict, simplify all
# values to "CA" (lightest pin) or reduce this dict to just residue 52.
_CATALYTIC_PINS = {                            # ALL BELLOW were gotten from Claude then confirmed by Henrique by looking in the literary source (here: https://advanced.onlinelibrary.wiley.com/doi/10.1002/adsc.70432)
    40:  "N,CA,C,O,CB,SG",  #Cys40 — the proximal/axial heme thiolate ligand, within the PCP motif (Pro39-Cys40-Pro41)
    39:  "N,CA,C,O,CB,CG,CD",     #the proximal/axial heme thiolate ligand, within the PCP motif (Pro39-Cys40-Pro41)
    41: "N,CA,C,O,CB,CG,CD",      #the proximal/axial heme thiolate ligand, within the PCP motif (Pro39-Cys40-Pro41)
    200: "N,CA,C,O,CB,CG,CD,OE1,OE2",     #Glu200 — the acid–base catalyst that deprotonates/reprotonates H₂O₂ during heterolytic O–O cleavage.
    193: "N,CA,C,O,CB,CG,CD,NE,CZ,NH1,NH2",      #Arg193 — the partner in the acid–base pair required for H₂O₂ cleavage, acting as charge stabilizer for the developing negative charge on Glu200. Note the numbering: Grogu runs +4 relative to AaeUPO, where these are the canonical Glu196/Arg189. 
    126: "N,CA,C,O,CB,CG,CD,OE1,OE2",      # The EGD motif (AaeUPO Glu122-Gly123-Asp124) — this is the magnesium-binding motif, and Grogu does carry a structural Mg²⁺</cite>. Applying the +4 offset puts it near E126-G127-D128 in Grogu, but I'd verify that on the actual sequence rather than take my arithmetic on faith. The Mg²⁺ is structural, not catalytic, but it orders the heme propionate environment.
    127: "N,CA,C,O",   # The EGD motif (AaeUPO Glu122-Gly123-Asp124) — this is the magnesium-binding motif, and Grogu does carry a structural Mg²⁺</cite>. Applying the +4 offset puts it near E126-G127-D128 in Grogu, but I'd verify that on the actual sequence rather than take my arithmetic on faith. The Mg²⁺ is structural, not catalytic, but it orders the heme propionate environment.
    128: "N,CA,C,O,CB,CG,OD1,OD2",   # The EGD motif (AaeUPO Glu122-Gly123-Asp124) — this is the magnesium-binding motif, and Grogu does carry a structural Mg²⁺</cite>. Applying the +4 offset puts it near E126-G127-D128 in Grogu, but I'd verify that on the actual sequence rather than take my arithmetic on faith. The Mg²⁺ is structural, not catalytic, but it orders the heme propionate environment.
    130:  "N,CA,C,O,CB,OG",                # EGD motif? Henrique added this based on 9RG5 structure
    283: "N,CA,C,O,CB,SG",   #the intramolecular C-terminal disulfide bridge conserved across long UPOs. Breaking it will cost you stability, and probably the pH 3–9 tolerance that makes this enzyme interesting
    325: "N,CA,C,O,CB,SG",   #the intramolecular C-terminal disulfide bridge conserved across long UPOs. Breaking it will cost you stability, and probably the pH 3–9 tolerance that makes this enzyme interesting
    73: "N,CA,C,O,CB,CG,SD,CE",   # selective phe (in gogru this one is met) triad maybe remove in agressive
    #125: "N,CA,C,O,CB,CG,CD1,CD2,CE1,CE2,CZ",   # selective phe triad maybe remove in agressive
    203: "N,CA,C,O,CB,CG,CD1,CD2,CE1,CE2,CZ",                # selective phe triad maybe remove in agressive
}

# ◆ PER EXPERIMENT — how aggressive the remodel is
# PARTIAL_T = amount of noise (Å) added to the FLEXIBLE residues before denoising.
#   3–5  = very gentle: shapes stay close to native, low risk, modest widening
#   8–12 = more backbone freedom: bigger changes, lower pass yield
# Bigger is NOT better — partial diffusion stays near the input by design, so
# real widening also comes from MPNN shrinking the lining (sequence lever).
PARTIAL_T = 10  # ◆ Å

# ◆ PER EXPERIMENT — how many backbones to generate (total = BATCH_SIZE × N_BATCHES)
RFD3_BATCH_SIZE = 10   # backbones per GPU call
RFD3_N_BATCHES  = 10   # ◆ 10 → 100 backbones. Use 1 for a quick smoke test.

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
MPNN_NUMBER_OF_BATCHES = 10    # ◆ × above = sequences per backbone
RF3_NUM_STEPS          = 100  # ◆ 50 = fast draft, 100 = normal, 200 = production
RF3_GROUP_SIZE         = 10   # folds per RF3 array task — leave as is

# ===========================================================================
# ✗ THE MACHINE LAYER — imported from site.py, not set here
# ===========================================================================
# Queue names are NOT here. They used to be, as two literals that shadowed
# site.py's -- so PIPELINE_QUEUE resolved correctly in site.py, was never
# imported by anything, and the config literal won silently. A run would
# print the queue it was being overridden to and submit to the other one.
#
#   PIPELINE_QUEUE=gpuv100 python partial_diffusion/scripts/00_submit_all.py
#   python partial_diffusion/scripts/00_submit_all.py --queue gpuv100
#
# Install paths, checkpoints and queue names live in site.py, not here --
# an experiment is portable, a filesystem is not. Override from the
# environment or the CLI (see envs/design.md), never by editing this.  # ✗
from partial_diffusion.site import (  # noqa: E402
    CONDA_SH, CPU_QUEUE, MPNN_CKPT, PROTEIN_ENV, QUEUE, RF3_CKPT, RF3_RELEASE,
    RFD3_CKPT, SHARED_ROOT,
)

# The run snapshot was applied ABOVE this import, so the two names that import
# brings in would be reset to the machine default here -- and a stage script
# launched as its own process would submit to a different queue than the run
# that launched it, splitting one experiment across two queues with nothing
# saying so. For a run in flight the snapshot is the truth; re-apply it.
if _SNAPSHOT_PATH:
    QUEUE     = _overrides.get("QUEUE", QUEUE)
    CPU_QUEUE = _overrides.get("CPU_QUEUE", CPU_QUEUE)

# ---------------------------------------------------------------------------
# ✗ DON'T EDIT — derived output paths
# ---------------------------------------------------------------------------
if not YOUR_NAME or YOUR_NAME == "your_name":
    raise RuntimeError("Set YOUR_NAME in config.py before running.")

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
