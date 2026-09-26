#!/usr/bin/env python3
"""
00_make_msa.py — build the native MSA that RF3 folds against.

Extracts chain A from INPUT_PDB and runs a ColabFold/MMseqs2 search, writing
inputs/<pdb_stem>_A.a3m.gz — the file NATIVE_MSA_PATH points at. This is the
same thing that produced the existing grogu_fixed_A.a3m.gz (verified: its query
line is byte-identical to chain A of grogu_fixed.pdb).

Run ONCE per enzyme, before 04_rf3_submit.py. The MSA is of the NATIVE
sequence and is reused for every design — see the note at the bottom of this
docstring for why per-design MSAs are the wrong move.

  python partial_diffusion/scripts/00_make_msa.py                  # auto backend
  python partial_diffusion/scripts/00_make_msa.py --backend api    # no install needed
  python partial_diffusion/scripts/00_make_msa.py --backend local --db /path/to/colabfold_dbs
  python partial_diffusion/scripts/00_make_msa.py --pdb inputs/other.pdb --chain A

Backends:
  api     talks to https://api.colabfold.com directly over stdlib urllib —
          submit a ticket, poll, download the tarball. Nothing to install, no
          colabfold/jax dependency chain. This is what `auto` uses when no
          local databases are present.
  remote  the same server, but driven through `colabfold_batch --msa-only`.
          Only useful if colabfold is already installed.
  local   colabfold_search against your own ColabFoldDB/UniRef30 (~1-2 TB on
          disk). Offline and unthrottled; worth it only if you do this often.

One query per enzyme is normal, courteous use of a free shared service. Do not
loop this script.

Then put the printed path in config.py as NATIVE_MSA_PATH.

WHY NOT ONE MSA PER DESIGN: designs differ from the native at only the
FLEXIBLE_RESIDUES (12 here, of 334), so an MMseqs2 search would return
essentially the same homologs — at the cost of hundreds of queries against a
free public server. Fold the designs against the native MSA, or against no MSA
at all if you want the confidence metrics to reflect the design rather than the
native fold.
"""
import argparse
import gzip
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Config resolution, in priority order:
#   1. Whatever run_local.py already installed as partial_diffusion.config
#      (that is config_local, which has itself honoured PIPELINE_BASE_CONFIG).
#   2. Standalone: honour PIPELINE_BASE_CONFIG ourselves, so
#      `export PIPELINE_BASE_CONFIG=partial_diffusion.config_mroupo` works when
#      this script is run directly and not through the pipeline.
#   3. Plain config.py.
C = sys.modules.get("partial_diffusion.config")
if C is None:
    import importlib
    C = importlib.import_module(
        os.environ.get("PIPELINE_BASE_CONFIG", "partial_diffusion.config"))

THREE2ONE = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C", "GLN": "Q",
    "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I", "LEU": "L", "LYS": "K",
    "MET": "M", "PHE": "F", "PRO": "P", "SER": "S", "THR": "T", "TRP": "W",
    "TYR": "Y", "VAL": "V", "MSE": "M",
}


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--pdb", default=None, help="PDB to read (default: INPUT_PDB from config)")
    p.add_argument("--chain", default="A", help="chain to search (default A — the enzyme)")
    p.add_argument("--backend", default="auto", choices=("auto", "api", "remote", "local"),
                   help="api = talk to the ColabFold server directly (no install "
                        "needed); remote = via colabfold_batch; local = own databases")
    p.add_argument("--api-mode", default="env",
                   help="ColabFold search mode for --backend api (default env)")
    p.add_argument("--db", default=None, help="ColabFold database dir (local backend)")
    p.add_argument("--out", default=None, help="output .a3m.gz (default inputs/<stem>_<chain>.a3m.gz)")
    p.add_argument("--force", action="store_true", help="overwrite an existing MSA")
    return p.parse_args()


