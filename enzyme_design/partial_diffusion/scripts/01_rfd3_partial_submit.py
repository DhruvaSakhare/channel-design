#!/usr/bin/env python3
"""
Stage 1 — RFD3 partial diffusion.

Writes the RFD3 input JSON and LSF submit script for partial diffusion.
The full enzyme structure is used as input. RFD3 adds PARTIAL_T steps of
noise and then denoises, holding FIXED_ATOMS and ligands anchored while
remodelling everything else.

Run from the partial_diffusion/ folder:
  python scripts/01_rfd3_partial_submit.py

After submitting, wait (bstat), then run:
  python scripts/02_rfd3_process.py
"""
import sys
import json
import os
import importlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
C = importlib.import_module(importlib.import_module("partial_diffusion").default_config())

C.make_workdirs()

# ── guard: a pinned residue that is also flexible gets NO pin ────────────────
# _build_fixed_atoms applies _CATALYTIC_PINS only to residues *not* in
# FLEXIBLE_RESIDUES ("... for r in _chain_resids(...) if r not in flex"), so a
# residue in both lists ends up with full backbone freedom in RFD3 — the exact
# opposite of what the annotation beside it says. The pin is dead code, and it
# looks like the opposite. This is the RFD3 stage, which is where that pin would
# have been honoured, so refuse here rather than discover it in the output.
#
# 03_mpnn_submit.py makes the same check against SHRINK_RESIDUES. Keep both:
# this one fires even on a config that sets no SHRINK_RESIDUES at all.
_pinned = set(getattr(C, "_CATALYTIC_PINS", {}))
_flex = set(getattr(C, "FLEXIBLE_RESIDUES", []))
_both = sorted(_pinned & _flex)
if _both:
    sys.exit(
        f"Residue(s) {_both} are in BOTH _CATALYTIC_PINS and FLEXIBLE_RESIDUES.\n"
        f"A flexible residue is skipped by _build_fixed_atoms, so the catalytic\n"
        f"pin on {_both} is silently ignored: RFD3 gets full backbone freedom\n"
        f"there, not the protected sidechain geometry the pin implies.\n"
        f"Decide which you meant:\n"
        f"  - keep the geometry  -> remove them from FLEXIBLE_RESIDUES\n"
        f"  - redesign them      -> remove them from _CATALYTIC_PINS\n"
        f"See KNOWN_ISSUES.md.")

# ── channel placeholder ──────────────────────────────────────────────────────
# If configured, merge the CAVER-derived tunnel placeholder into a copy of the
# input structure and hand it to RFD3 as extra fixed ligand context, so the
# denoiser packs around an open channel rather than collapsing into the void.
# All getattr, so config files predating this setting keep working unchanged.
rfd3_input   = C.INPUT_PDB
ligand_names = list(getattr(C, "RFD3_LIGAND_NAMES", None) or C.LIGAND_NAMES)
placeholder  = getattr(C, "CHANNEL_PLACEHOLDER", "")

if placeholder:
    sys.path.insert(0, str(C.LIB_ROOT))
    import caver_utils

    ph_path = Path(placeholder)
    if not ph_path.exists():
        sys.exit(f"CHANNEL_PLACEHOLDER not found: {ph_path}\n"
                 f"Generate it with:\n"
                 f"  python partial_diffusion/scripts/00_caver_channel.py {C.INPUT_PDB}")

    ph_resname = getattr(C, "CHANNEL_PLACEHOLDER_RESNAME", "TUN")
    merged = C.CONFIGS_DIR / f"{Path(C.INPUT_PDB).stem}_with_channel.pdb"
    caver_utils.append_placeholder_to_pdb(C.INPUT_PDB, ph_path, merged)
    rfd3_input = str(merged)
    if ph_resname not in ligand_names:
        ligand_names.append(ph_resname)
    n_dummy = sum(1 for ln in ph_path.read_text().splitlines() if ln.startswith("HETATM"))
    print(f"Channel placeholder : {ph_path}  ({n_dummy} atoms, resname {ph_resname})")
    print(f"Merged input        -> {merged}")

