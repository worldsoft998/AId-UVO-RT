import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture()
def tmp_campaign_dir(tmp_path):
    d = tmp_path / "campaign"
    d.mkdir()
    return str(d)
