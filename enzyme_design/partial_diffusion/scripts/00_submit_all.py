#!/usr/bin/env python3
"""
00_submit_all.py — submit the entire partial diffusion pipeline in one go.

Chains all stages using LSF job dependencies. RF3 runs as a parallel array
job so 1000 designs fold simultaneously rather than sequentially.

Run from enzyme_design_hpc/:
  python partial_diffusion/scripts/00_submit_all.py

To run a different config without needing write access to config.py (e.g.
someone else's config.py isn't yours to overwrite), set PIPELINE_BASE_CONFIG
— same mechanism 00_make_msa.py / config_local.py already use:
  export PIPELINE_BASE_CONFIG=partial_diffusion.dhruva_configs.config_smoketest
  python partial_diffusion/scripts/00_submit_all.py

Monitor with:  bstat  or  bjobs -r
Final outputs: <WORK>/best_designs/
"""
import sys
import subprocess
import re
import json
import os
import argparse
import importlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
BASE_CONFIG = importlib.import_module("partial_diffusion").default_config()
C = importlib.import_module(BASE_CONFIG)

PIPELINE_ROOT = Path(__file__).resolve().parents[2]


def parse_args():
    p = argparse.ArgumentParser(
        description="Submit the partial diffusion pipeline. CLI flags override "
                     "config.py for this run only — safe to launch several "
                     "experiments back to back without them interfering."
    )
    p.add_argument("--experiment", default=None, help="Override EXPERIMENT (output folder name)")
    p.add_argument("--partial_t", type=float, default=None, help="Override PARTIAL_T")
    p.add_argument("--contig", default=None, help="Override CONTIG")
    p.add_argument("--n_batches", type=int, default=None, help="Override RFD3_N_BATCHES")
    p.add_argument("--queue", default=None,
                   help="Override the GPU queue for this run (RFD3, MPNN, RF3 "
                        "folding). Beats PIPELINE_QUEUE, which beats site.py's "
                        "default. `bqueues` lists what you have.")
    p.add_argument("--cpu-queue", default=None,
                   help="Override the CPU queue for this run (prep, the CAVER "
                        "gate, scoring -- no GPU). Beats PIPELINE_CPU_QUEUE.")
    p.add_argument("--pilot", action="store_true",
                   help="Probe run: ONE backbone, through RFD3 and the CPU CAVER "
                        "gate, then stop before MPNN and RF3 -- i.e. the same "
                        "stages as `run_local.py --stages prep-caver_filter`. Use "
                        "it to tune the config against the channel before spending "
                        "GPU. If RFD3 has already squeezed the channel shut, no "
                        "sequence design will reopen it. Measure the result with "
                        "08_probe_channel.py, change the config, repeat. Promote to "
                        "a full run (no --pilot) once the backbone opens.")
    p.add_argument("--dry-run", action="store_true",
                   help="Write every submit script and print the bsub command for "
                        "each stage, but submit nothing. Use it to read exactly "
                        "what would run, and to confirm the stage chain, before "
                        "spending queue time. The scripts land in <WORK>/submit/ "
                        "so you can inspect them.")
    p.add_argument("--flexible", default=None,
                   help="Override FLEXIBLE_RESIDUES for this run: either a comma-separated "
                        "list (\"207,208,209\") or the path to a *_flex.json from "
                        "00_caver_channel.py. CATRES and FIXED_ATOMS are rebuilt from it, "
                        "so RFD3's pins and MPNN's fixed positions stay consistent.")
    p.add_argument("--placeholder", default=None,
                   help="Override CHANNEL_PLACEHOLDER: path to a *_channel.pdb, or "
                        "\"none\" to switch it off for this run.")
    p.add_argument("--mpnn-temp", type=float, default=None,
                   help="Override MPNN_TEMPERATURE (LigandMPNN default 0.1 is "
                        "near-argmax; 0.2-0.3 gives real sequence diversity)")
    p.add_argument("--auto-msa", action="store_true",
                   help="if the native MSA is missing, build it here on the login "
                        "node before queueing anything (may query the public "
                        "ColabFold server — takes a few minutes)")
    p.add_argument("--msa-backend", default="auto", choices=("auto", "remote", "local"),
                   help="backend for --auto-msa (default auto)")
    p.add_argument("--msa-db", default=None,
                   help="ColabFold database dir, for --msa-backend local")
    return p.parse_args()


