# Tests

Everything here runs on a laptop in a couple of seconds: **no GPU, no cluster,
no CAVER, no fpocket, no model weights, no network.** That is deliberate — the
parts of this project that need a GPU are the parts a reviewer cannot check,
so the tests cover the parts they can.

```bash
pip install pytest pyyaml numpy matplotlib
pytest -q
```

| file | what it protects |
|---|---|
| `test_no_machine_paths.py` | No cluster path, DTU user id, committed binary or licence-restricted file can re-enter the repository. |
| `test_sources_compile.py` | Every tracked `.py` parses. Catches a half-applied edit across the stage scripts; needs no dependencies. |
| `test_boltz_templates.py` | The shipped templates render to valid YAML and their affinity head names a ligand that exists. |
| `test_affinity_contract.py` | The CSV contract joining Boltz-2 to the channel clustering — the one interface between two components written separately. |
| `test_boltz_resume.py` | Resuming a batch does not duplicate rows (see the regression it is named for). |
| `test_configs.py` | Every shipped config imports, finds its structure, and writes only under `$PIPELINE_WORK_ROOT`. |
| `test_channel_staging.py` | Both CAVER entry points measure apo and stage under one filename, through one shared module — the two bugs in `docs/validation.md`. CAVER is stubbed out. |
| `test_paths.py` | `enzyme_design/` can still find `channel_discovery/` now that they are separate components. |

`fixtures/` holds a six-row Boltz summary and a matching cluster assignment
table. The rows are chosen so each filtering rule is observable: one row falls
below the `ligand_iptm` cutoff, one is a failed run with empty metrics, and the
remaining four split across two clusters.
