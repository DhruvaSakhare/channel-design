# Known issues

Things that will break a run or quietly give a wrong answer.

## 1. Old `channel_discovery/` results are not comparable with new ones

`run_batch.py` used to keep the substrate and name the staged file after the
input, adding an apo/holo offset plus filename-dependent noise, each larger
than the real difference between structures
([docs/validation.md](docs/validation.md)). It now measures apo under a constant
filename, and `--skip-existing` **exits** rather than reuse a pre-staging
`results/` directory, so the two can no longer end up in one table. Delete the
old directory and rerun. `--keep-substrate` restores the old behaviour; never
compare the two. The new path is tested but has not been run against real
CAVER.

## 2. On an unfamiliar structure, name the substrate

Measuring apo means removing the substrate, and with no `--substrate` the code
identifies it by elimination: every `HETATM` residue that is not a known
cofactor, ion, water, glycan, modified amino acid or buffer. The keep lists in
`staging.py` cover what turns up on UPO crystals, not everything the PDB
contains, so an unfamiliar residue is still removed.

Removing too much is the dangerous direction, because a hole in the structure
reads as extra channel width. A modified amino acid such as `MSE` or `CSO` is
the worst case: it sits *in* the backbone. `run_batch.py` warns when it strips
a named CCD component rather than a docking placeholder (`UNL`, `UNK`, `LIG`),
but a warning is not a guarantee. Pass the name instead and the guess goes
away:

```bash
00_caver_channel.py <pdb> --substrate UNL
run_batch.py --substrate UNL
```

`07_caver_rescore.py` and `02b_caver_filter.py` take it from the config's
`SUBSTRATE_NAME` automatically. Every script prints what it stripped — read
that line on a structure you have not measured before.

## 3. A substrate written as `ATOM` is invisible

Ligand-aware steps key on `HETATM`, so a substrate written as `ATOM` is treated
as protein. CAVER found 0 tunnels in `mroupo_nnbt_docked_clean.pdb` and 40 in
`mroupo_nnbt_fixed.pdb`, which differ only in record type.

`00_prep_pdb.py --check` now names any non-amino-acid residue it finds on an
`ATOM` line, so run it on a new structure before anything else. Repair with
`enzyme_design/partial_diffusion/scripts/fix_pdb_chains.py`.
`tests/test_input_structures.py` keeps shipped configs off such a file.

## 4. A residue in both `_CATALYTIC_PINS` and `FLEXIBLE_RESIDUES` gets no pin

`_build_fixed_atoms` pins only residues *not* in the flexible list, so a residue
in both gets full backbone freedom — the opposite of what the annotation beside
it implies. If it is also in `SHRINK_RESIDUES`, its own amino acid can be
forbidden too.

**Now enforced:** `01_rfd3_partial_submit.py` exits before any GPU time if the
two lists overlap, `03_mpnn_submit.py` does the same for `SHRINK_RESIDUES`, and
`tests/test_configs.py` fails if a shipped config has the overlap.

## 5. Two different MPNN command lines exist

`dauparas/LigandMPNN` uses `--omit_AA_per_residue` (a file); RosettaCommons
`foundry` uses `--omit_per_residue` (inline JSON). This pipeline uses foundry's.
Reading the wrong docs killed a full MPNN stage with `unrecognized arguments`.

## 6. Some "failed" jobs actually succeeded

`caver_filter` and `rf3_prep` can report `signal 9` / `TERM_EXTERNAL_SIGNAL`
after finishing, because the cleanup loop kills the shell before `exit 0`.
Check whether the output files exist before re-running an expensive stage.

## 7. There is no default queue

`00_submit_all.py` exits 2 until you set `PIPELINE_QUEUE` (or `--queue`) and
`PIPELINE_CPU_QUEUE` (or `--cpu-queue`). Names come from `bqueues`. `--dry-run`
and `run_local.py` do not need one.
