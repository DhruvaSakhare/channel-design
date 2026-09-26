#!/usr/bin/env python3
"""
Stage 3 — RF3: build input JSONs and submit fold jobs.

Reads MPNN FASTA outputs, pairs each sequence with the substrate, writes
RF3 input JSONs, and submits an LSF array job.

Run after MPNN jobs finish:
  python scripts/04_rf3_submit.py

After submitting, wait for the job (bstat), then run:
  python scripts/05_rf3_score.py
"""
import sys
import glob
import json
import math
import os
import importlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
C = importlib.import_module(os.environ.get("PIPELINE_BASE_CONFIG", "partial_diffusion.config"))

C.make_workdirs()

# --- Build RF3 component entries ---
# Heme is always a CCD ligand
heme_entry = {"ccd_code": C.HEME_CCD}

# Substrate: prefer CCD code if given, otherwise SMILES
if C.SUBSTRATE_CCD:
    substrate_entry = {"ccd_code": C.SUBSTRATE_CCD}
elif C.SUBSTRATE_SMILES:
    substrate_entry = {"smiles": C.SUBSTRATE_SMILES}
else:
    sys.exit("Set SUBSTRATE_SMILES or SUBSTRATE_CCD in config.py")

# --- Parse MPNN FASTAs ---
def parse_fasta(path):
    header, chunks = None, []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if header is not None:
                    yield header, "".join(chunks)
                header, chunks = line[1:], []
            else:
                chunks.append(line)
        if header is not None:
            yield header, "".join(chunks)

fa_files = sorted(glob.glob(str(C.MPNN_DIR / "**" / "*.fa"), recursive=True))
if not fa_files:
    sys.exit(f"No FASTA files under {C.MPNN_DIR} — run MPNN first (03_mpnn_submit.py).")

rf3_json_dir = C.CONFIGS_DIR / "rf3"
rf3_json_dir.mkdir(exist_ok=True)

written = 0
for fa in fa_files:
    name = Path(fa).name.split(".")[0]  # backbone stem
    designs = []
    for i, (header, seq) in enumerate(parse_fasta(fa)):
        chain_a = seq.split(":", 1)[0]
        designs.append({
            "name": f"{name}_{i}",
            "components": [
                {"seq": chain_a, "chain_id": "A", **({"msa_path": C.NATIVE_MSA_PATH} if getattr(C, "NATIVE_MSA_PATH", "") else {})},
                heme_entry,        # B_1 in RF3 output
                substrate_entry,   # C_1 in RF3 output
            ],
        })
    if not designs:
        continue
    out = rf3_json_dir / f"{name}.json"
    with open(out, "w") as f:
        json.dump(designs, f, indent=2)
    written += 1

print(f"Wrote {written} RF3 input JSON(s) -> {rf3_json_dir}")

# --- Build RF3 .cmds ---
json_files = sorted(rf3_json_dir.glob("*.json"))
if not json_files:
    sys.exit("No RF3 JSONs found — check FASTA parsing above.")

cmds_path = C.CMDS_DIR / "rf3.cmds"
rf3_wrapper = C.LIB_ROOT / "rf3_wrapper.py"
lines = []
for jf in json_files:
    out_dir = C.RF3_DIR / jf.stem
    lines.append(
        f"python {rf3_wrapper} fold inference_engine=rf3 "
        f"inputs={jf} out_dir={out_dir} "
        f"ckpt_path={C.RF3_CKPT} "
        f"num_steps={C.RF3_NUM_STEPS} "
        f"annotate_b_factor_with_plddt=True "
        f"early_stopping_plddt_threshold=0"
    )
cmds_path.write_text("\n".join(lines) + "\n")

# --- Build LSF array script ---
n_arrays = math.ceil(len(lines) / C.RF3_GROUP_SIZE)
sub_path = C.SUBMIT_DIR / "rf3.sh"
script = f"""#!/bin/sh
#BSUB -q {C.QUEUE}
#BSUB -J rf3[1-{n_arrays}]
#BSUB -n 4
#BSUB -gpu "num=1:mode=exclusive_process"
#BSUB -W 2:00
#BSUB -R "rusage[mem=10GB]"
#BSUB -R "span[hosts=1]"
#BSUB -o {C.LOGS_DIR}/%J_%I.out
#BSUB -e {C.LOGS_DIR}/%J_%I.err

mkdir -p {C.LOGS_DIR}
module load cuda/12.4
source {C.RF3_RELEASE}/activate_env.sh
export DISABLE_CUEQUIVARIANCE=true

CMDS_FILE={cmds_path}
GROUP_SIZE={C.RF3_GROUP_SIZE}
START=$(( (LSB_JOBINDEX - 1) * GROUP_SIZE ))
END=$(( START + GROUP_SIZE ))
i=0
while IFS= read -r cmd; do
    if [ "$i" -ge "$START" ] && [ "$i" -lt "$END" ]; then
        # Skip this fold if its output directory already contains a CIF
        out_dir=$(echo "$cmd" | grep -oP 'out_dir=\\K\\S+')
        if [ -n "$out_dir" ] && find "$out_dir" -name "*.cif" -print -quit 2>/dev/null | grep -q .; then
            echo "Skipping task $i (outputs already in $out_dir)"
        else
            echo "Running task $i: $cmd"
            eval "$cmd"
        fi
    fi
    i=$((i+1))
done < "$CMDS_FILE"
echo "Done at $(date)"

# RF3/torch can orphan GPU worker processes after folding; they stay in this
# task's process group and keep it in RUN until wall-time. Kill everything in
# our process group except this shell (group membership survives orphaning),
# then exit cleanly so scoring (done() dependency) starts as soon as folding is done.
_PGID=$(ps -o pgid= -p $$ | tr -d ' ')
for _pid in $(pgrep -g "$_PGID" 2>/dev/null); do
    [ "$_pid" != "$$" ] && kill -9 "$_pid" 2>/dev/null
done
exit 0
"""

sub_path.write_text(script)
sub_path.chmod(0o755)
print(f"{len(lines)} fold job(s) in {n_arrays} array task(s)")
print(f"RF3 input JSONs   -> {rf3_json_dir}")
print(f"LSF submit script -> {sub_path}")
print(f"\n--- SUMMARY ---")
print(f"  Sequences to fold : {len(lines)}")
print(f"  Array tasks       : {n_arrays}  (up to {C.RF3_GROUP_SIZE} folds per task)")
print(f"  Folded CIFs will go to : {C.RF3_DIR}/<backbone>/")
print(f"  Score files        : {C.RF3_DIR}/<backbone>/*.score")
print(f"\n--- SUBMIT ---")
print(f"  bsub < {sub_path}")
print(f"\nThen wait:  bstat")
print(f"Then check: ls {C.RF3_DIR}/")
print(f"Then run:   python partial_diffusion/scripts/05_rf3_score.py")
