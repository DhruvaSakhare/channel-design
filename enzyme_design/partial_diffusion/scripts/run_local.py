#!/usr/bin/env python3
"""
run_local.py — run the whole partial-diffusion pipeline on one local GPU.

Same stages as 00_submit_all.py, but with no LSF: instead of `bsub`-ing the
generated .sh files, this runs the generated commands here, one after another.
Config comes from config_local.py (which inherits everything scientific from
config.py and only replaces cluster paths).

Usage:
  conda activate <your protein-design env>
  python partial_diffusion/scripts/run_local.py --check      # preflight only
  python partial_diffusion/scripts/run_local.py              # stages 0-6
  python partial_diffusion/scripts/run_local.py --stages 3-6 # resume partway
  python partial_diffusion/scripts/run_local.py --dry-run    # print, don't run

Stages:
  0  prep      PDB sanity check (+ MSA if --auto-msa) (CPU/network)
  1  rfd3      partial diffusion -> backbones         (GPU)
  2  process   filter broken backbones                (CPU)
  3  mpnn      LigandMPNN sequence design             (GPU)
  4  rf3       RF3 folding of every design            (GPU)
  5  score     metrics CSV + plots                    (CPU)
  6  collect   best designs -> best_designs/          (CPU)
"""
import argparse
import os
import runpy
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

REPO_ROOT   = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

# Load the local config and install it as `partial_diffusion.config`, so the
# stage scripts pick it up when they import it.
# BOTH bindings are needed: `import a.b as c` resolves through getattr(a, "b")
# and only falls back to sys.modules, so patching sys.modules alone leaves the
# stage scripts importing the real config — and creating /work3 paths.
import partial_diffusion                            # noqa: E402
import partial_diffusion.config_local as C          # noqa: E402
sys.modules["partial_diffusion.config"] = C
partial_diffusion.config = C

STAGES = ["prep", "rfd3", "process", "mpnn", "rf3", "score", "collect"]


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stages", default="0-6",
                   help="stages to run: '0-6', '3-6', or '1,3,4' (default 0-6)")
    p.add_argument("--check", action="store_true",
                   help="run preflight checks and exit")
    p.add_argument("--dry-run", action="store_true",
                   help="print every command instead of running it")
    p.add_argument("--skip-preflight", action="store_true",
                   help="don't verify tools/checkpoints before starting")
    p.add_argument("--auto-msa", action="store_true",
                   help="in stage 0, build the native MSA if it is missing "
                        "(00_make_msa.py; may query the public ColabFold server)")
    p.add_argument("--msa-backend", default="auto", choices=("auto", "remote", "local"),
                   help="backend for --auto-msa (default auto)")
    p.add_argument("--msa-db", default=None,
                   help="ColabFold database dir, for --msa-backend local")
    return p.parse_args()


def expected_msa_path():
    """Same rule config_local.py uses: inputs/<pdb_stem>_A.a3m.gz."""
    return REPO_ROOT / "inputs" / f"{Path(C.INPUT_PDB).stem}_A.a3m.gz"


def parse_stages(spec):
    picked = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            picked.update(range(int(lo), int(hi) + 1))
        elif part:
            picked.add(int(part))
    bad = [s for s in picked if s not in range(len(STAGES))]
    if bad:
        sys.exit(f"No such stage(s): {sorted(bad)} — valid range is 0-{len(STAGES)-1}")
    return sorted(picked)


# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------
def check_checkpoint(path, label, problems, notes):
    """Existence is not enough — a truncated checkpoint passes `exists()` and
    then dies inside torch.load with 'failed finding central directory'.
    torch .pt/.ckpt files are zip archives, and is_zipfile() only reads the
    end-of-central-directory record, so this is cheap even for 3 GB files."""
    p = Path(path)
    if not p.exists():
        problems.append(f"{label} checkpoint missing: {p}")
        return
    size = p.stat().st_size
    if not zipfile.is_zipfile(p):
        problems.append(
            f"{label} checkpoint is not a readable archive ({size:,} bytes): {p}\n"
            f"           Truncated or corrupt — re-copy it and compare checksums.")
        return
    notes.append(f"{label} ckpt: {size/1e9:.2f} GB  {p}")


