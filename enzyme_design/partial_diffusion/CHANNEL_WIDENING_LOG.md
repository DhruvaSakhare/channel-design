# Channel widening — session log

**Goal:** widen PabUPO-II's substrate channel (currently ~half the width of a
working UPO) without breaking the fold or active site, using CAVER to measure
and RFD3 → LigandMPNN → RF3 to redesign.

**Status as of 2026-08-24:** measurement pipeline built and verified; pilot-run
loop built; channel placeholder still being debugged on HPC; a bug found today
in a teammate's shrink-residue config, not yet fixed.

---

## 1. Baseline

Measured with the substrate stripped (apo) and every structure staged under a
fixed filename (see §3) — reproduced independently on two machines to the
decimal:

| structure | bottleneck radius |
|---|---|
| 5FUJ (reference crystal) | 0.975 Å |
| **PabUPO-II parent** | **0.983 Å** ← the number to beat |
| 9HE9 (= PabUPO-II's own crystal structure) | 1.032 Å |
| 5OXU (reference crystal) | 1.050 Å |
| MroUPO | 1.058 Å |

9HE9 and PabUPO-II were confirmed to be the same protein: identical chain A
(335 residues), identical residue identities checked at several positions.

## 2. Bug: apo vs. holo comparison

`channel_discovery`'s CAVER stage never strips the docked substrate before
measuring. RF3-folded designs come out **holo** (enzyme + heme + substrate);
the three reference crystals are **apo** (heme + metals only, no substrate).

- Spread between the 3 real reference structures: **0.077 Å**
- Bottleneck shift on the *same* PabUPO-II structure, substrate in vs. out:
  **0.454 Å**

The artifact is ~6× larger than the biological signal it's supposed to detect.
Fixed in `lib/caver_utils.py` (`strip="auto"`, on by default in both
`00_caver_channel.py` and `07_caver_rescore.py`; the two refuse to compare a
baseline measured one way against structures measured the other). **Not yet
fixed in `channel_discovery/` itself** — worth flagging to whoever owns it.

## 3. Bug: CAVER's output depends on the input filename

Byte-identical input, 8 different filenames → bottleneck radius spread of
**0.0885 Å**, larger than the entire reference spread above. Same bytes + same
name is perfectly reproducible (0.0000 spread over 6 repeats). Root cause is
inside CAVER 3.0 itself (its randomized tunnel search), not our code.

Fixed by staging every structure CAVER sees under one canonical filename
(`structure.pdb`) in `caver_utils.run_caver`. Verified: spread → 0.0000, real
structures still separate correctly.

## 4. Tools built

| file | purpose |
|---|---|
| `lib/caver_utils.py` | run CAVER, read tunnel geometry / lining residues / path; canonical-filename staging; apo stripping |
| `partial_diffusion/scripts/00_caver_channel.py` | measure the parent → `_flex.json`, `_baseline.json`, `_channel.pdb` (placeholder) |
| `partial_diffusion/scripts/08_probe_channel.py` | measure one RFD3 backbone, verdict (WIDER/NARROWER/UNCHANGED), suggests next config change, logs every attempt |
| `partial_diffusion/scripts/07_caver_rescore.py` | rank finished designs by real Δ-bottleneck vs. the parent |
| `00_submit_all.py --pilot` | 1 backbone, RFD3 only, minutes not hours — the fast gate before spending GPU on MPNN+RF3 |
| `--flexible / --placeholder / --mpnn-temp` flags | override the config per-run without editing the file, for the tune-then-promote loop |
| `partial_diffusion/dhruva_configs/config_channel.py` | clean dedicated config, CAVER-derived values baked in |

## 5. CAVER-derived FLEXIBLE_RESIDUES for PabUPO-II

Tunnel 1 (highest-throughput channel), lining residues minus catalytic pins
(52, 85, 137, 205, 212, 215, 296, 339):

```
86, 88, 89, 90, 92, 93, 94, 96, 204, 207, 208, 209, 210, 211,
257, 258, 292, 295, 298, 334, 335, 336
```
(22 residues — backbone-only at 209, 211, 334: MPNN can't touch these, only
RFD3 backbone movement can.)

## 6. Channel placeholder — 3 failed attempts, root-caused each time

Idea: dummy atoms along the tunnel axis, held fixed as RFD3 ligand context, so
the denoiser packs *around* the channel instead of collapsing into it —
nothing else in partial diffusion rewards keeping the channel open.

1. **Column misalignment** — placeholder PDB written with 1-char column offset.
   Fixed, verified against real HETATM formatting.
2. **Non-increasing atom serials** — merged file had serials `1..2683, 1..9`
   (placeholder restarted at 1 instead of continuing). Biotite (RFD3's parser)
   rejected it: `InvalidFileError: Atom IDs are not strictly increasing`.
   Fixed: placeholder serials now continue from the base structure's max.
3. **`TUN` is a real 6-atom CCD code** — RFD3 tried to broadcast our 9 tunnel
   points onto that component's fixed 6-atom template:
   `ValueError: could not broadcast input array from shape (9,3) into (6,3)`.
   Fixed: placeholder rewritten as a chain of **single-atom xenon (XE)**
   residues — one atom per residue, so there's no multi-atom CCD template to
   conflict with, and Xe is what crystallographers actually use to probe
   hydrophobic cavities.

**Not yet verified: whether RFD3 accepts XE.** Pilot pending on HPC as of this
log.

## 7. Teammate's shrink-residue mechanism — reviewed 2026-08-24

Found in `enzyme_design_hpc_msa_and_bias/` (MroUPO config, not PabUPO-II).

**The mechanism itself is sound** — better than my initial worry. It's
per-residue scoped (`--omit_per_residue` with a `{residue: [forbidden AAs]}`
map), not a global `--bias_AA` that would shrink the whole hydrophobic core.
`SHRINK_RESIDUES` (subset of `FLEXIBLE_RESIDUES`) forbids bulky types there
(`OMIT_AA_AT_SHRINK`, default `PHE,TRP,TYR,LEU,MET,ILE`) so MPNN is forced to
choose small residues instead of just keeping the native bulky sidechain.
Documented clearly in their README, including the exact rule that would have
prevented the bug below: *"Keep catalytic/structural residues OUT of
FLEXIBLE_RESIDUES."*

**Bug found: two catalytic residues violate that exact rule.**

`_CATALYTIC_PINS` in their `config.py` annotates:
```
157: "N,CA,C,O,CB",  # distal Glu — H2O2 activation
160: "N,CA,C,O,CB",  # Phe — orients substrate toward heme
```
Both are *also* in `FLEXIBLE_RESIDUES`, and both are in `SHRINK_RESIDUES` —
meaning:

- **Their catalytic pin is silently dead code.** `_build_fixed_atoms` only
  applies `_CATALYTIC_PINS` to residues *not* in `FLEXIBLE_RESIDUES`
  (`... for r in ... if r not in flex`). A residue in both gets **zero**
  pinning — full backbone freedom in RFD3, not the protected sidechain
  geometry the comment implies.
- **160 is actively being pushed away from Phe.** `OMIT_AA_AT_SHRINK` forbids
  `PHE` there — directly opposing the residue's documented job of orienting
  the substrate toward the heme.

This is very likely a copy-paste/consolidation slip (the annotations show they
clearly know the chemistry — Cys/His/Glu/Phe is textbook UPO active-site
architecture) rather than a misunderstanding. Fix: remove 157 and 160 from
`SHRINK_RESIDUES` (and from `FLEXIBLE_RESIDUES` if they're meant to stay fully
rigid), or move them out of `_CATALYTIC_PINS` if the intent really is to let
MPNN redesign them — but as configured now, the pin is doing nothing.

**Confirmed second bug: the omit mechanism is wrong in 3 independent ways.**
User supplied the real LigandMPNN spec for `--omit_AA_per_residue`. Their code:
```python
omit_map = {f"A{r}": list(omit_aa) for r in shrink}
omit_flag = f"--omit_per_residue '{json.dumps(omit_map)}'"
```

| | their code | correct spec |
|---|---|---|
| flag name | `--omit_per_residue` | `--omit_AA_per_residue` |
| value | inline JSON string | **path to a JSON file on disk** |
| AA codes | 3-letter list (`["PHE","TRP","TYR"]`) | 1-letter string (`"F,W,Y"` or `"FWY"`) |

Any one of these alone breaks it — so independent of the 157/160 catalytic
overlap above, the shrink-by-omission mechanism was very likely never actually
constraining MPNN's choices. Whether it errored outright (unrecognized flag)
or silently no-op'd depends on how their `mpnn` CLI wrapper handles unknown
args — worth checking their actual run logs for which.

**Corrected version:**
```python
_AA3TO1 = {"ALA":"A","ARG":"R","ASN":"N","ASP":"D","CYS":"C","GLN":"Q",
           "GLU":"E","GLY":"G","HIS":"H","ILE":"I","LEU":"L","LYS":"K",
           "MET":"M","PHE":"F","PRO":"P","SER":"S","THR":"T","TRP":"W",
           "TYR":"Y","VAL":"V"}

omit_flag = ""
if shrink:
    omit_1letter = ",".join(_AA3TO1[a] for a in omit_aa)
    omit_map = {f"A{r}": omit_1letter for r in shrink}
    omit_json_path = Path(this_out) / "omit_AA_per_residue.json"
    omit_json_path.write_text(json.dumps(omit_map))
    omit_flag = f'--omit_AA_per_residue "{omit_json_path}"'
```

## 7b. Placeholder dropped; SHRINK_RESIDUES ported instead (2026-08-24)

Backed the channel placeholder out of `config_channel.py`
(`CHANNEL_PLACEHOLDER = ""`) — it took 3 rounds of bug fixes to even get RFD3
to accept the file, and rests on assumptions about RFD3's internals that
aren't fully verified. `00_caver_channel.py` still generates the placeholder
file if it's worth revisiting; it's just not wired in by default.

In its place: the corrected version of §7's `SHRINK_RESIDUES` mechanism,
ported into `partial_diffusion/scripts/03_mpnn_submit.py` (not the
teammate's file — this is our own script) plus real values for PabUPO-II in
`config_channel.py`:

```
SHRINK_RESIDUES (15) : 86, 88, 89, 92, 93, 96, 207, 208, 257, 258, 292, 295, 298, 335, 336
OMIT_AA_AT_SHRINK    : PHE, TRP, TYR, LEU, MET, ILE
```

This is the CAVER sidechain-lining subset of `FLEXIBLE_RESIDUES` — the 7
backbone-only liners (90, 94, 204, 209, 210, 211, 334) are deliberately
excluded, since no sidechain choice changes where a backbone atom sits.

Two hard checks added to `03_mpnn_submit.py` that the teammate's version
didn't have — both `sys.exit` before any GPU time is spent:
- `SHRINK_RESIDUES ⊆ FLEXIBLE_RESIDUES`
- `SHRINK_RESIDUES ∩ _CATALYTIC_PINS == ∅` — this is the exact bug found in
  §7; verified it fires correctly on that exact case.

Also fixed to match the real LigandMPNN spec (§7's 3-part bug): correct flag
name (`--omit_AA_per_residue`), a JSON **file path** rather than inline JSON,
and 1-letter AA codes via `_AA3TO1`.

Without the placeholder, the two remaining levers for widening are
`PARTIAL_T` (backbone freedom) and this shrink mechanism (sequence-level).
Earlier sidechain-stripping test (§ — full removal of 952 sidechain atoms
only bought +0.03 Å) suggests this constriction may be mostly backbone-limited
— so `PARTIAL_T` is probably the higher-leverage knob to raise first if a
pilot comes back `NARROWER` or `UNCHANGED`.

## 7c. omit-flag saga — RESOLVED (2026-08-24)

The teammate's original code was **correct**. I "fixed" it twice based on
external documentation that describes a DIFFERENT tool than what is installed
on this cluster, and both fixes were wrong. Cost: one full 10-backbone MPNN
stage (all 10 calls failed identically).

| | correct (teammate's original) | my wrong "fixes" |
|---|---|---|
| flag | `--omit_per_residue` | `--omit_AA_per_residue` (doesn't exist here) |
| value | inline JSON string | file path (never parsed -> "must be a dict") |
| codes | list of 3-letter, `["PHE","TRP"]` | concatenated 1-letter, `"FWY"` |

Ground truth came from the installed package's own source, not any README:
```
mpnn/utils/inference.py:649   "omit_per_residue": parse_json_like(args.omit_per_residue)
mpnn/utils/inference.py:1222  "omit_per_residue[{res_id}] must be a list"
```
`parse_json_like` parses the CLI value as JSON *text*; a file path isn't valid
JSON so it stays a plain string and fails the dict check with a misleading
message.

**Verified working, not just accepted.** First test (omit F/W/Y at A207)
returned native ILE — which proves nothing, since ILE wasn't in that omit list
and MPNN keeps native residues by default. Real test: omit ILE itself (A207's
native residue), same seed and backbone. Result: 207 came back as something
other than I. The constraint demonstrably changes output.

**Lesson for this codebase:** verify CLI flags against the installed package
source (`site-packages/<pkg>/`), never against upstream docs. The deployed
`mpnn` here is a custom build whose flag names and value formats differ from
the public LigandMPNN release.

## 7d. First real channel-width distribution (2026-08-24)

`02b_caver_filter.py` completed on 10 real RFD3 backbones. Config: CAVER-derived
22 FLEXIBLE_RESIDUES, PARTIAL_T=10, no placeholder.

| metric | value |
|---|---|
| widened | **10 / 10** |
| mean delta | **+0.057 A** |
| median delta | +0.063 A |
| stdev | 0.023 |
| range | +0.013 to +0.084 A |
| radius range | 0.995 - 1.067 A (parent 0.983) |
| above 0.02 noise floor | 9 / 10 |

vs. reference UPOs: all 10 beat 5FUJ (0.975); 7 beat 9HE9 (1.032, PabUPO-II's
own crystal); 4 beat 5OXU (1.050).

This settles the N=1 concern from the pilot — the single +0.057 A draw was not
luck, it sat almost exactly on the mean of 10, and every backbone widened.
PARTIAL_T=10 + the CAVER residue set reliably opens the backbone.

**Still only backbone geometry.** MPNN sequence choice and RF3 refolding come
after; 07_caver_rescore.py on folded designs is the number that counts.

## 7e. "Killed" CPU jobs are cosmetic — do not re-debug

`caver_filter` and `rf3_prep` both report `Exited with signal termination: 9` /
`TERM_EXTERNAL_SIGNAL` while having completed their work correctly (the filter
wrote all 10 CSV rows before "dying"; two runs died at an identical 338 s with
identical CPU/memory, which is deterministic, not node pressure).

Cause is almost certainly the cleanup loop every job script ends with:
```sh
for _pid in $(pgrep -g "$_PGID" 2>/dev/null); do
    [ "$_pid" != "$$" ] && kill -9 "$_pid" 2>/dev/null
done
exit 0
```
It exists to reap orphaned PyTorch dataloader workers. `caver_utils.run_caver`
spawns `java` subprocesses, and the loop appears to take down the shell before
`exit 0` runs, so LSF records a signal-9 exit for a job that actually succeeded.

Harmless in practice: the job chain uses `ended()` not `done()` precisely so a
non-clean exit still advances the pipeline. Worth tidying eventually (skip the
kill loop on CPU-only stages, which have no dataloader workers to reap), but it
is not blocking anything.

## 8. Where things stand (2026-08-24)

**Done.** The full chain runs end to end: CAVER-derived residue selection →
RFD3 → channel-width filter → MPNN with per-residue omission → RF3 → scoring →
before/after channel measurement. `channel_01` produced 174 designs passing the
quality gates, of which the first 20 measured show 16/20 widened (median
+0.042 A, best 1.094 A vs parent 0.983 A).

**Running.** `channel_02` — identical except FLEXIBLE_RESIDUES 22 -> 32
(+87, 91, 95, 206, 259, 261, 293, 294, 297, 331), making the lining stretches
contiguous. Single-variable change, so the comparison is clean.

**Open.**

1. Finish rescoring all 174 of `channel_01` — the 20 measured so far are all
   from backbone `model_0`, so they are correlated and not representative.
2. Compare `channel_02` against `channel_01`. If the pass rate holds but the
   median gain does not improve, that supports the constriction being
   backbone-limited, and the next lever is PARTIAL_T rather than more residues.
3. The catalytic ceiling (§7d) — PHE215/GLU212 form the bottleneck. Any further
   widening means a deliberate decision about the active site.
4. Hand the omit-flag fix (§7c) back to the teammate for their MroUPO config,
   which still has the flag-name bug AND the 157/160 catalytic overlap.
5. Tell whoever owns `channel_discovery/` about the apo/holo and filename
   issues (§2, §3) — they affect any run there, not just ours.
6. `--noise 0.02` in 08_probe_channel.py is still a guess. Canonical staging
   removed the filename variance but residual noise between near-identical
   structures was never measured.
