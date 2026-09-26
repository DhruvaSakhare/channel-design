# Data formats and interoperability

## There is no SBOL here, and that is not an oversight

This project does not use SBOL, SynBioHub, GenBank or any iGEM RFC, and we are
not going to claim otherwise.

The reason is that this is structural protein engineering, not genetic circuit
design. Every object the pipeline handles is a set of atomic coordinates, an
alignment, or a small molecule. SBOL describes genetic parts and their
composition, and it has no representation for "the bottleneck radius of a
substrate access tunnel" or "these 22 residues may move during diffusion". The
DNA constructs encoding these designs are real, but they live in the team's
wet-lab parts registry entries, not in this repository.

What we can claim is the thing that actually matters for reuse: **every
interface in this pipeline is a community-standard format, and none of them is
bespoke.** That is why the four components chain together at all, and why you
can cut into the workflow at any point with your own tools.

## Formats at every boundary

| format | standard | where |
|---|---|---|
| **PDB** | wwPDB | structures in and out of every stage |
| **mmCIF / PDBx** | wwPDB | RF3 and Boltz-2 output; converted for CAVER by `cif_to_pdb.py` |
| **FASTA** | de facto | sequence input to Boltz-2; accession is the first whitespace token |
| **A3M** | HH-suite / ColabFold | multiple sequence alignments from MMseqs2 |
| **SMILES** | Daylight | substrate definition in configs and Boltz templates |
| **PDB CCD** | RCSB Chemical Component Dictionary | cofactors by three-letter code — `HEM`, `CU`, `CU1`, `ZN`, `MG`, `NAD`, `FAD` |
| **SDF / MDL molfile** | MDL | substrates for docking |
| **PDBQT** | AutoDock | receptor and ligand for Vina |
| **CSV** | RFC 4180 | every table |
| **YAML** | YAML 1.2 | Boltz-2 job definitions |

## Named columns, not positional ones

Every table this project writes has a header, and every table it reads is
addressed by column name. `cluster_affinity_violin.py` validates that the
columns it needs are present and, if one is missing, exits with an error that
lists what it actually found:

```
ERROR: column 'ligand_iptm' not found in boltz_summary.csv.
Available: accession, status, seq_len, confidence_score, ...
```

That is the interoperability claim with teeth: you can rename a column, feed in
a table from a different tool, or point the script at your own predictions with
`--iptm-col` / `--affinity-col`, and you find out immediately rather than
getting a silently empty join.

## The one contract between components

Boltz-2 and the channel clustering were written separately and meet at a CSV:

| producer | `boltz/boltz_template_batch.py` writes `boltz_<template>_summary.csv` |
|---|---|
| **consumer** | `channel_discovery/caver_pipeline/python_scripts/cluster_affinity_violin.py` |
| **key** | `accession` (from the FASTA header) joined against `stem` in `cluster_assignments.csv` |
| **filter** | `ligand_iptm >= 0.8` |
| **value** | `affinity_pred_value` |

Because that contract is a plain CSV and not a function call, **any affinity
predictor can be substituted for Boltz-2.** Emit those three columns and the
rest of the workflow is unchanged. `tests/test_affinity_contract.py` is what
keeps the two halves honest.

## External identifiers and services

The pipeline consumes public identifiers rather than inventing its own:

- **RCSB PDB accessions** — 5FUJ, 5OXU and 9HE9 are appended to every
  clustering run as calibration anchors, so "this design clusters with 5OXU" is
  a statement made against public reference data.
- **UniProt / NCBI accessions** carry through from FASTA headers to every
  output table as the join key.
- **PDB Chemical Component Dictionary** codes for all cofactors.
- **ColabFold / MMseqs2** (`api.colabfold.com`) for alignments.
- **CUPP** clade assignments, consumed by `cluster_clade_heatmap.py`.
- **SignalP 6.0** for signal-peptide trimming before folding.