def preflight(stages):
    problems, notes = [], []

    gpu_stages = {1, 3, 4} & set(stages)
    if gpu_stages:
        smi = shutil.which("nvidia-smi")
        if not smi:
            problems.append("nvidia-smi not found — no CUDA driver on this machine.")
        else:
            out = subprocess.run([smi, "--query-gpu=name,memory.total",
                                  "--format=csv,noheader"],
                                 capture_output=True, text=True)
            gpus = [l for l in out.stdout.strip().splitlines() if l]
            if not gpus:
                problems.append("nvidia-smi reports no GPUs.")
            for g in gpus:
                notes.append(f"GPU: {g}")

    if 1 in stages:
        if not shutil.which("rfd3"):
            problems.append("`rfd3` not on $PATH — activate the env with RFdiffusion3.")
        check_checkpoint(C.RFD3_CKPT, "RFD3", problems, notes)
    if 3 in stages:
        if not shutil.which("mpnn"):
            problems.append("`mpnn` not on $PATH — activate the env with LigandMPNN.")
        check_checkpoint(C.MPNN_CKPT, "MPNN", problems, notes)
    if 4 in stages:
        wrapper = Path(C.LIB_ROOT) / "rf3_wrapper.py"
        if not wrapper.exists():
            problems.append(f"RF3 wrapper missing: {wrapper}")
        check_checkpoint(C.RF3_CKPT, "RF3", problems, notes)
        if C.RF3_ACTIVATE and not Path(C.RF3_ACTIVATE).exists():
            notes.append(f"RF3_ACTIVATE not found ({C.RF3_ACTIVATE}) — "
                         "assuming RF3 runs in the current env.")

    if not Path(C.INPUT_PDB).exists():
        problems.append(f"INPUT_PDB missing: {C.INPUT_PDB}")
    if C.NATIVE_MSA_PATH:
        if Path(C.NATIVE_MSA_PATH).exists():
            notes.append(f"MSA: {C.NATIVE_MSA_PATH}")
        else:
            problems.append(f"NATIVE_MSA_PATH set but missing: {C.NATIVE_MSA_PATH}")
    else:
        notes.append(f"MSA: none — RF3 will fold single-sequence. Build one with "
                     f"--auto-msa, or:\n           python {SCRIPTS_DIR}/00_make_msa.py\n"
                     f"           (expected at {expected_msa_path()})\n"
                     f"           NOTE: the PLDDT_CUT={C.PLDDT_CUT} gate is calibrated "
                     f"for MSA folding; single-sequence pLDDT runs lower.")

    print("--- PREFLIGHT ---")
    print(f"  experiment : {C.EXPERIMENT}  (owner {C.YOUR_NAME})")
    print(f"  input PDB  : {C.INPUT_PDB}")
    print(f"  work dir   : {C.WORK}")
    print(f"  backbones  : {C.RFD3_BATCH_SIZE * C.RFD3_N_BATCHES}"
          f"  x {C.MPNN_BATCH_SIZE * C.MPNN_NUMBER_OF_BATCHES} seqs"
          f" = {C.RFD3_BATCH_SIZE * C.RFD3_N_BATCHES * C.MPNN_BATCH_SIZE * C.MPNN_NUMBER_OF_BATCHES} folds")
    for n in notes:
        print(f"  {n}")
    for p in problems:
        print(f"  MISSING: {p}")
    print()
    return problems


