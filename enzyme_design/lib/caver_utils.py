"""
caver_utils.py — run CAVER on a single structure and read back what the
partial diffusion pipeline needs from it.

Three things come out of a CAVER run here:

  tunnel geometry   — bottleneck radius / length / throughput of the widest
                      channel, used as the before/after number ("did it
                      actually open up?")
  lining residues   — which residues form the channel wall, split into those
                      that line it with a SIDECHAIN (MPNN can shrink them) and
                      those that line it with BACKBONE only (only RFD3 moving
                      the backbone can widen those). This is what feeds
                      FLEXIBLE_RESIDUES.
  tunnel path       — the sphere centres + radii along the channel axis, which
                      can be written out as a placeholder "ligand" so RFD3
                      packs AROUND an open channel instead of collapsing into it.

CAVER's own config has compute_tunnel_residues / compute_bottleneck_residues
switched off by default; make_config() below forces them on, because the
residue list is the whole point of running it from this side.
"""

import csv
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

# channel_discovery/ is a sibling component at the repository root, and CAVER is
# fetched rather than vendored, so both are resolved in one place. See lib/paths.py.
from paths import (  # noqa: E402
    CAVER_CONFIG, CAVER_HOME, CAVER_JAR, CAVER_LIB, CHANNEL_ROOT,
)

HEME_NAMES = {"HEM", "HEME", "HEC", "HEA", "HEB", "HEG", "HDD", "HAS"}

# Kept when stripping a structure down to "the channel itself". The heme is the
# anchor CAVER measures from, and crystallographic metals/ions are part of the
# fold — only the substrate is removed.
WATER_NAMES = {"HOH", "WAT", "H2O", "DOD"}
ION_NAMES = {"MG", "CL", "ZN", "CA", "NA", "K", "MN", "CU", "FE", "NI", "CO",
             "SO4", "PO4", "GOL", "EDO", "ACT"}
# NOTE: XE is deliberately absent. The channel placeholder is written as xenon
# (see write_channel_placeholder), and it MUST be stripped before measuring —
# otherwise CAVER sees the dummy atoms filling the tunnel and reports a
# collapsed channel. Adding "XE" here would silently break every measurement of
# an RFD3 output that used a placeholder.
COFACTOR_NAMES = HEME_NAMES | ION_NAMES | WATER_NAMES

# Every structure is staged under this one filename before CAVER sees it.
# See the note in run_caver: CAVER's output depends on the input filename.
CANONICAL_PDB_NAME = "structure.pdb"


# ── input preparation ────────────────────────────────────────────────────────

def find_heme_fe(pdb_path):
    """Return (fe_xyz, protein_chain, max_resnum), or (None, None, None).

    Same anchoring rule the channel_discovery batch runner uses: the channel is
    defined relative to the heme iron, so a structure without one cannot be
    analysed here.
    """
    fe = None
    chain = None
    max_res = 0
    with open(pdb_path) as f:
        for line in f:
            if line.startswith("HETATM"):
                if (line[17:21].strip() in HEME_NAMES
                        and line[12:16].strip() in ("FE", "FE2", "FE3")):
                    fe = (float(line[30:38]), float(line[38:46]), float(line[46:54]))
            elif line.startswith("ATOM"):
                chain = line[21]
                try:
                    max_res = max(max_res, int(line[22:26]))
                except ValueError:
                    pass
    if fe is None or chain is None:
        return None, None, None
    return fe, chain, max_res


def substrate_resnames(pdb_path):
    """HETATM residue names that are neither cofactor, ion, nor water.

    In practice this is the docked substrate. Used to measure the channel
    APO — i.e. how wide the opening is, rather than how much gap is left
    beside a ligand sitting in it.
    """
    found = set()
    with open(pdb_path) as f:
        for line in f:
            if line.startswith("HETATM"):
                rn = line[17:20].strip()
                if rn and rn not in COFACTOR_NAMES:
                    found.add(rn)
    return found


