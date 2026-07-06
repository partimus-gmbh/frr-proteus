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
Interface: TypeAlias = bindings.ProteusInterface.Interface


def test_empty_root_renders_nothing():
    assert render_interfaces(ProteusInterface()) == ""


def test_interface_blocks():
    root = ProteusInterface()
    root.interface.append(
        Interface(name="swp1", description="to spine1")
    )
    root.interface.append(Interface(name="swp2"))
    assert render_interfaces(root) == (
        "!\n"
        "interface swp1\n"
        " description to spine1\n"
        "exit\n"
        "!\n"
        "interface swp2\n"
        "exit\n"
    )


def test_default_separator_before_section():
    root = ProteusInterface()
    root.interface.append(Interface(name="swp1"))
    assert render_interfaces(root) == "!\ninterface swp1\nexit\n"


def test_heading_none_disables_separator():
    root = ProteusInterface()
    root.interface.append(Interface(name="swp1"))
    text = render_interfaces(root, heading=None)
    assert text.startswith("interface swp1\n")


def test_heading_prefix():
    root = ProteusInterface()
    root.interface.append(Interface(name="swp1"))
    text = render_interfaces(root, heading="interfaces")
    assert text.startswith("!\n! interfaces\n!\ninterface swp1\n")


def test_heading_suppressed_when_empty():
    assert render_interfaces(ProteusInterface(), heading="interfaces") == ""


def test_ipv6_nd_ra_interval_seconds():
    root = ProteusInterface()
    intf = Interface(name="swp1")
    intf.ipv6_nd.ra_interval = 5
    root.interface.append(intf)
    assert render_interfaces(root) == (
        "!\n"
        "interface swp1\n"
        " ipv6 nd ra-interval 5\n"
        "exit\n"
    )


def test_ipv6_nd_ra_interval_msec():
    root = ProteusInterface()
    intf = Interface(name="swp1")
    intf.ipv6_nd.ra_interval_msec = 500
    root.interface.append(intf)
    assert " ipv6 nd ra-interval msec 500\n" in render_interfaces(root)


def test_ipv6_nd_ra_interval_choice_exclusive():
    root = ProteusInterface()
    intf = Interface(name="swp1")
    intf.ipv6_nd.ra_interval = 5
    intf.ipv6_nd.ra_interval_msec = 500
    root.interface.append(intf)
    with pytest.raises(bindings.YangValidationError):
        bindings.validate_tree(root)


def test_mpls_bgp_interface_flags():
    root = ProteusInterface()
    iface = Interface(name="eth0")
    iface.mpls_bgp_forwarding = True
    iface.mpls_bgp_l3vpn_multi_domain_switching = True
    root.interface.append(iface)
    assert render_interfaces(root) == (
        "!\n"
        "interface eth0\n"
        " mpls bgp forwarding\n"
        " mpls bgp l3vpn-multi-domain-switching\n"
        "exit\n"
    )


def test_mpls_bgp_interface_flags_omitted_when_unset():
    root = ProteusInterface()
    root.interface.append(Interface(name="eth0"))
    assert "mpls" not in render_interfaces(root)
