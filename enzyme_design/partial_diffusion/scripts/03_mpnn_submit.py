#!/usr/bin/env python3
"""
Stage 2 — LigandMPNN: design sequences on each backbone.

Writes a .cmds file (one mpnn command per backbone) and an LSF array submit
script, then prints the bsub command.

Run after 02_rfd3_process.py:
  python scripts/03_mpnn_submit.py

After submitting, wait for the job (bstat), then run:
  python scripts/04_rf3_submit.py
"""
import sys
import glob
import json
import math
import os
import importlib
from pathlib import Path

_AA3TO1 = {"ALA":"A","ARG":"R","ASN":"N","ASP":"D","CYS":"C","GLN":"Q",
           "GLU":"E","GLY":"G","HIS":"H","ILE":"I","LEU":"L","LYS":"K",
           "MET":"M","PHE":"F","PRO":"P","SER":"S","THR":"T","TRP":"W",
           "TYR":"Y","VAL":"V"}

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
C = importlib.import_module(os.environ.get("PIPELINE_BASE_CONFIG", "partial_diffusion.config"))
sys.path.insert(0, str(C.LIB_ROOT))
import jupyter_utils

C.make_workdirs()

# Prefer the most-filtered tier available:
#   widened/  — passed 02b_caver_filter.py's channel-width check (cheap CAVER
#               gate; skip GPU on backbones that already collapsed)
#   passing/  — passed 02_rfd3_process.py's clash/chainbreak check
#   (root)    — neither filter ran
# 02b writes widened/ as a CHILD of whichever tier it read from — passing/
# widened/ normally, but plain widened/ if passing/ turned out empty (e.g.
# nothing survived the clash filter, so 02b fell back to reading DIFFUSION_DIR
# directly). Check both; only one can ever be populated.
widened = (sorted(glob.glob(str(C.DIFFUSION_DIR / "passing" / "widened" / "*.cif.gz"))) or
          sorted(glob.glob(str(C.DIFFUSION_DIR / "widened" / "*.cif.gz"))))
filtered = sorted(glob.glob(str(C.DIFFUSION_DIR / "passing" / "*.cif.gz")))
structures = widened or filtered or sorted(glob.glob(str(C.DIFFUSION_DIR / "*.cif.gz")))

if not structures:
    sys.exit(f"No .cif.gz backbones in {C.DIFFUSION_DIR} — run RFD3 first.")

tier = ("channel-width filtered" if widened else
        "clash/break-filtered" if filtered else
        "all — no filter applied")
print(f"Using {len(structures)} backbone(s) ({tier})")

# getattr, not C.MPNN_TEMPERATURE: the per-person config files in
# */configs/ predate this setting and must keep working unchanged. 0.1 is
# LigandMPNN's own default, so an old config behaves exactly as it did before.
temperature = getattr(C, "MPNN_TEMPERATURE", 0.1)
if temperature <= 0.1:
    print(f"  NOTE: MPNN temperature {temperature} is near-deterministic. With most "
          f"positions pinned, the free ones will get the same residue nearly every "
          f"time — expect duplicate sequences. Try 0.2–0.3 for real diversity.")

# ── channel widening by sequence: forbid bulky residues at SHRINK_RESIDUES ──
# Freeing a residue doesn't make MPNN choose something smaller — it usually
# keeps the native bulky sidechain, since that's what's well-packed. This
# forces the issue: at SHRINK_RESIDUES, the bulky types are off the table, so
# MPNN has to pick something small there. getattr, not C.SHRINK_RESIDUES: this
# predates most configs and must stay a no-op when absent.
shrink_residues  = list(getattr(C, "SHRINK_RESIDUES", None) or [])
omit_aa_shrink   = getattr(C, "OMIT_AA_AT_SHRINK",
                           ["PHE", "TRP", "TYR", "LEU", "MET", "ILE"])

if shrink_residues:
    flexible = set(getattr(C, "FLEXIBLE_RESIDUES", []))
    not_flexible = [r for r in shrink_residues if r not in flexible]
    if not_flexible:
        sys.exit(f"SHRINK_RESIDUES contains residues not in FLEXIBLE_RESIDUES: "
                 f"{not_flexible}. A fixed residue can't be redesigned, so "
                 f"constraining its allowed types does nothing except mask a "
                 f"config mistake — add them to FLEXIBLE_RESIDUES or remove "
                 f"them from SHRINK_RESIDUES.")
    # The exact bug found in a teammate's config: a residue listed in both
    # _CATALYTIC_PINS (meant to be protected) and SHRINK_RESIDUES silently
    # loses its pin (FIXED_ATOMS only applies to non-flexible residues — see
    # _build_fixed_atoms) AND gets its native type forbidden. Refuse outright
    # rather than let that combination run quietly.
    pinned = set(getattr(C, "_CATALYTIC_PINS", {}))
    catalytic_conflict = sorted(pinned & set(shrink_residues))
    if catalytic_conflict:
        sys.exit(f"SHRINK_RESIDUES overlaps _CATALYTIC_PINS at {catalytic_conflict} "
                 f"— these are marked catalytically important AND flexible, so the "
                 f"pin is silently ignored (FIXED_ATOMS skips flexible residues) "
                 f"while their native type is now forbidden. Remove them from one "
                 f"list or the other.")
    unknown_aa = [a for a in omit_aa_shrink if a not in _AA3TO1]
    if unknown_aa:
        sys.exit(f"OMIT_AA_AT_SHRINK has unrecognized 3-letter code(s): {unknown_aa}")
    # Values stay a LIST of 3-letter codes. Read from the installed package's
    # own validator (mpnn/utils/inference.py) rather than any external doc:
    #   line 1222: "omit_per_residue[{res_id}] must be a list"
    # Upstream LigandMPNN's public README documents a concatenated 1-letter
    # string ("ACDEFGH...") for a similarly-named flag — that is a DIFFERENT
    # tool from what is installed here, and following it produced the wrong
    # shape. Trust the installed source, not the README.
    omit_tokens = list(omit_aa_shrink)
    print(f"  Shrink residues           : {len(shrink_residues)} "
          f"(forbidding {'/'.join(omit_aa_shrink)} there)")