# ---------------------------------------------------------------------------
# runners
# ---------------------------------------------------------------------------
def run_stage_script(script_name, argv=(), dry_run=False, fatal=True):
    """Execute a stage script in-process so it sees our patched config.

    Returns True on success. With fatal=False a failure is reported and the
    pipeline continues (used for the optional MSA build, where the fallback is
    single-sequence folding rather than a dead run).
    """
    path = SCRIPTS_DIR / script_name
    if dry_run:
        print(f"  [dry-run] python {path} {' '.join(argv)}")
        return True
    old_argv = sys.argv
    sys.argv = [str(path), *argv]
    try:
        runpy.run_path(str(path), run_name="__main__")
        return True
    except SystemExit as e:
        # Stage scripts sys.exit(str) on a real problem, sys.exit(0)/None when fine.
        if e.code in (0, None):
            return True
        if fatal:
            # `from None` — without it the new SystemExit is chained to the one
            # we just caught and Python prints a traceback over the message.
            raise SystemExit(f"{script_name} stopped: {e.code}") from None
        print(f"  {script_name} stopped: {e.code}")
        return False
    finally:
        sys.argv = old_argv


def shell(cmd, env=None, source=None, dry_run=False):
    """Run one command line under bash, optionally sourcing an env script."""
    full = f"source {source} >/dev/null 2>&1; {cmd}" if source else cmd
    if dry_run:
        print(f"  [dry-run] {cmd}")
        return 0
    proc = subprocess.run(["bash", "-c", full], env={**os.environ, **(env or {})})
    return proc.returncode


def run_cmds_file(path, source=None, dry_run=False, skip_if=None):
    """Run every line of a .cmds file sequentially (the LSF array script runs
    the same lines, just spread over tasks)."""
    lines = [l.strip() for l in Path(path).read_text().splitlines() if l.strip()]
    total, failed, skipped = len(lines), 0, 0
    for i, cmd in enumerate(lines, 1):
        if skip_if and skip_if(cmd):
            print(f"  [{i}/{total}] already done — skipping")
            skipped += 1
            continue
        print(f"  [{i}/{total}] {cmd[:110]}{'...' if len(cmd) > 110 else ''}")
        t0 = time.time()
        rc = shell(cmd, source=source, dry_run=dry_run)
        if rc != 0:
            print(f"       FAILED (exit {rc}) after {time.time()-t0:.0f}s — continuing")
            failed += 1
        else:
            print(f"       done in {time.time()-t0:.0f}s")
    if skipped:
        print(f"  {skipped}/{total} skipped (outputs present)")
    if failed:
        print(f"  WARNING: {failed}/{total} command(s) failed — later stages will "
              f"work with whatever succeeded.")
    return failed


def rf3_already_folded(cmd):
    """Mirror of the out_dir check in the LSF rf3 array script (which uses
    `grep -oP`, GNU-only)."""
    for tok in cmd.split():
        if tok.startswith("out_dir="):
            out_dir = Path(tok.split("=", 1)[1])
            return out_dir.is_dir() and any(out_dir.rglob("*.cif"))
    return False


# ---------------------------------------------------------------------------
# stages
# ---------------------------------------------------------------------------
def stage_rfd3(dry_run):
    """01 writes the input JSON + an LSF script; we ignore the script and call
    rfd3 directly with the same arguments."""
    run_stage_script("01_rfd3_partial_submit.py", dry_run=dry_run)

    n_expected = C.RFD3_BATCH_SIZE * C.RFD3_N_BATCHES
    found = len(list(Path(C.DIFFUSION_DIR).glob("*.cif.gz")))
    if found >= n_expected:
        print(f"  RFD3 outputs already present ({found} >= {n_expected}) — skipping.")
        return

    rfd3_json = C.CONFIGS_DIR / "rfd3_partial_input.json"
    cmd = (
        f'rfd3 design'
        f' out_dir="{C.DIFFUSION_DIR}"'
        f' inputs="{rfd3_json}"'
        f' ckpt_path="{C.RFD3_CKPT}"'
        f' diffusion_batch_size={C.RFD3_BATCH_SIZE}'
        f' n_batches={C.RFD3_N_BATCHES}'
        f' low_memory_mode=True'
    )
    env = {"DISABLE_CUEQUIVARIANCE": "true",
           "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"}
    if not dry_run:
        print(f"  {cmd}")
    t0 = time.time()
    rc = shell(cmd, env=env, dry_run=dry_run)
    if rc != 0:
        sys.exit(f"rfd3 failed (exit {rc}) — nothing downstream will work.")
    print(f"  RFD3 done in {time.time()-t0:.0f}s")