def expected_msa_path():
    """Same rule config.py's own auto-detect and run_local.py use.

    NOTE: this module's PIPELINE_ROOT (line 33) is already the repo root
    (Path(__file__).resolve().parents[2] from scripts/00_submit_all.py) —
    unlike config.py's own PIPELINE_ROOT, which is partial_diffusion/ and
    needs .parent to reach the repo root. Do NOT add .parent here too.
    """
    return PIPELINE_ROOT / "inputs" / f"{Path(C.INPUT_PDB).stem}_A.a3m.gz"


def ensure_msa(args):
    """Build the native MSA now, on the login node, if requested and missing.

    Compute nodes on the GPU/CPU queues don't reliably have internet access,
    so this can't be queued as an LSF job — it has to happen here, before
    anything is submitted, same as the manual `00_make_msa.py` step it
    replaces.
    """
    existing = Path(C.NATIVE_MSA_PATH) if C.NATIVE_MSA_PATH else None
    expected = expected_msa_path()

    if existing and existing.exists():
        print(f"  [0] MSA               present ({existing})")
        return
    if expected.exists():
        C.NATIVE_MSA_PATH = str(expected)
        print(f"  [0] MSA               found ({expected})")
        return

    if not args.auto_msa:
        print("  [0] MSA               none set — RF3 will fold single-sequence "
              "(pass --auto-msa to build one automatically)")
        return

    print("  [0] MSA               building (querying public ColabFold server, "
          "this can take a few minutes)...")
    cmd = [
        sys.executable, str(PIPELINE_ROOT / "partial_diffusion/scripts/00_make_msa.py"),
        "--pdb", C.INPUT_PDB, "--chain", "A",
        "--out", str(expected), "--backend", args.msa_backend,
    ]
    if args.msa_db:
        cmd += ["--db", args.msa_db]
    if DRY_RUN:
        print(f"      [dry-run] {' '.join(cmd)}")
        print("      [dry-run] (would build the MSA; needs network)")
        return
    subprocess.run(cmd, check=True)
    C.NATIVE_MSA_PATH = str(expected)
    print(f"  [0] MSA               built -> {expected}")


# Set from --dry-run in main(). A module-level flag rather than a parameter
# threaded through five call sites, because submit() is called from deep inside
# the stage logic and the alternative is plumbing a boolean through everything.
DRY_RUN = False
_DRY_JOB = 0


def submit(script_path):
    """bsub a script and return its job ID.

    Under --dry-run, print what would be submitted and hand back a fake job id
    so the dependency chain still prints correctly, then submit nothing.
    """
    global _DRY_JOB
    if DRY_RUN:
        _DRY_JOB += 1
        fake = f"DRY{_DRY_JOB}"
        print(f"      [dry-run] WOULD SUBMIT: bsub < {script_path}")
        return fake

    out = subprocess.run(
        f"bsub < {script_path}", shell=True, capture_output=True, text=True
    )
    if out.returncode != 0:
        print(f"bsub failed:\n{out.stderr}")
        sys.exit(1)
    m = re.search(r"Job <(\d+)>", out.stdout)
    if not m:
        print(f"Could not parse job ID from: {out.stdout}")
        sys.exit(1)
    return m.group(1)