def strip_resnames_from_pdb(pdb_path, out_path, resnames):
    """Copy a PDB with the given residue names dropped. Returns atoms removed.

    Both the parent and every design MUST be stripped the same way, or the
    comparison measures ligand occupancy instead of channel shape.
    """
    resnames = {r.upper() for r in resnames}
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    removed = 0
    with open(out_path, "w") as out:
        for line in open(pdb_path):
            if line[:6] in ("ATOM  ", "HETATM") and line[17:20].strip().upper() in resnames:
                removed += 1
                continue
            out.write(line)
    return removed


def write_pdb_with_fe_atom(pdb_path, out_path, fe, chain, max_res):
    """Copy the PDB, appending a synthetic ATOM record for the Fe.

    CAVER's starting_point_residue only resolves ATOM records, so the heme iron
    (a HETATM) has to be restated as one. Returns (resnum_str, chain).
    """
    fe_res = max_res + 1
    fx, fy, fz = fe
    fe_line = (f"ATOM  {9999:5d}  FE  FEX {chain}{fe_res:4d}    "
               f"{fx:8.3f}{fy:8.3f}{fz:8.3f}  1.00  0.00          FE  \n")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.is_symlink() or out_path.exists():
        out_path.unlink()

    with open(out_path, "w") as out:
        for line in open(pdb_path):
            if line.strip() in ("END", ""):
                continue
            out.write(line)
        out.write(fe_line)
        out.write("END\n")
    return str(fe_res), chain


def make_config(out_path, res_num, chain, probe_radius=None):
    """Write a per-structure CAVER config with residue reporting forced ON."""
    lines = CAVER_CONFIG.read_text().splitlines(keepends=True)
    out, seen = [], set()

    def setting(key, value):
        seen.add(key)
        return f"{key} {value}\n"

    for line in lines:
        if re.match(r"\s*starting_point_residue\b", line):
            out.append(setting("starting_point_residue", f"    {res_num} {chain}"))
        elif re.match(r"\s*compute_tunnel_residues\b", line):
            out.append(setting("compute_tunnel_residues", "yes"))
        elif re.match(r"\s*compute_bottleneck_residues\b", line):
            out.append(setting("compute_bottleneck_residues", "yes"))
        elif probe_radius is not None and re.match(r"\s*probe_radius\b", line):
            out.append(setting("probe_radius", str(probe_radius)))
        else:
            out.append(line)

    for key, value in (("starting_point_residue", f"{res_num} {chain}"),
                       ("compute_tunnel_residues", "yes"),
                       ("compute_bottleneck_residues", "yes")):
        if key not in seen:
            out.append("\n" + setting(key, value))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(out))
    return out_path


# ── running ──────────────────────────────────────────────────────────────────