def stage_prep(args):
    run_stage_script("00_prep_pdb.py", ["--check"], dry_run=args.dry_run)
    if not args.auto_msa:
        return

    # Check the file on disk, not C.NATIVE_MSA_PATH: the config resolves that
    # at import time and it may be empty (or overridden) while the MSA is in
    # fact already sitting in inputs/.
    out = expected_msa_path()
    for existing in (Path(C.NATIVE_MSA_PATH) if C.NATIVE_MSA_PATH else None, out):
        if existing and existing.exists():
            print(f"  MSA already present ({existing}) — not rebuilding.")
            C.NATIVE_MSA_PATH = str(existing)
            return

    argv = ["--out", str(out), "--backend", args.msa_backend]
    if args.msa_db:
        argv += ["--db", args.msa_db]
    print("  building native MSA (once per enzyme)...")
    run_stage_script("00_make_msa.py", argv, dry_run=args.dry_run, fatal=False)

    # config_local resolved NATIVE_MSA_PATH at import time, before the file
    # existed — point it at the new MSA so stage 4 picks it up this run.
    if out.exists():
        C.NATIVE_MSA_PATH = str(out)
        print(f"  NATIVE_MSA_PATH -> {out}")
    elif not args.dry_run:
        print("  WARNING: MSA build produced no file — stage 4 will fold "
              "single-sequence.")


def stage_mpnn(dry_run):
    run_stage_script("03_mpnn_submit.py", dry_run=dry_run)
    cmds = C.CMDS_DIR / "mpnn.cmds"
    if dry_run and not cmds.exists():
        return
    run_cmds_file(cmds, dry_run=dry_run)


def stage_rf3(dry_run):
    run_stage_script("04_rf3_submit.py", dry_run=dry_run)
    cmds = C.CMDS_DIR / "rf3.cmds"
    if dry_run and not cmds.exists():
        return
    source = C.RF3_ACTIVATE if (C.RF3_ACTIVATE and Path(C.RF3_ACTIVATE).exists()) else None
    os.environ.setdefault("DISABLE_CUEQUIVARIANCE", "true")
    run_cmds_file(cmds, source=source, dry_run=dry_run, skip_if=rf3_already_folded)


def main():
    args = parse_args()
    stages = parse_stages(args.stages)

    problems = preflight(stages)
    if args.check:
        sys.exit(1 if problems else 0)
    if problems and not args.skip_preflight:
        sys.exit("Preflight failed — fix the items above, set the matching env "
                 "vars, or pass --skip-preflight.")

    C.make_workdirs()
    t_start = time.time()
    for s in stages:
        print(f"\n=== stage {s} — {STAGES[s]} " + "=" * 40)
        t0 = time.time()
        if s == 0:
            stage_prep(args)
        elif s == 1:
            stage_rfd3(args.dry_run)
        elif s == 2:
            run_stage_script("02_rfd3_process.py", dry_run=args.dry_run)
        elif s == 3:
            stage_mpnn(args.dry_run)
        elif s == 4:
            stage_rf3(args.dry_run)
        elif s == 5:
            run_stage_script("05_rf3_score.py", dry_run=args.dry_run)
        elif s == 6:
            run_stage_script("06_collect_best.py", dry_run=args.dry_run)
        print(f"--- stage {s} ({STAGES[s]}) finished in {time.time()-t0:.0f}s")

    print(f"\nAll requested stages done in {(time.time()-t_start)/60:.1f} min.")
    print(f"Results: {C.WORK}")
    if 6 in stages:
        print(f"Best designs: {C.BEST_DIR}")


if __name__ == "__main__":
    main()
