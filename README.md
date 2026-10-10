# channel-design

**Widening the substrate access channel of an unspecific peroxygenase, with the
measurement inside the design loop.**

DTU-Denmark, iGEM 2026. Wiki: <https://2026.igem.wiki/dtu-denmark/>

> Built with AI assistance. Every claim in this repository is traceable to a
> file, a command, or a measurement — see [docs/validation.md](docs/validation.md)
> for what is verified and what is not, and
> [.claude/RESPONSIBLE_AI_USE.md](.claude/RESPONSIBLE_AI_USE.md) for the policy
> we worked under.

Unspecific peroxygenases (UPOs) are attractive industrial oxidation catalysts,
but a substrate only reacts if it can reach the heme. That journey is a narrow
tunnel through the protein, and for a bulky substrate the tunnel is the
bottleneck — quite literally, a constriction under 1 Å in radius.

This repository is the pipeline we built to do something about it. Tunnel
geometry is not an afterthought in it — it drives three separate decisions:

| | CAVER runs on | and decides |
|---|---|---|
| **1** | the parent enzyme, before anything else | **which residues are allowed to move.** The hardest choice in this kind of design, made from measured geometry instead of intuition |
| **2** | every RFdiffusion backbone, before sequence design | **which backbones survive.** The thing we are optimising for is cheap to measure on CPU, so a backbone whose channel collapsed is killed *before* it costs GPU time in LigandMPNN and RF3 |
| **3** | every folded design | **which designs won.** Ranked by measured change in bottleneck radius, never by how confident the model was |

Tunnel tools measure; generative pipelines design and filter on active-site
geometry and fold quality. We are not aware of one that uses tunnel bottleneck
radius as the **selector, the gate and the objective** — that loop is what this
software is.

On PabUPO-II it took the bottleneck from **0.983 Å to 1.094 Å (+11.3%)** at
pLDDT 0.96 — wider than all three reference UPO crystal structures.

The more transferable result is that **we found two bugs in how the channel was
being measured, each larger than the effect we were trying to detect.** If you
measure protein tunnels, [read that part](docs/validation.md) even if you never
run this code.

---

## Quickstart — 30 seconds, no GPU

```bash
git clone https://gitlab.igem.org/2026/software/dtu-denmark/channel-design.git
cd channel-design
uv run --extra tests pytest -q
```

