"""
The shipped Boltz templates must actually be usable.

A template is plain Boltz YAML with a `{seq}` placeholder. The failure mode
worth catching is a template that looks fine but produces invalid YAML once a
sequence is substituted, or that points its affinity head at a ligand id that
does not exist -- neither shows up until a GPU job has already been queued.
"""
import importlib.util

import pytest
import yaml

from conftest import REPO_ROOT

TEMPLATE_DIR = REPO_ROOT / "boltz" / "templates"
TEMPLATES = sorted(TEMPLATE_DIR.glob("*.yaml"))

spec = importlib.util.spec_from_file_location(
    "btb", REPO_ROOT / "boltz" / "boltz_template_batch.py")
btb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(btb)

SEQ = "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ"


def test_templates_exist():
    assert TEMPLATES, f"no templates found in {TEMPLATE_DIR}"


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_template_validates(path):
    btb.validate_template(path.read_text())


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_rendered_template_is_valid_yaml(path, tmp_path):
    out = tmp_path / "boltz_input.yaml"
    btb.render_yaml(path.read_text(), SEQ, "TEST_001", out)
    doc = yaml.safe_load(out.read_text())

    assert "sequences" in doc
    proteins = [s["protein"] for s in doc["sequences"] if "protein" in s]
    assert proteins, f"{path.name} declares no protein"
    assert proteins[0]["sequence"] == SEQ, "placeholder was not substituted"


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_affinity_binder_refers_to_a_declared_ligand(path, tmp_path):
    out = tmp_path / "boltz_input.yaml"
    btb.render_yaml(path.read_text(), SEQ, "TEST_001", out)
    doc = yaml.safe_load(out.read_text())

    if "properties" not in doc:
        pytest.skip(f"{path.name} predicts no affinity")

    ligand_ids = {s["ligand"]["id"] for s in doc["sequences"] if "ligand" in s}
    for prop in doc["properties"]:
        binder = prop["affinity"]["binder"]
        assert binder in ligand_ids, (
            f"{path.name}: affinity binder '{binder}' is not a declared "
            f"ligand (have: {sorted(ligand_ids)})"
        )


def test_validate_template_rejects_missing_placeholder():
    with pytest.raises(SystemExit):
        btb.validate_template("sequences:\n  - protein:\n      id: A\n")


def test_validate_template_rejects_missing_sequences_block():
    with pytest.raises(SystemExit):
        btb.validate_template('protein:\n  sequence: "{seq}"\n')
