from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from frr_proteus.render import heading


def test_three_line_heading():
    assert heading("route-maps") == "!\n! route-maps\n!\n"


def test_multi_line_title():
    assert heading("customer prefix lists\nmaintained by netops") == (
        "!\n! customer prefix lists\n! maintained by netops\n!\n"
    )


def test_blank_title_lines_skipped():
    assert heading("title\n\n") == "!\n! title\n!\n"


def test_empty_title_rejected():
    with pytest.raises(ValueError, match="empty"):
        heading("  \n ")