def run_caver(pdb_path, work_dir, probe_radius=None, quiet=True, strip=None):
    """Run CAVER on one structure. Returns the output dir, or None on failure.

    work_dir gets  pdb/  (the Fe-augmented input CAVER reads),  config.txt,
    and  out/  (CAVER's own output tree).

    strip — residue names to remove first. Pass "auto" to drop whatever docked
    substrate is present (see substrate_resnames) and measure the channel APO.
    A bound ligand narrows the tunnel by far more than the differences between
    structures, so this must be consistent across everything being compared.
    """
    pdb_path = Path(pdb_path)
    work_dir = Path(work_dir)
    pdb_in   = work_dir / "pdb"
    out_dir  = work_dir / "out"

    if strip:
        names = substrate_resnames(pdb_path) if strip == "auto" else set(strip)
        if names:
            stripped = work_dir / "stripped" / pdb_path.name
            n = strip_resnames_from_pdb(pdb_path, stripped, names)
            if not quiet:
                print(f"  stripped {n} atom(s) of {', '.join(sorted(names))} "
                      f"— measuring channel apo")
            pdb_path = stripped

    fe, chain, max_res = find_heme_fe(pdb_path)
    if fe is None:
        if not quiet:
            print(f"  no heme Fe in {pdb_path.name} — cannot anchor the channel")
        return None

    # Stage under a FIXED name, never the structure's own. CAVER 3.0 returns a
    # measurably different tunnel set for byte-identical input when the file is
    # named differently — 0.09 A of spread in bottleneck radius across 8 names
    # here, larger than the spread between real UPO crystal structures. Same
    # bytes + same name is perfectly reproducible, so holding the name constant
    # removes the nuisance variable while leaving real structural differences
    # fully resolved.
    staged = pdb_in / CANONICAL_PDB_NAME
    res_num, fe_chain = write_pdb_with_fe_atom(pdb_path, staged, fe, chain, max_res)
    config = make_config(work_dir / "config.txt", res_num, fe_chain, probe_radius)
    out_dir.mkdir(parents=True, exist_ok=True)

    # CAVER reads EVERY pdb in -pdb; a leftover from a previous run in this
    # work dir would be silently treated as another trajectory frame.
    for stray in pdb_in.glob("*.pdb"):
        if stray.name != CANONICAL_PDB_NAME:
            stray.unlink()

    proc = subprocess.run(
        ["java", "-Xmx1200m", "-cp", str(CAVER_LIB), "-jar", str(CAVER_JAR),
         "-home", str(CAVER_HOME), "-pdb", str(pdb_in),
         "-conf", str(config), "-out", str(out_dir)],
        capture_output=True, text=True,
    )

    log = out_dir / "log.txt"
    ok = log.exists() and ("Finished successfully" in log.read_text()
                           or "Calculation finished" in log.read_text())
    if not ok and not quiet:
        print(f"  CAVER failed on {pdb_path.name} — see {log}")
        if proc.stderr:
            print("  " + proc.stderr.strip().splitlines()[-1])
        return None
    return out_dir if ok else None


# ── reading results ──────────────────────────────────────────────────────────

def read_tunnels(out_dir):
    """Return [{tunnel, cluster, bottleneck_radius, length, throughput, curvature}],
    sorted by throughput descending (CAVER's own notion of 'best channel')."""
    path = Path(out_dir) / "analysis" / "tunnel_characteristics.csv"
    if not path.exists():
        return []

    rows = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f, skipinitialspace=True):
            def num(key):
                try:
                    return float(row.get(key, "").strip())
                except (ValueError, AttributeError):
                    return None
            try:
                tid = int(row["Tunnel"].strip())
            except (KeyError, ValueError):
                continue
            rows.append({
                "tunnel":            tid,
                "cluster":           row.get("Tunnel cluster", "").strip(),
                "bottleneck_radius": num("Bottleneck radius"),
                "length":            num("Length"),
                "throughput":        num("Throughput"),
                "curvature":         num("Curvature"),
            })
    rows.sort(key=lambda r: (r["throughput"] is None, -(r["throughput"] or 0)))
    return rows


def best_tunnel(out_dir, max_length=None, max_curvature=None):
    """The highest-throughput tunnel, optionally restricted to sane geometry.

    The filters exist because CAVER happily reports long meandering crevices
    that are not the substrate channel; the defaults in channel_discovery's
    batch runner (length <= 25 A, curvature <= 1.5) are the same idea.
    """
    for t in read_tunnels(out_dir):
        if max_length is not None and (t["length"] or 0) > max_length:
            continue
        if max_curvature is not None and (t["curvature"] or 0) > max_curvature:
            continue
        return t
    return None


def protein_resnums(pdb_path, chain="A"):
    """Residue numbers of the protein (ATOM records) on one chain.

    Used to drop cofactors from CAVER's lining list: the heme, metals and the
    synthetic FEX marker all line the channel, but none of them are residues
    you can make flexible.
    """
    nums = set()
    with open(pdb_path) as f:
        for line in f:
            if line.startswith("ATOM") and line[21] == chain:
                try:
                    nums.add(int(line[22:26]))
                except ValueError:
                    pass
    return nums


