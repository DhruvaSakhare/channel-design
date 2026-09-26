# Known issues and traps

Things that are wrong, or that will waste your time, written down because each
one already cost somebody a run. Every claim here was verified against files or
coordinates, and the check is included so you can confirm rather than trust.

---

## 1. `channel_discovery/` does not strip the substrate

The two measurement rules in [docs/validation.md](docs/validation.md) are
enforced in `enzyme_design/lib/caver_utils.py`. They are **not** fixed in
`channel_discovery/` itself: `cif_to_pdb.py` removes only water, and
`run_batch.py` does not stage structures under a constant filename.

**Consequence:** a run driven from `channel_discovery/` that compares designs
against the bundled reference crystals still carries both artifacts — a ~0.45 Å
apo/holo offset and up to 0.0885 Å of filename-dependent noise, against a real
between-structure signal of 0.077 Å.

**If you are measuring channels, go through the design-side wrapper.** Fixing
this properly means moving the staging rules into `caver_pipeline/` so both
entry points share them.

---

## 2. A substrate written as `ATOM` is invisible

`mroupo_nnbt_docked_clean.pdb` and `mroupo_nnbt_fixed.pdb` differ **only** in
record type. Atom names, chains and chain A numbering are identical.

```bash
cd enzyme_design/inputs
for f in mroupo_nnbt_docked_clean.pdb mroupo_nnbt_fixed.pdb; do
  echo -n "$f: "; grep " UNL " "$f" | cut -c1-6 | sort -u | tr '\n' ' '; echo
done
# mroupo_nnbt_docked_clean.pdb: ATOM
# mroupo_nnbt_fixed.pdb:        HETATM
```

Every ligand-aware step keys on `HETATM`, so in `docked_clean` the substrate is
silently treated as protein. **CAVER finds 0 tunnels there and 40 in the fixed
file** (best bottleneck 1.058 Å). `--trim` would have dropped the substrate
entirely.

`config_mroupo_nnbt.py` pointed at the broken file and now points at the fixed
one. `tests/test_input_structures.py` asserts this for every shipped config.
Use `enzyme_design/partial_diffusion/scripts/fix_pdb_chains.py` to repair a
structure of your own.

---

## 3. A residue in both `_CATALYTIC_PINS` and `FLEXIBLE_RESIDUES` gets no pin

`_build_fixed_atoms` applies the catalytic pin only to residues **not** in the
flexible list:

```python
return {f"{chain}{r}": _CATALYTIC_PINS.get(r, "N,CA,C,O")
        for r in _chain_resids(pdb_path, chain) if r not in flex}
```

So a residue named in both gets **zero** pinning — full backbone freedom in
RFD3, not the protected sidechain geometry the comment beside it implies. The
pin is dead code, and it looks like the opposite.

Worse in combination: if that residue is also in `SHRINK_RESIDUES`, then
`OMIT_AA_AT_SHRINK` is actively forbidding the amino acid whose job the comment
describes. A residue annotated "orients substrate toward heme" can be barred
from being a phenylalanine.

**Check your own config before running:** list residues appearing in both
`_CATALYTIC_PINS` and `FLEXIBLE_RESIDUES`, and decide deliberately.

---

## 4. Verify MPNN flags against the installed build, not the public docs

The deployed `mpnn` may be a custom build whose flag names differ from public
LigandMPNN. Following the public documentation cost us a full 10-backbone MPNN
stage — all ten calls died with `unrecognized arguments`.

Test that a constraint actually constrains, by forbidding the residue's **own
native type**. If the mechanism works, that type cannot come back:

```bash
mpnn --seed 42 --structure_path "$BACKBONE" --out_directory /tmp/omit_test \
    --batch_size 1 --number_of_batches 1 --model_type ligand_mpnn \
    --checkpoint_path "$MPNN_CKPT" --is_legacy_weights True \
    --omit_per_residue '{"A160": ["PHE"]}'
```

Exit 0 plus a non-PHE residue at 160 means it works. Testing with a type the
residue was not going to pick anyway proves nothing — that was our first
mistake.

---

## 5. Some "failed" jobs actually succeeded

`caver_filter` and `rf3_prep` report `signal 9` / `TERM_EXTERNAL_SIGNAL` while
completing their work: the job scripts' cleanup loop takes down the shell
before `exit 0`. **Check whether the output files exist before assuming a
failure** and re-running an expensive stage.

---

## 6. `MPNN_TEMPERATURE` at the default makes every design identical

LigandMPNN defaults to 0.1, which is effectively argmax. With ~300 of 335
positions pinned, the few free positions get the same residue almost every
time, and N sequences per backbone collapse to a handful of distinct ones.

`0.25` is the shipped default here. Raise it to explore the channel lining;
above ~0.5 expect more RF3 fold failures.

---

## 7. Nothing in the objective rewards keeping the channel open

RFD3 packs protein, and an empty channel is a void — compact packing wins. A
dummy-atom placeholder to occupy the bore was tried and is currently **off** by
choice, after three rounds of bug fixes (column alignment, atom-serial
ordering, and `TUN` turning out to be a real 6-atom CCD code).

`SHRINK_RESIDUES` is the cleaner lever. This is the most important open
question in the method: see
[`CHANNEL_WIDENING_LOG.md`](enzyme_design/partial_diffusion/CHANNEL_WIDENING_LOG.md).

---

## Open work

1. Finish rescoring all 174 `channel_01` designs — the current result rests on
   a correlated sample of 20.
2. Compare `channel_02` (32 flexible) against `channel_01`. If the pass rate
   holds but the median gain does not, the constriction is backbone-limited and
   the next lever is `PARTIAL_T`, not more residues.
3. Measure the residual noise between near-identical structures. `--noise 0.02`
   in `08_probe_channel.py` is still a guess.
4. Move the apo/holo and filename-staging rules into `caver_pipeline/` so both
   entry points share them (issue 1).
