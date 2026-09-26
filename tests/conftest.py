import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"

# The pipeline is a set of scripts, not an installed package; these are the
# same two entries the stage scripts put on sys.path themselves.
sys.path.insert(0, str(REPO_ROOT / "enzyme_design"))
sys.path.insert(0, str(REPO_ROOT / "enzyme_design" / "lib"))