def read_lining_residues(out_dir, tunnel_cluster=1, keep_resnums=None):
    """Parse analysis/residues.txt for one tunnel cluster.

    Returns {"sidechain": [...], "backbone": [...]} of residue numbers.

    The distinction matters for how you widen the channel:
      sidechain-lining  — MPNN can swap the residue for a smaller one
      backbone-only     — the wall is the mainchain itself, so only RFD3
                          moving that backbone will ever open it

    keep_resnums — if given, restrict to these residue numbers. Pass
    protein_resnums(pdb) to exclude heme/metal/FEX entries.
    """
    path = Path(out_dir) / "analysis" / "residues.txt"
    if not path.exists():
        return {"sidechain": [], "backbone": []}

    sidechain, backbone = [], []
    in_block = False
    header = re.compile(r"==\s*Tunnel cluster\s+(\d+)\s*==")

    for line in path.read_text().splitlines():
        m = header.search(line)
        if m:
            in_block = int(m.group(1)) == tunnel_cluster
            continue
        if not in_block or line.startswith("#") or not line.strip():
            continue
        parts = line.split()
        # C  res  AA  N  sideN  atoms...
        if len(parts) < 5:
            continue
        try:
            resnum = int(parts[1])
            side_n = int(parts[4])
        except ValueError:
            continue
        if keep_resnums is not None and resnum not in keep_resnums:
            continue
        (sidechain if side_n > 0 else backbone).append(resnum)

    return {"sidechain": sorted(set(sidechain)),
            "backbone":  sorted(set(backbone))}


def read_tunnel_path(out_dir, tunnel_id):
    """Return [(x, y, z, r), ...] along the tunnel axis, or [] if unavailable."""
    path = Path(out_dir) / "analysis" / "tunnel_profiles.csv"
    if not path.exists():
        return []

    axes = {}
    for axis in ("X", "Y", "Z", "R"):
        axes[axis] = _profile_row(path, tunnel_id, axis)
    if any(not v for v in axes.values()):
        return []

    n = min(len(v) for v in axes.values())
    return [(axes["X"][i], axes["Y"][i], axes["Z"][i], axes["R"][i])
            for i in range(n)]


def _profile_row(csv_path, tunnel_id, axis):
    """One row of tunnel_profiles.csv — the values for a given tunnel and axis."""
    with open(csv_path, newline="") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            row = [c.strip() for c in row]
            if len(row) < 13:
                continue
            try:
                if int(row[2]) != tunnel_id:
                    continue
            except ValueError:
                continue
            if row[12] == axis:
                return [float(v) for v in row[13:] if v and v != "-"]
    return []


# ── channel placeholder ──────────────────────────────────────────────────────

