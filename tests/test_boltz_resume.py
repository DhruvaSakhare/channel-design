"""
Resuming a Boltz batch must not duplicate rows.

The driver appended to the summary CSV, and --resume re-collects metrics for
every accession that is already finished. Each resume therefore added another
row per accession, and because cluster_affinity_violin.py aggregates that CSV
without deduplicating, a twice-resumed run silently counted every structure
three times. The fix rewrites the summary instead of appending; this test is
what stops it regressing.

No GPU and no Boltz install: a finished run is faked on disk, so only the
resume path is exercised.
"""
import csv
import importlib.util
import json
import sys

from conftest import REPO_ROOT

spec = importlib.util.spec_from_file_location(
    "btb", REPO_ROOT / "boltz" / "boltz_template_batch.py")
btb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(btb)

ACCESSIONS = ("UPO_001", "UPO_002")


def _fake_completed_run(out_dir, accession):
    """Write what Boltz leaves behind, so --resume treats it as finished."""
    pred = out_dir / accession / "boltz_out" / "predictions" / accession
    pred.mkdir(parents=True, exist_ok=True)
    (pred / f"confidence_{accession}_model_0.json").write_text(json.dumps({
        "confidence_score": 0.91, "ptm": 0.88, "iptm": 0.90,
        "ligand_iptm": 0.92, "protein_iptm": 0.89,
        "complex_plddt": 0.93, "complex_iplddt": 0.90,
    }))
    (pred / f"affinity_{accession}.json").write_text(json.dumps({
        "affinity_pred_value": -1.85, "affinity_probability_binary": 0.81,
    }))
    (pred / f"{accession}_model_0.pdb").write_text(
        "ATOM      1  N   MET A   1      0.000   0.000   0.000  1.00  0.00           N\nEND\n")


def _resume(tmp_path, fasta, template):
    argv = sys.argv
    sys.argv = ["boltz_template_batch.py", "-f", str(fasta), "-t", str(template),
                "-o", str(tmp_path / "out"), "--resume"]
    try:
        btb.main()
    finally:
        sys.argv = argv


def test_repeated_resume_writes_one_row_per_accession(tmp_path):
    fasta = tmp_path / "in.fasta"
    fasta.write_text("".join(
        f">{acc} example\nMKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ\n" for acc in ACCESSIONS))
    template = REPO_ROOT / "boltz" / "templates" / "heme_nnbt.yaml"

    out_dir = tmp_path / "out"
    for acc in ACCESSIONS:
        _fake_completed_run(out_dir, acc)

    for _ in range(3):
        _resume(tmp_path, fasta, template)

    summary = out_dir / "boltz_heme_nnbt_summary.csv"
    with open(summary, newline="") as f:
        rows = list(csv.DictReader(f))

    seen = [r["accession"] for r in rows]
    assert sorted(seen) == sorted(ACCESSIONS), (
        f"three resumes should leave one row per accession, got {seen}")
    assert all(r["status"] == "ok" for r in rows)
    assert all(r["ligand_iptm"] for r in rows), "metrics were not re-collected"


def test_resume_keeps_rows_for_accessions_absent_from_this_fasta(tmp_path):
    """A narrower re-run must not silently delete earlier results."""
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True)
    summary = out_dir / "boltz_heme_nnbt_summary.csv"
    with open(summary, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=btb.FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerow({"accession": "UPO_999", "status": "ok", "seq_len": 300})

    fasta = tmp_path / "in.fasta"
    fasta.write_text(">UPO_001 example\nMKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ\n")
    _fake_completed_run(out_dir, "UPO_001")
    _resume(tmp_path, fasta, REPO_ROOT / "boltz" / "templates" / "heme_nnbt.yaml")

    with open(summary, newline="") as f:
        seen = {r["accession"] for r in csv.DictReader(f)}
    assert seen == {"UPO_001", "UPO_999"}, (
        f"earlier result UPO_999 was dropped; got {sorted(seen)}")
