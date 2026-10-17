"""
staging.py — the two rules that make a CAVER number comparable.

Both entry points import this module (channel_discovery's run_batch.py and the
design pipeline's enzyme_design/lib/caver_utils.py), so the rules live in one
place instead of being re-implemented, and drifting, in each. See
docs/validation.md for why each rule exists, and the wiki for the measurements
behind them.

  1. Measure APO. A bound substrate occupies part of the channel, costing
     several times the real spread in bottleneck radius between UPO crystal
     structures. Heme, crystallographic metals and ions are part of the fold
     and are kept; only the substrate is removed.
  2. Stage every structure under ONE filename. CAVER 3.0's randomised tunnel
     search seeds from the input name: byte-identical input under different
     filenames gave a spread larger than the difference between real
     structures, and no spread at all under one filename.

Pure standard library, so it imports (and is tested) without CAVER installed.
"""

from pathlib import Path

HEME_NAMES = {"HEM", "HEME", "HEC", "HEA", "HEB", "HEG", "HDD", "HAS"}

# Kept when stripping a structure down to "the channel itself".
WATER_NAMES = {"HOH", "WAT", "H2O", "DOD"}
ION_NAMES = {"MG", "CL", "ZN", "CA", "NA", "K", "MN", "CU", "FE", "NI", "CO",
             "SO4", "PO4", "GOL", "EDO", "ACT"}

# Glycans. UPOs are glycoproteins, so an N-linked tree is on nearly every real
# UPO crystal. They are part of the protein as crystallised, not a ligand to
# remove.
GLYCAN_NAMES = {"NAG", "NDG", "NGA", "A2G", "BMA", "MAN", "AMA", "GAL", "GLA",
                "GLC", "BGC", "FUC", "FUL", "XYS", "XYP", "SIA", "RAM", "ARA",
                "RIB", "LYX", "MMA"}

# Modified amino acids. These sit IN the backbone: dropping one leaves a hole
# in the chain, which CAVER reads as extra channel.
MODIFIED_AA_NAMES = {"MSE", "CSO", "CSD", "CSS", "CSX", "OCS", "CME", "CMT",
                     "SMC", "SEP", "TPO", "PTR", "TYS", "KCX", "LLP", "MLY",
                     "MLZ", "M3L", "ALY", "HYP", "PCA", "FME", "CGU", "SAC",
                     "ABA", "AIB", "NLE", "ORN", "HIC", "NEP", "HIP", "DAL",
                     "DGL", "SAH", "SAM"}

# Buffers and cryoprotectants from the crystallisation liquor. Not substrate,
# and usually on the surface rather than in the channel.
BUFFER_NAMES = {"PEG", "PG4", "P6G", "1PE", "2PE", "PGE", "MPD", "DMS", "TRS",
                "EPE", "MES", "IMD", "FMT", "ACY", "CIT", "FLC", "TAR", "MLI",
                "OXL", "SIN", "BME", "DTT", "DTU", "TCE", "AZI", "BCT", "NO3",
                "SCN", "IPA", "MOH", "ETA", "URE", "SPD", "SPM", "BU1", "BU3",
                "POL", "PIN", "CAC", "NHE", "TEO", "UNX"}

# NOTE: XE is deliberately absent from every set above. The channel placeholder
# is written as xenon (see caver_utils.write_channel_placeholder), and it MUST
# be stripped before measuring — otherwise CAVER sees the dummy atoms filling
# the tunnel and reports a collapsed channel. Adding "XE" here would silently
# break every measurement of an RFD3 output that used a placeholder.
COFACTOR_NAMES = (HEME_NAMES | ION_NAMES | WATER_NAMES
                  | GLYCAN_NAMES | MODIFIED_AA_NAMES | BUFFER_NAMES)

# Residue names a docking run conventionally gives an unnamed ligand. When
# elimination picks one of these it has almost certainly found the substrate.
# Anything OUTSIDE this set is a named CCD component, which may be the
# substrate or may be a crystallisation additive -- the caller should say which
# it stripped so the difference is visible. See unconventional_substrates().
PLACEHOLDER_SUBSTRATE_NAMES = {"UNL", "UNK", "LIG", "MOL", "DRG", "INH", "SUB"}

# Every structure is staged under this one filename before CAVER sees it.
CANONICAL_PDB_NAME = "structure.pdb"


def unconventional_substrates(resnames):
    """Of `resnames`, the ones elimination should not be trusted on.

    A docked substrate is conventionally UNL/UNK/LIG; a named component such as
    DAO or SLU could equally be a crystallisation additive that belongs in the
    structure. Callers warn on these rather than strip them silently, because
    removing something that should have stayed invents channel width.
    """
    return sorted(n for n in resnames
                  if n.upper() not in PLACEHOLDER_SUBSTRATE_NAMES)


def substrate_resnames(pdb_path, keep=(), substrate=None):
    """Residue names to remove before measuring the channel apo.

    Pass `substrate` (the configured substrate residue name, e.g. "UNL") and
    only that is removed. That is the reliable form: the caller knows what it
    docked, and this function does not have to guess.

    Without it, fall back to naming by elimination — every HETATM residue that
    is not a known cofactor, ion, water, glycan, modified amino acid, buffer or
    cryoprotectant. The keep lists above exist because elimination used to
    delete N-linked glycans and backbone residues like MSE off raw PDB entries
    and call the result "apo".

    Elimination still removes a residue it has never heard of, so it is a
    heuristic, not a guarantee: the lists cover what turns up on UPO crystals,
    not everything the PDB contains. Removing too much is the dangerous
    direction — a hole in the structure reads as extra channel width — so on an
    unfamiliar structure, check what the caller reports it stripped, or name the
    substrate and remove the guess entirely.

    `keep` adds further names that must survive — run_batch passes its extra
    heme alias there.
    """
    keep = {k.upper() for k in keep}
    present = set()
    with open(pdb_path) as f:
        for line in f:
            if line.startswith("HETATM"):
                rn = line[17:20].strip()
                if rn:
                    present.add(rn)

    if substrate is not None:
        want = substrate.strip().upper()
        return {rn for rn in present if rn.upper() == want}

    return {rn for rn in present
            if rn.upper() not in COFACTOR_NAMES and rn.upper() not in keep}


def strip_resnames_from_pdb(pdb_path, out_path, resnames):
    """Copy a PDB with the given residue names dropped. Returns atoms removed.

    Both the parent and every design MUST be stripped the same way, or the
    comparison measures ligand occupancy instead of channel shape.
    """
    resnames = {r.upper() for r in resnames}
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    removed = 0
    with open(pdb_path) as src, open(out_path, "w") as out:
        for line in src:
            if line[:6] in ("ATOM  ", "HETATM") and line[17:20].strip().upper() in resnames:
                removed += 1
                continue
            out.write(line)
    return removed


def clear_stray_pdbs(pdb_dir):
    """Delete every *.pdb in `pdb_dir` except the canonical one.

    CAVER reads EVERY pdb in -pdb, so a file left by an earlier run (for
    instance one staged under its original name, before this module existed)
    would be silently treated as another trajectory frame.
    """
    for stray in Path(pdb_dir).glob("*.pdb"):
        if stray.name != CANONICAL_PDB_NAME:
            stray.unlink()
