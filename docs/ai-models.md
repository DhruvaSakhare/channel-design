# AI model disclosure

iGEM asks teams using AI models to say which models, where the training data
came from, how performance was evaluated, and what the limitations are.

**The short version: we trained nothing and fine-tuned nothing.** Every model
here is a published, third-party, pre-trained network used as released. None of
their weights are redistributed in this repository.

## The models

| model | version | role | source |
|---|---|---|---|
| **Boltz-2** | 2.2.1 | Holo structure prediction and binding-affinity estimation from sequence | [jwohlwend/boltz](https://github.com/jwohlwend/boltz) |
| **RFdiffusion3** | `rfd3_latest` | Partial diffusion: remodels a backbone while holding most residues fixed | [RosettaCommons/foundry](https://github.com/RosettaCommons/foundry) |
| **LigandMPNN** | `ligandmpnn_v_32_010_25` | Inverse folding: designs sequence for a backbone, ligand-aware | [RosettaCommons/foundry](https://github.com/RosettaCommons/foundry) (upstream: [dauparas/LigandMPNN](https://github.com/dauparas/LigandMPNN)) |
| **RF3** | `rf3_latest` | Folds and scores each design with heme and substrate present | [RosettaCommons/foundry](https://github.com/RosettaCommons/foundry) |

Installation and weight download: [`envs/design.md`](../envs/design.md) and
[`envs/boltz.yml`](../envs/boltz.yml).

## Training data

**None of it is ours.** We did no training, no fine-tuning, and no
hyperparameter search on any of these networks. All four were trained by their
authors, predominantly on the Protein Data Bank; consult each upstream project
for the exact composition, cut-off dates and any leakage caveats. We are not in
a position to characterise datasets we did not build.

The only data we supply at inference time is:

- our own prepared enzyme structures (`enzyme_design/inputs/`, derived from
  public PDB entries and in-house models),
- multiple sequence alignments retrieved from the public ColabFold/MMseqs2
  server at run time,
- substrate definitions as SMILES strings.

## How we evaluated performance

We did not evaluate these models as models. We evaluated whether their output
was fit for the one question this project asks — *is the substrate channel
wider?* — using an independent, non-neural measurement:

- **CAVER 3.0 tunnel geometry**, a deterministic geometric algorithm, is the
  primary read-out. It is not a learned metric and does not share failure modes
  with the networks that produced the structures.
- **Model-reported confidence** (pLDDT, pTM, ipTM, ipSAE) is used only as a
  filter for structures worth measuring, never as evidence a design is better.
- **Public crystal structures** (5FUJ, 5OXU, 9HE9) anchor every comparison, so
  predictions are judged against experimental data rather than each other.

The numbers are in [validation.md](validation.md). The most important thing we
learned was that **our measurement was wrong before the models were** — two
artifacts in the CAVER read-out were individually larger than the differences
we were trying to detect.

## Limitations

- **Nothing here has been tested in a lab.** Every result is computational. A
  design that folds confidently in RF3 may not express, fold or function.
- **Confidence is not correctness.** pLDDT 0.96 says the network is certain,
  not that the structure is right. This matters most for the redesigned
  residues, which are exactly the positions with least evolutionary signal.
- **Affinity predictions are ranking signals, not measurements.** Boltz-2's
  `affinity_pred_value` is used to order candidates; we make no claim about its
  absolute calibration on UPOs, a family unlikely to be well represented in
  training data.
- **Predicted structures are not crystal structures.** Bottleneck radii from
  predicted models carry the prediction's error, which is why every comparison
  is anchored to real crystals and why the apo/holo protocol is enforced.
- **The design sample is correlated.** See the caveat in
  [validation.md](validation.md#design-result).
- **The pipeline inherits its models' biases.** A generative model trained
  mostly on soluble, well-behaved proteins will propose soluble, well-behaved
  proteins, whether or not that suits an industrial peroxygenase.
