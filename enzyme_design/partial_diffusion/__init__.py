"""
The partial-diffusion pipeline.

Stage scripts choose their configuration through `default_config()` rather than
naming a module directly, so that a fresh clone works before anyone has made a
config.py. That file is deliberately not in the repository -- it is your working
copy, made by copying config_template.py -- and defaulting straight to it meant
`--help` and `--dry-run` failed with an import error on a clean checkout.
"""
import os
from importlib.util import find_spec


def default_config():
    """Name of the config module the stage scripts should import.

    In order: $PIPELINE_BASE_CONFIG if set, then your own config.py if you have
    made one, then the shipped template. The template is a working configuration
    for the bundled example enzyme, so a fresh clone can be inspected and
    dry-run before anything is configured.
    """
    chosen = os.environ.get("PIPELINE_BASE_CONFIG")
    if chosen:
        return chosen
    if find_spec("partial_diffusion.config") is not None:
        return "partial_diffusion.config"
    return "partial_diffusion.config_template"