design_name = "partial_rfd3"
payload = {
    design_name: {
        "dialect":            2,
        "input":              rfd3_input,            # full enzyme structure
        "contig":             C.CONTIG,              # e.g. "A1-349" — whole chain
        "partial_t":          float(C.PARTIAL_T),    # Angstroms of noise (<=15 conservative, 20+ aggressive)
        "ligand":             ",".join(ligand_names),  # comma-separated residue names
        "allow_ligand_on_existing_chain": True,
        "select_fixed_atoms": C.FIXED_ATOMS,         # proximal residue(s) fully pinned
    }
}

rfd3_json = C.CONFIGS_DIR / "rfd3_partial_input.json"
with open(rfd3_json, "w") as f:
    json.dump(payload, f, indent=2)
print(f"RFD3 input JSON  -> {rfd3_json}")

n_expected = C.RFD3_BATCH_SIZE * C.RFD3_N_BATCHES
script_path = C.SUBMIT_DIR / "rfd3_partial.sh"
script = f"""#!/bin/sh
#BSUB -q {C.QUEUE}
#BSUB -J rfd3_partial
#BSUB -n 4
#BSUB -gpu "num=1:mode=exclusive_process"
#BSUB -W 6:00
#BSUB -R "rusage[mem=10GB]"
#BSUB -R "span[hosts=1]"
#BSUB -o {C.LOGS_DIR}/%J.out
#BSUB -e {C.LOGS_DIR}/%J.err

mkdir -p {C.LOGS_DIR} {C.DIFFUSION_DIR}

# Skip if all expected backbone files already exist (exit 0 so the next
# stage's done() dependency still fires and the pipeline keeps moving).
FOUND=$(find {C.DIFFUSION_DIR} -maxdepth 1 -name "*.cif.gz" | wc -l)
if [ "$FOUND" -ge {n_expected} ]; then
    echo "RFD3 outputs already present ($FOUND >= {n_expected}) — skipping."
    exit 0
fi

module load cuda/12.4
source {C.CONDA_SH}
conda activate {C.PROTEIN_ENV}

export DISABLE_CUEQUIVARIANCE=true
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

rfd3 design \\
    out_dir="{C.DIFFUSION_DIR}" \\
    inputs="{rfd3_json}" \\
    ckpt_path="{C.RFD3_CKPT}" \\
    diffusion_batch_size={C.RFD3_BATCH_SIZE} \\
    n_batches={C.RFD3_N_BATCHES} \\
    low_memory_mode=True

echo "RFD3 partial diffusion done at $(date)"

# rfd3/torch can orphan GPU worker processes after it returns; they stay in this
# job's process group and keep LSF in RUN until wall-time. Kill everything in
# our process group except this shell (group membership survives orphaning),
# then exit cleanly so the next stage's done() dependency fires right away.
_PGID=$(ps -o pgid= -p $$ | tr -d ' ')
for _pid in $(pgrep -g "$_PGID" 2>/dev/null); do
    [ "$_pid" != "$$" ] && kill -9 "$_pid" 2>/dev/null
done
exit 0
"""

with open(script_path, "w") as f:
    f.write(script)
script_path.chmod(0o755)

print(f"RFD3 input JSON   -> {rfd3_json}")
print(f"LSF submit script -> {script_path}")
print(f"\n--- SUMMARY ---")
print(f"  Input PDB      : {rfd3_input}")
print(f"  Contig         : {C.CONTIG}")
print(f"  Noise level    : {C.PARTIAL_T} Å  (partial_t)")
print(f"  Ligands fixed  : {', '.join(ligand_names)}")
print(f"  Atoms pinned   : {C.FIXED_ATOMS}")
print(f"  Backbones      : {C.RFD3_BATCH_SIZE} per batch × {C.RFD3_N_BATCHES} batch(es) = {C.RFD3_BATCH_SIZE * C.RFD3_N_BATCHES} total")
print(f"  Outputs will go to : {C.DIFFUSION_DIR}/")
print(f"\n--- SUBMIT ---")
print(f"  bsub < {script_path}")
print(f"\nThen wait:  bstat")
print(f"Then check: ls {C.DIFFUSION_DIR}/")
print(f"Then run:   python partial_diffusion/scripts/02_rfd3_process.py")