def write_script(name, wall, body, dep_id=None, gpu=True, cores=4, mem="10GB", snapshot_path=None):
    path = C.SUBMIT_DIR / f"{name}.sh"
    # GPU stages go to the GPU queue; CPU-only stages go to CPU_QUEUE and request
    # NO GPU (reserving a GPU for a non-GPU job is against HPC policy).
    queue = C.QUEUE if gpu else C.CPU_QUEUE
    # Use ended() not done(): on the DTU GPU queue a job that grabs a GPU and
    # exits quickly doesn't release — it hangs until wall-time and is killed by
    # TERM_RUNLIMIT, which is NOT a clean exit, so done() would never fire.
    # ended() fires on any termination (clean or killed), and the per-stage skip
    # guards make re-entry safe, so the chain always advances.
    dep  = f'#BSUB -w "ended({dep_id})"' if dep_id else ""
    gpu_lines = (
        '#BSUB -gpu "num=1:mode=exclusive_process"\n'
        "export DISABLE_CUEQUIVARIANCE=true\n"
        "export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True\n"
    ) if gpu else ""
    cuda_line = "module load cuda/12.4\n" if gpu else ""
    # CONDA_SH and PROTEIN_ENV empty is the documented "the environment is
    # already active" case -- a uv or module-based install with no conda at
    # all. Emitting the lines anyway produced `source` with no argument (an
    # error) followed by `conda activate` with no argument, which activates
    # *base* and so quietly replaces the interpreter the run was set up with.
    # A worse failure than crashing, because the job still exits 0.
    env_lines = ""
    if C.CONDA_SH:
        env_lines += f"source {C.CONDA_SH}\n"
    if C.PROTEIN_ENV:
        env_lines += f"conda activate {C.PROTEIN_ENV}\n"
    snapshot_line = (f"export PIPELINE_RUN_CONFIG={snapshot_path}\n"
                      f"export PIPELINE_BASE_CONFIG={BASE_CONFIG}\n") if snapshot_path else ""
    path.write_text(f"""#!/bin/sh
#BSUB -q {queue}
#BSUB -J {name}
#BSUB -n {cores}
#BSUB -W {wall}
#BSUB -R "rusage[mem={mem}]"
#BSUB -R "span[hosts=1]"
{dep}
#BSUB -o {C.LOGS_DIR}/{name}_%J.out
#BSUB -e {C.LOGS_DIR}/{name}_%J.err

mkdir -p {C.LOGS_DIR}
{cuda_line}{env_lines}# `python` does not exist on every system where `python3` does. Resolve it
# once, after any activation above, rather than hoping per command.
PY="$(command -v python || command -v python3)"
{gpu_lines}{snapshot_line}cd {PIPELINE_ROOT}
{body}
echo "Done at $(date)"

# PyTorch tools (LigandMPNN etc.) spawn dataloader worker processes that get
# orphaned when the main command exits but stay in this job's process group —
# LSF then keeps the job in RUN until wall-time instead of releasing it. Kill
# every process in our process group (grandchildren included; group membership
# survives orphaning) except this shell, then exit 0 cleanly so the next
# stage's done() dependency still fires.
_PGID=$(ps -o pgid= -p $$ | tr -d ' ')
for _pid in $(pgrep -g "$_PGID" 2>/dev/null); do
    [ "$_pid" != "$$" ] && kill -9 "$_pid" 2>/dev/null
done
exit 0
""")
    path.chmod(0o755)
    return path


