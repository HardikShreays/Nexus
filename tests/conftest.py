import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from demo import load_pilot  # noqa: E402

P = "MUM-DC1"


@pytest.fixture
def pilot():
    """Fresh store + index loaded with the sample pilot project (docs and vendor master only)."""
    return load_pilot()