def chain_sequence(pdb_path, chain):
    """One-letter sequence from CA atoms, taking the first altloc only.

    Matches config._chain_resids' view of the chain, so the MSA query lines up
    with the residue numbering the rest of the pipeline uses.
    """
    seq = {}
    with open(pdb_path) as f:
        for line in f:
            if line[:4] != "ATOM" or line[21] != chain:
                continue
            if line[12:16].strip() != "CA" or line[16] not in (" ", "A"):
                continue
            resi = int(line[22:26])
            seq.setdefault(resi, THREE2ONE.get(line[17:20].strip(), "X"))
    if not seq:
        sys.exit(f"No CA atoms for chain {chain} in {pdb_path}")
    resis = sorted(seq)
    gaps = [r for r in range(resis[0], resis[-1] + 1) if r not in seq]
    if gaps:
        print(f"  NOTE: {len(gaps)} numbering gap(s) in chain {chain} "
              f"(e.g. {gaps[:5]}) — the MSA query is the resolved residues only.")
    unknown = sum(1 for r in resis if seq[r] == "X")
    if unknown:
        print(f"  WARNING: {unknown} residue(s) had unrecognised names -> X")
    return "".join(seq[r] for r in resis), resis[0], resis[-1]


def pick_backend(requested):
    have_remote = shutil.which("colabfold_batch")
    have_local = shutil.which("colabfold_search")
    if requested == "remote":
        if not have_remote:
            sys.exit("colabfold_batch not on $PATH — use --backend api (needs nothing "
                     "installed) or --backend local.")
        return "remote"
    if requested == "local":
        if not have_local:
            sys.exit("colabfold_search not on $PATH — use --backend api or install colabfold.")
        return "local"
    if requested == "api":
        return "api"
    # auto: local databases are fastest and unthrottled; otherwise talk to the
    # public server directly — no colabfold install needed for that.
    if have_local:
        return "local"
    return "api"


# --- ColabFold MMseqs2 server -------------------------------------------------
# Protocol (github.com/sokrypton/ColabFold, run_mmseqs2):
#   POST {host}/ticket/msa      form fields q=<fasta>, mode=<env|all|...>
#   GET  {host}/ticket/{id}     -> {"status": PENDING|RUNNING|COMPLETE|ERROR|...}
#   GET  {host}/result/download/{id}  -> tar.gz of uniref.a3m, bfd...a3m
# Implemented on urllib so this works in any environment, with no colabfold
# install and no jax/alphafold dependency chain.
API_HOST = "https://api.colabfold.com"
USER_AGENT = "enzyme_design_hpc/00_make_msa.py"


def _api_call(url, data=None, raw=False, timeout=30):
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(data).encode() if data else None,
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        payload = r.read()
    return payload if raw else json.loads(payload)


def search_api(seq, name, workdir, mode="env", host=API_HOST):
    fasta = f">{name}\n{seq}\n"
    try:
        res = _api_call(f"{host}/ticket/msa", {"q": fasta, "mode": mode})
    except urllib.error.URLError as e:
        sys.exit(f"Could not reach {host}: {e}\n"
                 "  (no network? try --backend local with your own databases)")

    status = res.get("status")
    ticket = res.get("id")
    if status in ("ERROR", "MAINTENANCE"):
        sys.exit(f"ColabFold server returned {status} — try again later.")
    if status == "RATELIMIT":
        sys.exit("ColabFold server rate-limited this client. Wait a few minutes "
                 "and retry; do not loop this script.")
    if not ticket:
        sys.exit(f"Unexpected response from {host}: {res}")

    print(f"  ticket {ticket} — waiting for the search to finish")
    delay, waited = 5, 0
    while True:
        time.sleep(delay)
        waited += delay
        try:
            res = _api_call(f"{host}/ticket/{ticket}")
        except urllib.error.URLError as e:
            print(f"    poll failed ({e}) — retrying")
            continue
        status = res.get("status")
        if status == "COMPLETE":
            break
        if status in ("ERROR", "MAINTENANCE", "UNKNOWN"):
            sys.exit(f"Search failed: server status {status}")
        print(f"    {status} ({waited}s)")
        delay = min(delay + 5, 30)   # back off; this is a shared free service

    print("  downloading results")
    blob = _api_call(f"{host}/result/download/{ticket}", raw=True, timeout=300)
    tar_path = Path(workdir) / "result.tar.gz"
    tar_path.write_bytes(blob)
    with tarfile.open(tar_path) as tf:
        # filter="data" refuses absolute paths and ../ escapes — this archive
        # comes off the network, so don't let it write outside workdir.
        try:
            tf.extractall(workdir, filter="data")
        except TypeError:          # filter= added in 3.11.4/3.12
            tf.extractall(workdir)
    return Path(workdir)