def write_channel_placeholder(path_points, out_pdb, resname="XE", chain="D",
                              spacing=1.5, shrink=0.0, element="XE"):
    """Write the tunnel axis as a chain of MONATOMIC pseudo-ligands.

    Fed to RFD3 as fixed ligand context, these occupy the channel volume so the
    denoiser packs the protein AROUND an open channel rather than collapsing
    into the void. Without them nothing in partial diffusion rewards keeping a
    tunnel open, and compact-packing wins every time.

    Each point is its OWN single-atom residue, which is the whole trick. Writing
    all N points as one multi-atom residue makes RFD3 look that residue name up
    in the CCD and try to broadcast our N tunnel points onto the template's fixed
    atom count and internal geometry:

        ValueError: could not broadcast input array from shape (9,3) into (6,3)

    A monatomic component has exactly one atom, so the count always matches and
    there is no internal geometry to violate. Xenon is the natural choice — it is
    what crystallographers actually soak into proteins to map hydrophobic
    cavities, so a row of Xe along the tunnel axis is a physically meaningful
    "keep this volume open" restraint rather than an invented residue.

    spacing  — minimum gap (A) between placed atoms; CAVER samples the axis far
               more finely than a ligand needs, so points are thinned.
    shrink   — subtract this from each sphere radius before deciding to keep a
               point. Raising it places atoms only where the channel is already
               wide, which biases toward widening the narrow parts rather than
               freezing the current shape.
    """
    kept = []
    for (x, y, z, r) in path_points:
        if r - shrink <= 0:
            continue
        if kept and math.dist((x, y, z), kept[-1][:3]) < spacing:
            continue
        kept.append((x, y, z, r))

    if not kept:
        return None, 0

    out_pdb = Path(out_pdb)
    out_pdb.parent.mkdir(parents=True, exist_ok=True)
    # Two-letter element symbols start in column 13; one-letter ones in 14.
    name = f"{element:<4s}" if len(element) == 2 else f" {element:<3s}"
    with open(out_pdb, "w") as f:
        for i, (x, y, z, r) in enumerate(kept, start=1):
            # Strict PDB columns. Getting these wrong by even one character
            # makes every fixed-column parser (RFD3's included) read garbage:
            #  7-11 serial | 13-16 name | 18-20 resName | 22 chain | 23-26 resSeq
            #  31-38 x | 39-46 y | 47-54 z | 55-60 occ | 61-66 B | 77-78 element
            # resSeq is i, not 1: one residue per point (see the docstring).
            f.write(f"HETATM{i:5d} {name:<4s} {resname:>3s} {chain:1s}{i:4d}    "
                    f"{x:8.3f}{y:8.3f}{z:8.3f}{1.00:6.2f}{r:6.2f}"
                    f"{'':10s}{element:>2s}\n")
        f.write("END\n")
    return out_pdb, len(kept)


def append_placeholder_to_pdb(base_pdb, placeholder_pdb, out_pdb):
    """Merge a placeholder pseudo-ligand into a copy of the input structure.

    Two things here are load-bearing, both learned from RFD3 rejecting the file:

    1. The placeholder's atom serial numbers are RENUMBERED to continue from the
       base structure's highest serial. Written as-is they restart at 1, so the
       merged file's serials run 1..2683 then 1..9 — and biotite (which RFD3
       parses with) raises "Atom IDs are not strictly increasing" and the whole
       job dies in under a minute.
    2. Coordinate records must come before the trailing CONECT/MASTER/END block.
       Appending after CONECT leaves bond records pointing into the middle of the
       file, which is malformed even when the serials are fine.
    """
    out_pdb = Path(out_pdb)
    out_pdb.parent.mkdir(parents=True, exist_ok=True)

    coord_recs, trailing, max_serial = [], [], 0
    for ln in Path(base_pdb).read_text().splitlines(keepends=True):
        rec = ln[:6]
        if rec in ("ATOM  ", "HETATM"):
            try:
                max_serial = max(max_serial, int(ln[6:11]))
            except ValueError:
                pass
            coord_recs.append(ln)
        elif rec == "TER   ":
            coord_recs.append(ln)
        elif ln.strip() in ("END", ""):
            continue
        elif rec in ("CONECT", "MASTER"):
            trailing.append(ln)
        else:
            coord_recs.append(ln)

    placed = []
    for ln in Path(placeholder_pdb).read_text().splitlines(keepends=True):
        if not ln.startswith("HETATM"):
            continue
        max_serial += 1
        # Columns 7-11 are the serial; splice a renumbered one in, leaving every
        # other column byte-identical.
        placed.append(f"{ln[:6]}{max_serial:5d}{ln[11:]}")

    out_pdb.write_text("".join(coord_recs + placed + trailing) + "END\n")
    return out_pdb


def caver_available():
    """True if CAVER can actually run here (jar present and java on PATH)."""
    return CAVER_JAR.exists() and shutil.which("java") is not None
