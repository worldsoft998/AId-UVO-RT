import os

import pytest

from aiduvo.coverage import metrics
from aiduvo.coverage.ucis import load_coverage, parse_ucis_string

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "ucis_sample.xml")


def test_parse_child_count_and_attribute_hits():
    snap = load_coverage(FIXTURE)
    flat = snap.flat()
    assert flat["cg_demo.cp_op.write"].hits == 12
    assert flat["cg_demo.cp_op.read"].hits == 7
    assert flat["cg_demo.cp_op.idle"].hits == 3          # hits attribute form
    assert flat["cg_demo.cp_level.lvl1"].hits == 1


def test_ignore_bins_are_excluded_from_the_total():
    snap = load_coverage(FIXTURE)
    assert snap.total_bins == 6                            # 7 bins, 1 ignored
    assert any(b.excluded for b in snap.iter_bins())


def test_closure_matches_hand_count():
    snap = load_coverage(FIXTURE)
    # covered: write, read, idle, lvl1  ->  4 of 6
    assert metrics.closure(snap) == pytest.approx(4 / 6)


def test_namespace_tolerance():
    text = """<coveragedata xmlns="urn:other">
      <covergroup name="g"><coverpoint name="c">
        <bin name="b1"><count>2</count></bin>
      </coverpoint></covergroup>
    </coveragedata>"""
    snap = parse_ucis_string(text)
    assert snap.flat()["g.c.b1"].hits == 2


def test_empty_document_is_empty():
    snap = parse_ucis_string('<?xml version="1.0"?><ucis:coveragedata xmlns:ucis="x"/>')
    assert snap.is_empty()