cmds_file = str(C.CMDS_DIR / "mpnn.cmds")
n_written = 0
with open(cmds_file, "w") as f:
    for structure in structures:
        bn = os.path.basename(structure).replace(".cif.gz", "")
        this_out = str(C.MPNN_DIR / bn)
        os.makedirs(this_out, exist_ok=True)

        # Confirm this backbone has a valid RFD3 sidecar JSON before using it.
        # If only CIFs were copied into passing/ (not the JSONs), also check
        # the parent diffusion_out/ directory.
        side_json = Path(structure.replace(".cif.gz", ".json"))
        if not side_json.exists():
            side_json = side_json.parent.parent / side_json.name
        if not side_json.exists():
            print(f"  [skip] no sidecar JSON for {bn}")
            continue

        # partial diffusion preserves residue numbering (no index remapping),
        # so pin catalytic residues directly by their input labels. This mpnn
        # build splits --fixed_residues on commas, so join with "," (a space
        # separator makes it read the whole list as one invalid residue ID).
        fixed_resis = ",".join(C.CATRES)

        fixed_flag = f'--fixed_residues "{fixed_resis}"' if fixed_resis else ""

        # INLINE JSON, not a file path. From the installed package's source:
        #   inference.py:649  "omit_per_residue": parse_json_like(args.omit_per_residue)
        #   inference.py:1222 "omit_per_residue[{res_id}] must be a list"
        # so the CLI value is parsed as JSON text and must yield
        # {"<chain><resnum>": ["PHE", "TRP", ...], ...}. Passing a file path
        # here fails silently-ish: the path is not valid JSON, parse_json_like
        # leaves it a plain string, and validation then reports the confusing
        # "omit_per_residue must be a dict."
        #
        # Single-quoted so the shell passes the JSON through as one argument —
        # these commands are written to a .cmds file and run via `eval`.
        omit_flag = ""
        if shrink_residues:
            omit_map = {f"A{r}": omit_tokens for r in shrink_residues}
            omit_flag = f"--omit_per_residue '{json.dumps(omit_map)}'"

        cmd = (
            f'mpnn --seed 42 --structure_path "{structure}" '
            f'--out_directory "{this_out}" '
            f'--batch_size {C.MPNN_BATCH_SIZE} '
            f'--number_of_batches {C.MPNN_NUMBER_OF_BATCHES} '
            f'--temperature {temperature} '
            f'--model_type ligand_mpnn '
            f'--checkpoint_path "{C.MPNN_CKPT}" '
            f'--is_legacy_weights True '
            # NOTE: --fixed_residues and --designed_chains are mutually exclusive
            # in LigandMPNN. We pin catalytic residues with --fixed_residues; the
            # only protein chain is A (HEM/NNBT are ligand context), so everything
            # else on chain A is designed automatically — no --designed_chains needed.
            + fixed_flag
            + (" " + omit_flag if omit_flag else "")
        ).rstrip()
        f.write(cmd + "\n")
        n_written += 1

if n_written == 0:
    sys.exit("No MPNN commands written — are sidecar JSONs present next to each .cif.gz?")

n_tasks = sum(1 for _ in open(cmds_file))
sub_script = jupyter_utils.make_sub_script(
    cmds_file,
    n_task=n_tasks,
    group_size=10,
    mem="10G",
    queue=C.QUEUE,
    job_name="mpnn",
    cores=4,
    time_limit="2:00",
    env=C.PROTEIN_ENV,
)

print(f"\n{n_tasks} MPNN command(s) -> {cmds_file}")
print(f"LSF submit script    -> {sub_script}")
print(f"\n--- SUMMARY ---")
print(f"  Backbones going into MPNN : {len(structures)}")
print(f"  Sequences per backbone    : {C.MPNN_BATCH_SIZE * C.MPNN_NUMBER_OF_BATCHES}")
print(f"  Sampling temperature      : {temperature}")
print(f"  Positions free to design  : {len(C.FLEXIBLE_RESIDUES) if hasattr(C, 'FLEXIBLE_RESIDUES') else '?'}"
      f"  ({len(C.CATRES)} pinned to native)")
print(f"  Total sequences expected  : {len(structures) * C.MPNN_BATCH_SIZE * C.MPNN_NUMBER_OF_BATCHES}")
print(f"  Output FASTAs will go to  : {C.MPNN_DIR}/<backbone>/")
print(f"\n--- SUBMIT ---")
print(f"  bsub < {sub_script}")
print(f"\nThen wait:  bstat")
print(f"Then check: ls {C.MPNN_DIR}/")
print(f"Then run:   python partial_diffusion/scripts/04_rf3_submit.py")
