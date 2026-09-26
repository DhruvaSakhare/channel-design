# inputs/ — your structures go here

This directory is **deliberately empty**. It is yours.

Put your prepared enzyme PDB here, and `00_make_msa.py` will write its
alignment alongside it. Nothing in this directory is tracked by git except
this file, so your structures stay local unless you choose to commit them.

Our own structures — the ones the bundled example configs use — live in
[`../examples/`](../examples/) instead, so that they never get mixed up with
yours.

## What a prepared structure looks like

1. Solvent and non-essential HETATMs removed
2. Heme on its own chain (e.g. chain B)
3. Substrate on its own chain (e.g. chain C), positioned ~4–5 Å above the iron
4. **Every ligand on a unique chain, separate from the protein**
5. **Ligands written as `HETATM`, not `ATOM`** — a substrate written as `ATOM`
   is invisible to every ligand-aware step, and CAVER will find no tunnel at
   all. See [KNOWN_ISSUES.md](../../KNOWN_ISSUES.md#2-a-substrate-written-as-atom-is-invisible).

`../partial_diffusion/scripts/fix_pdb_chains.py` does the chain surgery if
your file needs it.

## Getting started

```bash
cp my_enzyme.pdb inputs/
python partial_diffusion/scripts/00_make_msa.py --pdb inputs/my_enzyme.pdb
```

Then copy `../partial_diffusion/config_template.py` to
`../partial_diffusion/config.py`, point `INPUT_PDB` at your file, and edit the
tagged lines. The MSA is discovered automatically by filename.
