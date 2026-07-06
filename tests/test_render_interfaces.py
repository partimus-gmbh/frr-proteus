from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, TypeAlias

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from frr_proteus.render import render_interfaces

if TYPE_CHECKING:
    from frr_proteus._generated import proteus as bindings
else:
    bindings = pytest.importorskip("frr_proteus._generated.proteus")

ProteusInterface: TypeAlias = bindings.ProteusInterface
Interface: TypeAlias = bindings.ProteusInterface.Interfaces.Interface


def test_empty_root_renders_nothing():
    assert render_interfaces(ProteusInterface()) == ""


def test_interface_blocks():
    root = ProteusInterface()
    root.interfaces.interface.append(
        Interface(name="swp1", description="to spine1")
    )
    root.interfaces.interface.append(Interface(name="swp2"))
    assert render_interfaces(root) == (
        "interface swp1\n"
        " description to spine1\n"
        "exit\n"
        "interface swp2\n"
        "exit\n"
    )


def test_ipv6_nd_ra_interval_seconds():
    root = ProteusInterface()
    intf = Interface(name="swp1")
    intf.ipv6_nd.ra_interval = 5
    root.interfaces.interface.append(intf)
    assert render_interfaces(root) == (
        "interface swp1\n"
        " ipv6 nd ra-interval 5\n"
        "exit\n"
    )


def test_ipv6_nd_ra_interval_msec():
    root = ProteusInterface()
    intf = Interface(name="swp1")
    intf.ipv6_nd.ra_interval_msec = 500
    root.interfaces.interface.append(intf)
    assert " ipv6 nd ra-interval msec 500\n" in render_interfaces(root)


def test_ipv6_nd_ra_interval_choice_exclusive():
    root = ProteusInterface()
    intf = Interface(name="swp1")
    intf.ipv6_nd.ra_interval = 5
    intf.ipv6_nd.ra_interval_msec = 500
    root.interfaces.interface.append(intf)
    with pytest.raises(bindings.YangValidationError):
        bindings.validate_tree(root)
