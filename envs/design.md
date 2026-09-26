# The design environment (RFdiffusion3, LigandMPNN, RF3)

The redesign stages need three models that are **not** redistributed with this
repository. All three come from the same upstream project, so this is one
install rather than three.

Unlike the other two environments there is no pinned `environment.yml` here:
the correct torch build depends on your driver's CUDA version, and the
checkpoints are large binaries that belong on a filesystem, not in git. What
follows is the honest recipe rather than a lockfile that could not be honoured.

## Install

```bash
conda create -n protein-design python=3.11 -y
conda activate protein-design

# Install torch for YOUR CUDA first -- check with `nvidia-smi`.
pip install torch --index-url https://download.pytorch.org/whl/cu128

pip install "rc-foundry[all]"
```

Source: [RosettaCommons/foundry](https://github.com/RosettaCommons/foundry).
It is the single upstream for RFdiffusion3, RF3 and ProteinMPNN/LigandMPNN.

## Weights

```bash
foundry install base-models --checkpoint-dir /path/to/ckpt
foundry list-installed
```

`base-models` fetches the current RFD3, RF3 and MPNN variants together, which
is why this pipeline expects them side by side in one `ckpt/` directory.

Then point the pipeline at them — see `envs/dtu-hpc.env.example`:

```bash
export RFD3_CKPT=/path/to/ckpt/rfd3_latest.ckpt
export MPNN_CKPT=/path/to/ckpt/ligandmpnn_v_32_010_25.pt
export RF3_CKPT=/path/to/ckpt/rf3_latest.pt
export RF3_RELEASE=/path/to/rf3/release     # the RF3 software tree, if separate
```

Defaults, if you set nothing, are `enzyme_design/ckpt/<name>` — so unpacking
the checkpoints there also works, and `ckpt/` is gitignored.

`partial_diffusion/site.py` prints what it resolved:

```bash
python enzyme_design/partial_diffusion/site.py
```

## Licensing

RF3 and RFdiffusion3 are published under a BSD-3-Clause licence with openly
served weights, per the RF3 release. Check the upstream repository for the
current terms before redistributing anything derived from them — this project
does not redistribute the weights at all.

## If you cannot run this stage

The design stages (RFD3 → LigandMPNN → RF3) need a GPU and these checkpoints.
Everything else in this repository does not:

- `boltz/` needs its own environment and a GPU, but no local weights.
- `docking/` and `channel_discovery/` need only `envs/docking.yml` — no GPU,
  no checkpoints. The entire channel-measurement half of the project, which is
  where the validation work lives, runs on a laptop.

`scripts/smoke_test.sh` deliberately exercises only that half.

## A note on `modelhub`

Older internal RF3 installs ship a `modelhub` package inside the RF3 release
tree rather than `rc-foundry`. `lib/rf3_wrapper.py` imports it and patches
`nvmlDeviceGetNumGpuCores` for A100 MIG slices. If you install from foundry as
above you will not have `modelhub`; set `RF3_RELEASE` to your install and the
wrapper will use whatever is there.