def main():
    args = parse_args()

    # A pilot with no explicit name gets a fresh numbered one. Reusing a name
    # would make the RFD3 stage skip (its outputs already exist) and the probe
    # would then measure the PREVIOUS backbone — silently reporting that your
    # config change did nothing.
    if args.pilot and args.experiment is None:
        n = 1
        while (C.SHARED_ROOT / C.YOUR_NAME / f"probe_{n:03d}").exists():
            n += 1
        args.experiment = f"probe_{n:03d}"
        print(f"  Pilot experiment name: {args.experiment}")

    # Apply CLI overrides to the in-process config so this run's prints and
    # the snapshot below reflect the override, without touching config.py.
    if args.experiment is not None:
        C.EXPERIMENT = args.experiment
        C.WORK          = C.SHARED_ROOT / C.YOUR_NAME / C.EXPERIMENT
        C.CONFIGS_DIR   = C.WORK / "configs"
        C.SUBMIT_DIR    = C.WORK / "submit"
        C.LOGS_DIR      = C.WORK / "logs"
        C.CMDS_DIR      = C.WORK / "cmds"
        C.SCORES_DIR    = C.WORK / "scores"
        C.DIFFUSION_DIR = C.WORK / "diffusion_out"
        C.MPNN_DIR      = C.WORK / "mpnn_out"
        C.RF3_DIR       = C.WORK / "rf3_out"
        C.BEST_DIR      = C.WORK / "best_designs"
    if args.partial_t is not None:
        C.PARTIAL_T = args.partial_t
    if args.contig is not None:
        C.CONTIG = args.contig
    if args.n_batches is not None:
        C.RFD3_N_BATCHES = args.n_batches
    # Queues come from site.py via the config's import. A CLI override is the
    # right tool for "this one run, on the other queue" -- it is the case that
    # sent somebody editing a config file that tells them not to.
    if args.queue is not None:
        C.QUEUE = args.queue
    if args.cpu_queue is not None:
        C.CPU_QUEUE = args.cpu_queue
    if args.pilot:
        C.RFD3_BATCH_SIZE = 1
        C.RFD3_N_BATCHES = 1
    if args.mpnn_temp is not None:
        C.MPNN_TEMPERATURE = args.mpnn_temp
    if args.placeholder is not None:
        C.CHANNEL_PLACEHOLDER = ("" if args.placeholder.lower() in ("none", "off", "")
                                 else str(Path(args.placeholder).resolve()))
    if args.flexible is not None:
        # Accept either a *_flex.json (what 00_caver_channel.py writes) or a
        # bare comma-separated list.
        src = Path(args.flexible)
        if src.suffix == ".json" and src.exists():
            C.FLEXIBLE_RESIDUES = json.loads(src.read_text())["flexible_residues"]
        else:
            C.FLEXIBLE_RESIDUES = [int(x) for x in args.flexible.replace(" ", "").split(",") if x]
        # CATRES / FIXED_ATOMS are DERIVED from FLEXIBLE_RESIDUES at import time,
        # so they must be rebuilt or RFD3 would pin the very residues we just
        # freed (and MPNN would still hold their sequence native).
        C.CATRES      = C._build_catres(C.INPUT_PDB, C.FLEXIBLE_RESIDUES)
        C.FIXED_ATOMS = C._build_fixed_atoms(C.INPUT_PDB, C.FLEXIBLE_RESIDUES)

    # Queue names have no default -- see site.py. Check before anything is
    # written or submitted, and name the two queues separately, because
    # getting CPU_QUEUE wrong is the mistake that reserves a GPU for the CAVER
    # gate. A --dry-run is still allowed to proceed: reading the chain you
    # would submit is useful before you know which queue you want.
    missing = [label for label, value, flag, var in (
        ("GPU", C.QUEUE,     "--queue",     "PIPELINE_QUEUE"),
        ("CPU", C.CPU_QUEUE, "--cpu-queue", "PIPELINE_CPU_QUEUE"),
    ) if not value]
    if missing and not args.dry_run:
        print("\nNo {} queue set, and there is no default -- queue names are "
              "specific to your cluster.\n".format(" or ".join(missing)))
        print("  List yours:   bqueues")
        print("  This run:     --queue <gpu-queue> --cpu-queue <cpu-queue>")
        print("  This shell:   export PIPELINE_QUEUE=... PIPELINE_CPU_QUEUE=...")
        print("  Permanently:  put both in envs/site.env  (setup.sh reads it)\n")
        print("The CPU queue is for prep, the CAVER gate and scoring. Sending")
        print("those to a GPU queue reserves a GPU to do no GPU work.\n")
        print("On DTU HPC: --queue gpuv100 --cpu-queue hpc  (or gpua100, which")
        print("is usually the more contended of the two).\n")
        sys.exit(2)

    ensure_msa(args)

    global DRY_RUN
    DRY_RUN = args.dry_run
    if DRY_RUN:
        print("\n*** DRY RUN — writing submit scripts, submitting nothing ***\n")

    C.make_workdirs()

    # Freeze the resolved settings for this run into a snapshot file, and
    # point every script this run launches (now and via queued LSF jobs) at
    # it via PIPELINE_RUN_CONFIG. This means editing config.py afterwards
    # (e.g. to launch a second, different experiment) cannot corrupt this
    # run, even if its later stages don't execute until hours from now.
    snapshot = {
        "EXPERIMENT": C.EXPERIMENT,
        "PARTIAL_T": C.PARTIAL_T,
        "CONTIG": C.CONTIG,
        "INPUT_PDB": C.INPUT_PDB,
        "NATIVE_MSA_PATH": C.NATIVE_MSA_PATH,
        "CATRES": C.CATRES,
        "FIXED_ATOMS": C.FIXED_ATOMS,
        "SUBSTRATE_SMILES": C.SUBSTRATE_SMILES,
        "SUBSTRATE_CCD": C.SUBSTRATE_CCD,
        "RFD3_BATCH_SIZE": C.RFD3_BATCH_SIZE,
        "RFD3_N_BATCHES": C.RFD3_N_BATCHES,
        "MPNN_BATCH_SIZE": C.MPNN_BATCH_SIZE,
        "MPNN_NUMBER_OF_BATCHES": C.MPNN_NUMBER_OF_BATCHES,
        # getattr: the per-person config files predate these knobs. The
        # defaults reproduce the old behaviour exactly (0.1 is LigandMPNN's
        # own default; no placeholder means the original RFD3 input).
        "MPNN_TEMPERATURE": getattr(C, "MPNN_TEMPERATURE", 0.1),
        "CHANNEL_PLACEHOLDER": getattr(C, "CHANNEL_PLACEHOLDER", ""),
        "CHANNEL_PLACEHOLDER_RESNAME": getattr(C, "CHANNEL_PLACEHOLDER_RESNAME", "XE"),
        "RFD3_LIGAND_NAMES": getattr(C, "RFD3_LIGAND_NAMES", None),
        "SHRINK_RESIDUES": getattr(C, "SHRINK_RESIDUES", None),
        "OMIT_AA_AT_SHRINK": getattr(C, "OMIT_AA_AT_SHRINK",
                                     ["PHE", "TRP", "TYR", "LEU", "MET", "ILE"]),
        "RF3_NUM_STEPS": C.RF3_NUM_STEPS,
        "RF3_GROUP_SIZE": C.RF3_GROUP_SIZE,
        "QUEUE": C.QUEUE,
        "CPU_QUEUE": C.CPU_QUEUE,
        "PLDDT_CUT": C.PLDDT_CUT,
        "PAE_CUT": C.PAE_CUT,
        "IPSAE_CUT": C.IPSAE_CUT,
        "WORK": str(C.WORK),
        "CONFIGS_DIR": str(C.CONFIGS_DIR),
        "SUBMIT_DIR": str(C.SUBMIT_DIR),
        "LOGS_DIR": str(C.LOGS_DIR),
        "CMDS_DIR": str(C.CMDS_DIR),
        "SCORES_DIR": str(C.SCORES_DIR),
        "DIFFUSION_DIR": str(C.DIFFUSION_DIR),
        "MPNN_DIR": str(C.MPNN_DIR),
        "RF3_DIR": str(C.RF3_DIR),
        "BEST_DIR": str(C.BEST_DIR),
    }
    snapshot_path = C.CONFIGS_DIR / "run_config.json"
    # Write atomically: dump to a temp file, then rename into place. os.replace
    # is atomic, so a stage reading run_config.json can only ever see the
    # complete old or complete new content — never a half-written or 0-byte file
    # (which would crash config.py with a JSONDecodeError). This matters because
    # queued LSF jobs may read this file at any moment while it's being rewritten.
    tmp_path = snapshot_path.with_name(snapshot_path.name + ".tmp")
    tmp_path.write_text(json.dumps(snapshot, indent=2))
    os.replace(tmp_path, snapshot_path)
    print(f"  Run snapshot -> {snapshot_path}")

    # Also copy the actual config.py used for this run into the output folder,
    # as a human-readable record next to the machine-read snapshot.
    import shutil
    config_copy = C.CONFIGS_DIR / "config_used.py"
    shutil.copy2(C.__file__, config_copy)
    print(f"  Config copy  -> {config_copy}")

    # Make every subprocess call below (and the LSF jobs they queue) read
    # this run's frozen settings instead of the live config.py.
    os.environ["PIPELINE_RUN_CONFIG"] = str(snapshot_path)

    n_backbones = C.RFD3_BATCH_SIZE * C.RFD3_N_BATCHES
    n_sequences = C.MPNN_BATCH_SIZE * C.MPNN_NUMBER_OF_BATCHES
    n_designs   = n_backbones * n_sequences
    import math
    n_rf3_tasks = math.ceil(n_designs / C.RF3_GROUP_SIZE)

    print(f"\n{'='*60}")
    print(f"  Partial diffusion — {C.YOUR_NAME}/{C.EXPERIMENT}")
    print(f"{'='*60}")
    print(f"  Input PDB   : {C.INPUT_PDB}")
    print(f"  Noise       : {C.PARTIAL_T} Å")
    print(f"  Backbones   : {n_backbones}  ({C.RFD3_BATCH_SIZE} × {C.RFD3_N_BATCHES} batches)")
    print(f"  Sequences   : {n_sequences} per backbone  →  {n_designs} designs total")
    print(f"  RF3 steps   : {C.RF3_NUM_STEPS}  ({n_rf3_tasks} array tasks, {C.RF3_GROUP_SIZE} folds each)")
    # Only reachable unset under --dry-run; the guard in main() stops a real
    # submit. Say so rather than printing a blank.
    print(f"  GPU queue   : {C.QUEUE or '(not set)'}   (RFD3, MPNN, RF3 folding)")
    print(f"  CPU queue   : {C.CPU_QUEUE or '(not set)'}   (prep, launcher, scoring — no GPU)")
    # If the config exposes FLEXIBLE_RESIDUES (targeted-remodel configs), echo it
    # so you can eyeball at submission time exactly which residues are free to
    # move/redesign — everything else is held rigid + native.
    _flex = getattr(C, "FLEXIBLE_RESIDUES", None)
    if _flex:
        print(f"  Flexible    : {len(_flex)} residues free to move/redesign — {_flex}")
        print(f"                (all other {len(C.CATRES)} residues held rigid + native)")
    _temp = getattr(C, "MPNN_TEMPERATURE", 0.1)
    print(f"  MPNN temp   : {_temp}"
          + ("   <- near-deterministic, expect duplicate sequences" if _temp <= 0.1 else ""))
    _ph = getattr(C, "CHANNEL_PLACEHOLDER", "")
    print(f"  Channel hold: {_ph if _ph else 'none — nothing stops the channel collapsing'}")
    print()

    # We decide here, on the login node, which stages are already complete and
    # skip *submitting* them entirely. This matters because on the DTU GPU
    # queue a job that grabs a GPU in exclusive_process mode and then exits
    # within seconds hangs in RUN during the node's GPU-release epilog — so a
    # GPU "skip job" that just exits 0 would still stall the whole chain.
    # prev_id tracks the last job actually submitted; each stage depends on it
    # (or on nothing, if every earlier stage was already done).
    prev_id = None

    # ------------------------------------------------------------------
    # Stage 1 — RFD3 (GPU, sequential batches)
    # Wall time: ~30 min per batch of RFD3_BATCH_SIZE on A100
    # ------------------------------------------------------------------
    n_diffusion = len(list(C.DIFFUSION_DIR.glob("*.cif.gz")))
    if n_diffusion >= n_backbones:
        print(f"  [1] RFD3              SKIPPED (already {n_diffusion} backbones)")
    else:
        # sys.executable, not a bare "python": on many systems only python3
        # exists and this died with exit 127.
        gen_cmd = [sys.executable, "partial_diffusion/scripts/01_rfd3_partial_submit.py"]
        if DRY_RUN:
            print(f"      [dry-run] {' '.join(gen_cmd)}")
            print("      [dry-run] (would generate submit/rfd3_partial.sh)")
        else:
            subprocess.run(gen_cmd, cwd=PIPELINE_ROOT, check=True, capture_output=True)
        # rfd3_partial.sh is generated by 01_rfd3_partial_submit.py above, so it
        # doesn't go through write_script — inject the snapshot + base-config
        # exports manually. Both are needed: PIPELINE_RUN_CONFIG for the
        # frozen path/scale overrides, PIPELINE_BASE_CONFIG so the stage
        # script imports the same config module this run was launched with
        # rather than falling back to the (possibly different, possibly
        # unwritable) plain config.py.
        rfd3_sh_path = C.SUBMIT_DIR / "rfd3_partial.sh"
        if not DRY_RUN:
            subprocess.run(
                f"sed -i '1a export PIPELINE_RUN_CONFIG={snapshot_path}\\n"
                f"export PIPELINE_BASE_CONFIG={BASE_CONFIG}' {rfd3_sh_path}",
                shell=True, check=True
            )
        prev_id = submit(rfd3_sh_path)
        print(f"  [1] RFD3              {"would submit" if DRY_RUN else "submitted "}  job {prev_id}")

    # ------------------------------------------------------------------
    # Stage 2 — filter RFD3 outputs + run MPNN
    # Split into two jobs, CPU then GPU: 02_rfd3_process.py (structural
    # metrics) and 02b_caver_filter.py (channel-width gate — same idea as
    # --pilot, just over the whole batch: a backbone that already collapsed
    # gets no better from MPNN, so don't spend GPU finding that out) are both
    # CPU-only. They used to run inside the GPU mpnn job for convenience;
    # split out because "reserve a GPU for non-GPU work" is against HPC
    # policy here, same reasoning as rf3_prep below. 02b fails OPEN — if
    # CAVER/java isn't in this env or the baseline is missing, it says so and
    # does nothing, so MPNN falls through to exactly the unfiltered behaviour
    # this pipeline had before it existed.
    # ------------------------------------------------------------------
    mpnn_done = any(C.MPNN_DIR.glob("**/*.fa"))
    if mpnn_done:
        print(f"  [2] process+MPNN      SKIPPED (sequences already present)")
    else:
        filter_minutes = max(10, n_backbones * 2)   # ~1-2 min/backbone in CAVER
        filter_sh = write_script(
            name="caver_filter",
            wall=f"{filter_minutes // 60}:{filter_minutes % 60:02d}",
            dep_id=prev_id,
            gpu=False,
            cores=2,
            mem="6GB",
            snapshot_path=snapshot_path,
            body=f"""
$PY partial_diffusion/scripts/02_rfd3_process.py
$PY partial_diffusion/scripts/02b_caver_filter.py
""")
        prev_id = submit(filter_sh)
        print(f"  [2a] process+filter    {"would submit" if DRY_RUN else "submitted "}  job {prev_id}  (CPU)")

    # A pilot stops HERE, not after RFD3. It used to return before stage 2a,
    # which meant the cluster pilot never ran 02b_caver_filter.py -- the very
    # gate the pilot exists to exercise -- while the local pilot
    # (run_local.py --stages prep-caver_filter) did run it. Same word, two
    # different meanings, and the diagram in docs/walkthrough-gpu.md described
    # the local one. Including 2a costs no GPU (it is a CPU job) and cannot
    # destroy the backbone being probed: 02b_caver_filter.py COPIES survivors
    # into widened/ and never deletes from diffusion_out/.
    if args.pilot:
        print(f"\n{'='*60}")
        print(f"  PILOT — 1 backbone, through the CAVER gate. No MPNN, no RF3.")
        print(f"{'='*60}")
        when = (f"When job {prev_id} finishes, measure the channel:"
                if prev_id else
                "Backbones already present — measure the channel now:")
        print(f"  {when}\n")
        print(f"    python partial_diffusion/scripts/08_probe_channel.py \\")
        print(f"        {C.DIFFUSION_DIR}/*.cif.gz \\")
        print(f"        --baseline <your>_baseline.json\n")
        print(f"  The gate's own verdict is in {C.LOGS_DIR}/caver_filter.*;")
        print(f"  08_probe_channel.py is the number you tune against.\n")
        print(f"  WIDER    -> rerun without --pilot for the full pipeline")
        print(f"  NARROWER -> change the config and pilot again; the probe")
        print(f"              prints what to try and logs each attempt")
        print(f"{'='*60}\n")
        return

    if not mpnn_done:
        # ~4 min/backbone (model reload + design), min 30 min, capped for a tight
        # wall so a hung GPU job is reaped quickly instead of holding a GPU for
        # hours. Format as H:MM.
        mpnn_minutes = max(30, n_backbones * 4)
        mpnn_sh = write_script(
            name="mpnn_stage",
            wall=f"{mpnn_minutes // 60}:{mpnn_minutes % 60:02d}",
            dep_id=prev_id,
            snapshot_path=snapshot_path,
            body=f"""
$PY partial_diffusion/scripts/03_mpnn_submit.py

echo "--- Running MPNN ---"
while IFS= read -r cmd; do
    echo "$cmd"
    eval "$cmd"
done < {C.CMDS_DIR}/mpnn.cmds
""")
        prev_id = submit(mpnn_sh)
        print(f"  [2b] MPNN              {"would submit" if DRY_RUN else "submitted "}  job {prev_id}  (GPU)")

    # ------------------------------------------------------------------
    # Stage 3a — generate RF3 inputs (CPU only, fast)
    # Runs 04_rf3_submit.py which writes the RF3 JSONs and rf3.sh array job.
    # Skip at the login node if the inputs are already built — otherwise this
    # trivial job would grab a GPU on gpua100 and hang until wall-time.
    # ------------------------------------------------------------------
    rf3_inputs_ready = (
        (C.SUBMIT_DIR / "rf3.sh").exists()
        and any((C.CONFIGS_DIR / "rf3").glob("*.json"))
    )
    if rf3_inputs_ready:
        print(f"  [3] RF3 input prep    SKIPPED (inputs already built)")
    else:
        prep_sh = write_script(
            name="rf3_prep",
            wall="0:20",
            dep_id=prev_id,
            gpu=False,
            cores=1,
            mem="4GB",
            snapshot_path=snapshot_path,
            body=f"""
$PY partial_diffusion/scripts/04_rf3_submit.py

# rf3.sh below is submitted as its OWN later bsub job, so it won't inherit
# PIPELINE_RUN_CONFIG / PIPELINE_BASE_CONFIG from this job's environment —
# pin both explicitly so it still reads this run's config whenever it
# actually executes.
sed -i '1a export PIPELINE_RUN_CONFIG={snapshot_path}\\nexport PIPELINE_BASE_CONFIG={BASE_CONFIG}' {C.SUBMIT_DIR}/rf3.sh
"""
        )
        prev_id = submit(prep_sh)
        print(f"  [3] RF3 input prep    {"would submit" if DRY_RUN else "submitted "}  job {prev_id}")

    # ------------------------------------------------------------------
    # Stage 3b — RF3 array job (GPU, parallel)
    # 04_rf3_submit.py already wrote rf3.sh as an array job; inject dependency
    # ------------------------------------------------------------------
    # We need to submit rf3.sh after prep finishes, so wrap it in a launcher
    rf3_launcher_sh = C.SUBMIT_DIR / "rf3_launcher.sh"
    rf3_sh = C.SUBMIT_DIR / "rf3.sh"
    launcher_dep = f'#BSUB -w "ended({prev_id})"' if prev_id else ""
    # Same conditional activation as write_script, spelled out again because
    # this script is written by hand rather than through it. SCORE_CMD is a
    # single shell string run later, so its activation is && -joined.
    launcher_env = f"source {C.CONDA_SH}\n\n" if C.CONDA_SH else ""
    score_activate = ""
    if C.CONDA_SH:
        score_activate += f" && source {C.CONDA_SH}"
    if C.PROTEIN_ENV:
        score_activate += f" && conda activate {C.PROTEIN_ENV}"
    rf3_launcher_sh.write_text(f"""#!/bin/sh
#BSUB -q {C.CPU_QUEUE}
#BSUB -J rf3_launcher
#BSUB -n 1
#BSUB -W 0:10
#BSUB -R "rusage[mem=2GB]"
{launcher_dep}
#BSUB -o {C.LOGS_DIR}/rf3_launcher_%J.out
#BSUB -e {C.LOGS_DIR}/rf3_launcher_%J.err

{launcher_env}PY="$(command -v python || command -v python3)"

SCORE_CMD="export PIPELINE_RUN_CONFIG={snapshot_path} && export PIPELINE_BASE_CONFIG={BASE_CONFIG}{score_activate} && cd {PIPELINE_ROOT} && $PY partial_diffusion/scripts/05_rf3_score.py && $PY partial_diffusion/scripts/06_collect_best.py && echo Done"

# All done — nothing left to submit
if [ -f {C.SCORES_DIR}/rf3_metrics.csv ]; then
    echo "Scores already present — pipeline complete, nothing to submit."
    exit 0
fi

# RF3 already ran — check by counting completed backbone output dirs vs expected.
# rf3.cmds has one line per backbone; each line writes to its own rf3_out/<stem>/.
# A backbone dir is "done" when it contains at least one .cif.gz file.
if [ -f {C.CMDS_DIR}/rf3.cmds ]; then
    EXPECTED=$(wc -l < {C.CMDS_DIR}/rf3.cmds)
    FOUND=$(find {C.RF3_DIR} -mindepth 2 -maxdepth 2 -name "*.cif.gz" -printf '%h\\n' 2>/dev/null | sort -u | wc -l)
    if [ "$FOUND" -ge "$EXPECTED" ] && [ "$EXPECTED" -gt 0 ]; then
        echo "RF3 outputs complete ($FOUND/$EXPECTED backbone dirs done) — submitting scoring only."
        bsub -q {C.CPU_QUEUE} -J score_stage -n 1 -W 0:30 \\
             -R "rusage[mem=4GB]" \\
             -o {C.LOGS_DIR}/score_%J.out \\
             -e {C.LOGS_DIR}/score_%J.err \\
             bash -c "$SCORE_CMD"
        echo "Scoring job submitted."
        exit 0
    fi
fi

# Normal path: submit the RF3 array job, then scoring after it finishes
RF3_OUT=$(bsub < {rf3_sh})
echo "$RF3_OUT"
RF3_ID=$(echo "$RF3_OUT" | grep -oP 'Job <\\K[0-9]+')

bsub -w "ended($RF3_ID)" \\
     -q {C.CPU_QUEUE} -J score_stage -n 1 -W 0:30 \\
     -R "rusage[mem=4GB]" \\
     -o {C.LOGS_DIR}/score_%J.out \\
     -e {C.LOGS_DIR}/score_%J.err \\
     bash -c "$SCORE_CMD"

echo "RF3 array and scoring submitted."
""")
    rf3_launcher_sh.chmod(0o755)
    launcher_id = submit(rf3_launcher_sh)
    print(f"  [4] RF3 array+scoring {"would submit" if DRY_RUN else "submitted "}  job {launcher_id}")

    print(f"\n{'='*60}")
    print(f"  All jobs queued.  Monitor: bstat")
    print(f"  Logs      : {C.LOGS_DIR}/")
    print(f"  Outputs   : {C.WORK}/")
    print(f"  Best CIFs : {C.BEST_DIR}/")
    print(f"\n  Rough timeline:")
    rfd3_h = max(1, n_backbones * 15 // 60)
    print(f"    RFD3    : ~{rfd3_h}–{rfd3_h+2}h")
    print(f"    MPNN    : ~{max(1, n_backbones * 2 // 60)}–{max(1, n_backbones * 3 // 60) + 1}h")
    print(f"    RF3     : ~1–3h  (parallel array, {n_rf3_tasks} tasks)")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