def run(cmd):
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    proc = subprocess.run([str(c) for c in cmd])
    if proc.returncode != 0:
        sys.exit(f"MSA search failed (exit {proc.returncode}).")


def search_remote(fasta, workdir):
    run(["colabfold_batch", "--msa-only", str(fasta), str(workdir)])
    return workdir


def search_local(fasta, workdir, db):
    if not db:
        sys.exit("--backend local needs --db pointing at your ColabFold database dir.")
    if not Path(db).is_dir():
        sys.exit(f"Database dir not found: {db}")
    run(["colabfold_search", str(fasta), str(db), str(workdir)])
    return workdir


def merge_a3m(workdir):
    """The server returns one a3m per database (uniref + environmental).
    ColabFold uses them together, so concatenate: keep the first file's header
    and query, then append the others' alignment rows."""
    order = ["uniref.a3m", "bfd.mgnify30.metaeuk30.smag30.a3m"]
    # exclude our own output — otherwise a re-run in the same directory would
    # read the previous merge back in as a source.
    found = {p.name: p for p in Path(workdir).rglob("*.a3m") if p.name != "merged.a3m"}
    picked = [found[n] for n in order if n in found]
    picked += [p for n, p in sorted(found.items()) if n not in order]
    if not picked:
        sys.exit(f"Download contained no .a3m files (looked under {workdir})")
    if len(picked) == 1:
        return picked[0]

    out = Path(workdir) / "merged.a3m"
    with open(out, "w") as dst:
        for i, src in enumerate(picked):
            header, records = None, []
            for line in open(src):
                if line.startswith("#"):
                    header = line
                elif line.startswith(">"):
                    records.append([line, ""])
                elif records:
                    records[-1][1] += line
            if i == 0:
                if header:
                    dst.write(header)        # one #len<TAB>card header overall
            else:
                records = records[1:]        # drop the repeated query entry
            for name, seq in records:
                dst.write(name)
                dst.write(seq)
    print(f"  merged {len(picked)} alignment(s): {[p.name for p in picked]}")
    return out


def find_a3m(workdir):
    hits = sorted(Path(workdir).rglob("*.a3m"))
    if not hits:
        sys.exit(f"Search finished but produced no .a3m under {workdir}")
    # colabfold_search writes 0.a3m; colabfold_batch writes <name>.a3m
    return max(hits, key=lambda p: p.stat().st_size)


def verify(a3m_path, query_seq):
    """Check the a3m really describes our query before we commit to it."""
    n_seqs, first_seq = 0, None
    with open(a3m_path) as f:
        for line in f:
            if line.startswith("#"):
                continue
            if line.startswith(">"):
                n_seqs += 1
            elif first_seq is None:
                first_seq = line.strip()
    if first_seq is None:
        sys.exit(f"{a3m_path} has no sequences.")
    plain = first_seq.replace("-", "")
    plain = "".join(c for c in plain if not c.islower())
    if plain != query_seq:
        print(f"  WARNING: a3m query ({len(plain)} aa) does not match chain "
              f"sequence ({len(query_seq)} aa) — check the search input.")
    return n_seqs