That is the whole thing — [uv](https://docs.astral.sh/uv/) installs its own
Python and every dependency from the committed `uv.lock`, so there is nothing
to set up first and nothing to activate. Takes about a second.

Without uv (needs **Python 3.12 or newer** — `python3` on a stock macOS is
still 3.9, so use a venv rather than the system interpreter):

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r envs/requirements-tests.txt
pytest -q
```

That exercises the real join between components, every shipped configuration,
and the cross-component path resolution, on fixture data. No GPU, no cluster,
no model weights, no network.

Or the fuller check, which adds the real channel pipeline if you have fpocket,
Java and CAVER installed, and skips that tier cleanly if you do not:

```bash
./scripts/smoke_test.sh
```

To see what the GPU pipeline *would* do, without a GPU:

```bash
python enzyme_design/partial_diffusion/site.py          # what paths resolved
PIPELINE_BASE_CONFIG=partial_diffusion.configs.config_pabupo2_channel_01 \
  python enzyme_design/partial_diffusion/scripts/00_submit_all.py --dry-run
```

---

## The workflow

```
FASTA ─► Boltz-2 ─► Vina docking ─► fpocket + CAVER ─► RFD3 ─► LigandMPNN ─► RF3
         structure    poses          pockets, tunnels   remodel  sequences   fold
         + affinity                        │                                  │
                                           └──── which residues to free ──────┤
                                                                              │
                                     CAVER rescore ◄───── did it widen? ──────┘
```

Full diagram and the two cross-component hand-offs:
[docs/architecture.md](docs/architecture.md).

| | component | what it does | needs |
|---|---|---|---|
| 1 | [`boltz/`](boltz/) | Template-driven batch Boltz-2: one YAML per cofactor set, holo structures and binding affinity for a whole FASTA | GPU |
| 2 | [`docking/`](docking/) | AutoDock Vina CLI — blind or targeted docking, box construction, PDBQT preparation | CPU |
| 3 | [`channel_discovery/`](channel_discovery/) | Two-stage screen: fpocket finds the heme-proximal pocket, CAVER maps the tunnels and clusters them by shape | CPU |
| 4 | [`enzyme_design/`](enzyme_design/) | Partial diffusion redesign: RFD3 → LigandMPNN → RF3, with CAVER measurement gating each stage | GPU |

## What you actually need to run it

**You do not need a cluster.** The pipeline has three entry points, and only
the last one assumes a scheduler:

| you have | you can run | how |
|---|---|---|
| **A laptop, no GPU** | `docking/`, all of `channel_discovery/`, every analysis script `07`–`12`, the full test suite | `pytest -q`, `./scripts/smoke_test.sh` |
| **One GPU, no scheduler** | The *entire* design pipeline — RFD3 → LigandMPNN → RF3 — stage by stage on a single card | `python partial_diffusion/scripts/run_local.py` |
| **A cluster with LSF** | The same thing, submitted as job arrays for scale | `python partial_diffusion/scripts/00_submit_all.py` |

`run_local.py` is the same stages as the cluster path with `bsub` taken out, so
nothing is cluster-specific except the batch scripts themselves. It has a
preflight mode that tells you what is missing before anything runs:

```bash
python enzyme_design/partial_diffusion/scripts/run_local.py --check
```

**The entire channel-measurement half of this project — where the validation
work is — needs no GPU at all.**

---

## Install

Three environments, because they genuinely conflict: the docking stack pins
`numpy<2.0` for the RDKit and Vina ABI, while Boltz pulls in torch.

```bash
./setup.sh            # the CPU half: tests + channel measurement
./setup.sh --gpu      # also Boltz-2 and the design stages
./setup.sh --check    # report what is present, install nothing
```

That is everything: it installs [uv](https://docs.astral.sh/uv/) if you do not
have it (asking first), installs every Python dependency from the committed
`uv.lock`, downloads **CAVER 3.0** from caver.cz and verifies its checksum, and
builds **fpocket** from source. **No conda required.** Re-running is safe, and
`$CAVER_HOME` / `$FPOCKET` are honoured if you already have either.

Two caveats worth knowing:

- **fpocket's source build fails on macOS** — a known problem in its bundled
  qhull. Use `conda install -c bioconda fpocket` there. It is only needed for
  the *pocket* stage; tunnel measurement does not use it.
- **On macOS arm64 there is no AutoDock Vina wheel**, so the docking extra
  needs boost headers (`brew install boost`). Linux x86_64 uses a prebuilt
  wheel and needs nothing.

Prefer to do it yourself, or already have conda? The pieces are independent:

```bash
uv sync --extra tests --extra docking    # Python only
./scripts/fetch_third_party.sh           # CAVER + fpocket only
conda env create -f envs/docking.yml     # the conda route instead of uv
```

**Model weights are not fetched** — tens of GB, and only needed if you are
redesigning rather than measuring:

```bash
uv run foundry install base-models --checkpoint-dir ./ckpt
```

See [`envs/design.md`](envs/design.md). Java 8 for CAVER can be your system one.

Nothing needs editing to run. Every path defaults to somewhere inside the
checkout and takes an environment override; see
[`envs/dtu-hpc.env.example`](envs/dtu-hpc.env.example) for a cluster setup.

### Dependency files

### Dependency files

| file | what it pins |
|---|---|
| [`uv.lock`](uv.lock) | **the full transitive lock** for every stage, across platforms — what `uv sync` installs |
| [`envs/requirements-tests.txt`](envs/requirements-tests.txt) | the test environment — a **full** pin, transitive dependencies included, verified against a run of the suite |
| [`envs/docking.yml`](envs/docking.yml) + [`requirements-docking.txt`](envs/requirements-docking.txt) | direct pins for the docking and channel stages. conda is the supported path: `fpocket` and `openjdk=8` are not on PyPI, and `numpy<2.0` must be installed *before* rdkit and vina or their C extensions break |
| [`envs/boltz.yml`](envs/boltz.yml) + [`requirements-boltz.txt`](envs/requirements-boltz.txt) | direct pins for Boltz-2. `torch` is deliberately unpinned — the right wheel depends on your driver's CUDA |

The two GPU environments are pinned at the direct level rather than fully
locked, because a complete lock has to be generated on a machine where the
environment actually works. [docs/hpc-verification.md](docs/hpc-verification.md)
has the commands for producing one.

The design environment needs model weights and is documented separately in
[`envs/design.md`](envs/design.md) — all of RFdiffusion3, RF3 and LigandMPNN
come from [RosettaCommons/foundry](https://github.com/RosettaCommons/foundry)
in one install.

Nothing needs editing to run. Every path defaults to somewhere inside the
checkout and takes an environment override; see
[`envs/dtu-hpc.env.example`](envs/dtu-hpc.env.example) for what a cluster setup
looks like.

---

## Using it for your enzyme

**→ [docs/walkthrough-gpu.md](docs/walkthrough-gpu.md) is the full step-by-step**,
from cloning to ranked designs, for someone with a GPU and their own enzyme.
The short version follows.

The method is not UPO-specific. To point it at your own enzyme:

1. **Prepare your structure** — ligands on their own chains, substrate ~4–5 Å
   above the iron. `enzyme_design/partial_diffusion/scripts/fix_pdb_chains.py`
   does the chain surgery. *Ligands must be `HETATM`* — see
   [KNOWN_ISSUES.md](KNOWN_ISSUES.md#2-a-substrate-written-as-atom-is-invisible).
2. **Copy a config** from `enzyme_design/partial_diffusion/configs/` and edit
   the tagged lines. The one list that matters is `FLEXIBLE_RESIDUES`;
   everything not in it is held rigid and native.
3. **Let CAVER choose that list** — `00_caver_channel.py` measures the parent
   and writes the tunnel-lining residues for you.
4. **Build the MSA** — `00_make_msa.py`, once per enzyme.

For Boltz, a template is plain YAML with a `{seq}` placeholder and cofactors by
PDB three-letter code. The bundled `4cu.yaml` (four copper ions, for
multicopper oxidases) is there as evidence this already generalised past heme
enzymes — `HEM`, `CU`, `ZN`, `NAD`, `FAD` all work the same way.

---

## Results and honesty

| | |
|---|---|
| Best design | **1.094 Å** bottleneck, **+11.3%** over the parent, pLDDT 0.96 |
| RFD3 backbones widened | 10/10, mean +0.057 Å |
| Designs passing fold quality | 174/200 |
| Folded designs measured | 16/20 widened, median +0.042 Å |

**Caveats we would rather you read than discover.** Those 20 designs all come
from one backbone and are therefore correlated; the full 174-design rescore is
unfinished. Nothing here has been tested in a lab. The ceiling on widening this
particular channel turns out to be catalytic — the constriction is formed by
two catalytic residues, so going much further means touching the active site.

Details, and the two measurement bugs: [docs/validation.md](docs/validation.md).

---

## Documentation

| | |
|---|---|
| [docs/architecture.md](docs/architecture.md) | how the four components chain; the two hand-offs; configuration layers |
| [docs/validation.md](docs/validation.md) | the two measurement bugs, the crystal benchmark, the design result, what is *not* validated |
| [docs/data-formats.md](docs/data-formats.md) | every format at every boundary; the CSV contract; why there is no SBOL here |
| [docs/ai-models.md](docs/ai-models.md) | which models, whose training data, how we evaluated, what the limitations are |
| [KNOWN_ISSUES.md](KNOWN_ISSUES.md) | seven traps that each cost somebody a run, with the commands to verify them |
| [CHANGELOG.md](CHANGELOG.md) | what was built and why |
| [docs/walkthrough-gpu.md](docs/walkthrough-gpu.md) | **start here to run it** — twelve steps, clone to ranked designs, plus a no-GPU measurement-only path |
| [tests/README.md](tests/README.md) | what each test protects |
| [docs/hpc-verification.md](docs/hpc-verification.md) | step-by-step check that this runs on a cluster, and how to generate the full dependency locks |
| [`CHANNEL_README.md`](enzyme_design/partial_diffusion/CHANNEL_README.md) | the channel-widening workflow in detail |
| [`CHANNEL_WIDENING_LOG.md`](enzyme_design/partial_diffusion/CHANNEL_WIDENING_LOG.md) | the lab notebook: what was tried, what failed, why it is built this way |

---

## Extending it

Stage scripts are numbered in execution order and independently runnable.
Configuration is layered so an experiment never carries a filesystem:
experiment settings in `configs/`, machine settings in `site.py`, your
overrides in a gitignored env file.

The one thing to know before changing anything: the components meet at a CSV
(`accession`, `ligand_iptm`, `affinity_pred_value`) and at
`enzyme_design/lib/paths.py`. Both are covered by tests, because both break
silently. Run `pytest -q` before and after.

Swapping in a different affinity predictor for Boltz-2 means emitting those
three columns. Nothing else changes.

---

## Data and large files

This repository holds source code and small example inputs only — 1.9 MB
packed. The bundled structures (10 prepared PDBs, 4 ColabFold MSAs, 3 public
reference crystals) live in `enzyme_design/examples/` and are enough to run
the channel pipeline end to end. `enzyme_design/inputs/` ships empty — that
directory is for **your** structures, so ours never get mixed in with them.

Model weights are **not** here: they belong to their upstream projects and are
fetched, see [`envs/design.md`](envs/design.md). Molecular dynamics
trajectories and full design result sets are not in this repository either; if
they are published they will go to
[Zenodo](https://teams.igem.org/go/deliverables/software/zenodo) with a citable
DOI and be linked from here.

## License and citation

This project's own code is **Apache 2.0** — see [LICENSE](LICENSE).

Third-party tools are **not** redistributed here; [NOTICE](NOTICE) lists them
with their licenses. Two in particular:

- **CAVER 3.0** — GPLv3, Masaryk University. Fetched by
  `scripts/fetch_third_party.sh`. If you publish results made with it, cite
  Chovancova E. *et al.* (2012) *CAVER 3.0: A Tool for the Analysis of
  Transport Pathways in Dynamic Protein Structures.* PLoS Comput Biol
  8(10):e1002708.
- **fpocket** — MIT, © Peter Schmidtke & Vincent Le Guilloux.

To cite this software, see [CITATION.cff](CITATION.cff).
