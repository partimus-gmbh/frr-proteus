from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, TypeAlias

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from frr_proteus.render import render_vrfs

if TYPE_CHECKING:
    from frr_proteus._generated import proteus as bindings
else:
    bindings = pytest.importorskip("frr_proteus._generated.proteus")

ProteusVrf: TypeAlias = bindings.ProteusVrf
Vrf: TypeAlias = bindings.ProteusVrf.Vrf


def test_empty_root_renders_nothing():
    assert render_vrfs(ProteusVrf()) == ""


def test_vrf_blocks():
    root = ProteusVrf()
    root.vrf.append(Vrf(name="tnt1", l3vni=15000001))
    root.vrf.append(Vrf(name="tnt2"))
    assert render_vrfs(root) == (
        "!\n"
        "vrf tnt1\n"
        " vni 15000001\n"
        "exit-vrf\n"
        "!\n"
        "vrf tnt2\n"
        "exit-vrf\n"
    )


def test_heading_prefix():
    root = ProteusVrf()
    root.vrf.append(Vrf(name="tnt1"))
    text = render_vrfs(root, heading="vrfs")
    assert text.startswith("!\n! vrfs\n!\nvrf tnt1\n")


def test_heading_suppressed_when_empty():
    assert render_vrfs(ProteusVrf(), heading="vrfs") == ""


def test_prefix_routes_only_suffix():
    root = ProteusVrf()
    root.vrf.append(
        Vrf(name="tnt1", l3vni=15000001, prefix_routes_only=True)
    )
    assert " vni 15000001 prefix-routes-only\n" in render_vrfs(root)


def test_default_vrf_rejected():
    root = ProteusVrf()
    root.vrf.append(Vrf(name="default"))
    with pytest.raises(bindings.YangValidationError):
        bindings.validate_tree(root)


def test_prefix_routes_only_requires_l3vni():
    root = ProteusVrf()
    root.vrf.append(Vrf(name="tnt1", prefix_routes_only=True))
    with pytest.raises(bindings.YangValidationError):
        bindings.validate_tree(root)