def clean_a3m(a3m_path):
    """Strip NUL bytes and drop empty-sequence records.

    Seen reproducibly (not a one-off transfer glitch — confirmed by
    re-querying) for extremely weak ColabFold hits (e-value > 1): the server
    sometimes returns such a record as a bare NUL byte instead of a properly
    gap-padded row. RF3's fixed-width MSA loader can't handle that and dies
    with an "inhomogeneous shape" crash deep inside folding, so clean it here
    instead of trusting every future download to come back well-formed.
    """
    raw = Path(a3m_path).read_bytes()
    n_nul = raw.count(b"\x00")
    text = raw.replace(b"\x00", b"").decode("utf-8", errors="replace")

    lines = text.splitlines(keepends=True)
    out, dropped = [], []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith(">"):
            body = lines[i + 1] if i + 1 < len(lines) else ""
            if body.strip() == "":
                dropped.append(line.strip())
                i += 2
                continue
            out.append(line)
            out.append(body)
            i += 2
        else:
            out.append(line)
            i += 1

    if n_nul or dropped:
        print(f"  NOTE: cleaned {n_nul} NUL byte(s) and {len(dropped)} "
              f"empty-sequence record(s) out of the downloaded MSA "
              f"(known ColabFold quirk on very weak hits):")
        for d in dropped:
            print(f"    dropped: {d}")

    return "".join(out).encode("utf-8"), n_nul, len(dropped)


def main():
    args = parse_args()
    pdb = Path(args.pdb) if args.pdb else Path(C.INPUT_PDB)
    if not pdb.exists():
        sys.exit(f"Not found: {pdb}")

    out = Path(args.out) if args.out else (
        Path(C.PIPELINE_ROOT).parent / "inputs" / f"{pdb.stem}_{args.chain}.a3m.gz")
    if out.exists() and not args.force:
        sys.exit(f"{out} already exists — pass --force to regenerate.")

    seq, first, last = chain_sequence(pdb, args.chain)
    backend = pick_backend(args.backend)
    print(f"  PDB      : {pdb}")
    print(f"  chain {args.chain}  : {len(seq)} residues ({first}-{last})")
    print(f"  backend  : {backend}")
    if backend in ("remote", "api"):
        print("  (querying the public ColabFold MMseqs2 server — this can take "
              "several minutes, and queues behind other users)")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        fasta = tmp / f"{pdb.stem}_{args.chain}.fasta"
        fasta.write_text(f">{pdb.stem}_{args.chain}\n{seq}\n")
        workdir = tmp / "msa"
        workdir.mkdir()
        if backend == "api":
            search_api(seq, f"{pdb.stem}_{args.chain}", workdir, mode=args.api_mode)
            a3m = merge_a3m(workdir)
        else:
            if backend == "remote":
                search_remote(fasta, workdir)
            else:
                search_local(fasta, workdir, args.db)
            a3m = find_a3m(workdir)
        verify(a3m, seq)
        cleaned, n_nul, n_dropped = clean_a3m(a3m)
        n_seqs = cleaned.count(b"\n>") + (1 if cleaned.startswith(b">") else 0)
        out.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(out, "wb") as dst:
            dst.write(cleaned)

    print(f"\n  Wrote {out}  ({n_seqs} sequences, "
          f"{out.stat().st_size/1e6:.1f} MB gzipped)")
    if n_nul or n_dropped:
        print(f"  (cleaned {n_nul} NUL byte(s), dropped {n_dropped} "
              f"malformed record(s) — see NOTE above)")
    if n_seqs < 100:
        print("  WARNING: shallow MSA (<100 sequences) — RF3 will get little "
              "evolutionary signal. Consider folding single-sequence instead.")
    print(f"\n  Set in config.py:")
    print(f'    NATIVE_MSA_PATH = "{out.resolve()}"')
    print("  (config_local.py finds inputs/<pdb_stem>_A.a3m.gz automatically.)")
    print("\n  Next:  python partial_diffusion/scripts/04_rf3_submit.py")


if __name__ == "__main__":
    main()
