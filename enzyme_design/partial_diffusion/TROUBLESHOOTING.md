# Troubleshooting

Errors you are likely to hit, and what each one actually means. Cluster-only
failures (jobs stuck in PEND, wall-time kills) are in
[CLUSTER.md](CLUSTER.md).

---

## `ValidationError: ligand — Input should be a valid string`
RFD3 expects `ligand` as a comma-separated string, not a list. This is handled
automatically by the scripts — if you see this, make sure you're running the
scripts from this folder, not the parent pipeline's `scripts/`.

## `ValueError: Ligand chain(s) overlap with existing chain(s)`
Your ligands share a chain with the protein. Fix the PDB in PyMOL (see
"Preparing the PDB" above) — each ligand must be on its own unique chain.
The JSON must also include `"allow_ligand_on_existing_chain": true`.

## `Passing backbones: 0 / N`
All backbones failed the chain break filter. For partial diffusion this is
normal at low counts — the filter allows up to 3 chain breaks by default.
Check `scores/rfd3_metrics.csv` for the actual values.
If all designs have many chain breaks, try reducing `PARTIAL_T`.

## `Passing designs: 0 / N` at the scoring stage
Different from the above — the backbones were fine, but nothing cleared
`PLDDT_CUT` / `PAE_CUT` / `IPSAE_CUT`. Check the MSA first, before you touch the
science:
```bash
python -c "import partial_diffusion.config as C; print(C.NATIVE_MSA_PATH or 'SINGLE-SEQUENCE')"
```
If it prints `SINGLE-SEQUENCE` while `PLDDT_CUT` is 0.80+, that alone explains
it — build the MSA (`00_make_msa.py`) or lower the cut to ~0.70. Only if the MSA
was present is a zero count a real result about your `FLEXIBLE_RESIDUES` and
`PARTIAL_T`. `scores/rf3_metrics.csv` has every design's numbers, so you can see
how close they came.

## `00_make_msa.py` uses the wrong enzyme
It reads `INPUT_PDB` from `config.py`. Check the header it prints — the PDB path
and residue count must match the enzyme you mean. When running it standalone
against a non-default config, `export PIPELINE_BASE_CONFIG=partial_diffusion.<module>`
first; the script honours that variable, but only when it is exported in the
*same* shell.

## `No such file or directory: rf3_wrapper.py`
The RF3 wrapper path is wrong. In `04_rf3_submit.py`, make sure it reads:
```python
rf3_wrapper = C.LIB_ROOT / "rf3_wrapper.py"
```
not `C.PIPELINE_ROOT / "lib" / "rf3_wrapper.py"`.

## `mpnn: error: argument --fixed_residues: not allowed with argument --designed_chains`
LigandMPNN treats `--fixed_residues`, `--designed_residues`, `--fixed_chains`
and `--designed_chains` as mutually exclusive. The scripts pass only
`--fixed_residues` (comma-separated, e.g. `A72,A73,A244`). If you edit the mpnn
command, don't add a `--designed_chains` flag alongside it.

## `mpnn: ID 'A72 A73 ...' must look like '<letters><number>'`
The `--fixed_residues` value must be **comma-separated**, not space-separated —
this mpnn build splits on commas. Handled by `03_mpnn_submit.py` already.

## `json.decoder.JSONDecodeError: Expecting value: line 1 column 1`
`config.py` couldn't read `<WORK>/configs/run_config.json` — it was empty or
truncated. Re-run `00_submit_all.py` for that experiment; it rewrites the
snapshot atomically. (This can happen if a previous submit was Ctrl-C'd mid-write.)

