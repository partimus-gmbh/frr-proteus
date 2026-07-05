from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, TypeAlias

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from frr_proteus.render import render_bgp_instance

# Import statically for type checkers so the deeply-nested binding classes keep
# their real types; at runtime use importorskip so the suite skips cleanly when
# bindings haven't been generated. Both paths bind `bindings` to the same module.
if TYPE_CHECKING:
    from frr_proteus._generated import proteus as bindings
else:
    bindings = pytest.importorskip("frr_proteus._generated.proteus")

# This binding doubles as an annotation *and* is instantiated below
# (`Instance(...)`, `Instance.Neighbor(...)`). `TypeAlias` marks it as an alias
# while keeping a normal assignment, so the value stays callable. A PEP 695
# `type X = ...` can't be used here: a TypeAliasType is neither callable nor
# attribute-accessible.
Instance: TypeAlias = bindings.ProteusBgp.Bgp.Instance


def _new_instance(asn: int | None = 65001, vrf: str = "default") -> Instance:
    instance = Instance(vrf=vrf)
    if asn is not None:
        instance.autonomous_system = asn
    return instance


def _add_neighbor(instance: Instance, addr: str) -> Instance.Neighbor:
    neighbor = Instance.Neighbor(address=addr)
    instance.neighbor.append(neighbor)
    return neighbor


def test_router_bgp_header_and_trailing_bang():
    text = render_bgp_instance(_new_instance())
    assert text.startswith("router bgp 65001\n")
    assert text.endswith("!\n")


def test_autonomous_system_required():
    with pytest.raises(ValueError, match="autonomous-system"):
        render_bgp_instance(_new_instance(asn=None))


def test_router_id_omitted_when_unset():
    assert "router-id" not in render_bgp_instance(_new_instance())


def test_router_id_rendered_when_set():
    instance = _new_instance()
    instance.router_id = "10.0.0.1"
    assert " bgp router-id 10.0.0.1\n" in render_bgp_instance(instance)


@pytest.mark.parametrize(
    "remote_as,expected",
    [
        ("external", "neighbor 192.0.2.1 remote-as external"),
        ("internal", "neighbor 192.0.2.1 remote-as internal"),
        (65099, "neighbor 192.0.2.1 remote-as 65099"),
    ],
)
def test_neighbor_remote_as(remote_as, expected):
    instance = _new_instance()
    _add_neighbor(instance, "192.0.2.1").remote_as = remote_as
    assert expected in render_bgp_instance(instance)


def test_neighbor_without_remote_as_not_rendered():
    # e.g. a peer-group member inheriting remote-as: the session-level
    # remote-as line must simply be absent, not broken.
    instance = _new_instance()
    _add_neighbor(instance, "192.0.2.1")
    assert "remote-as" not in render_bgp_instance(instance)


def test_network_statement_under_address_family():
    instance = _new_instance()
    instance.afi_safis.ipv4_unicast.network.append(
        Instance.AfiSafis.Ipv4Unicast.Network(prefix="192.0.2.0/24")
    )

    text = render_bgp_instance(instance)
    assert " address-family ipv4 unicast\n" in text
    assert "  network 192.0.2.0/24\n" in text
    assert " exit-address-family\n" in text
    # bgpd's vty_frame(" !\n address-family ...") only flushes once the
    # block has content -- so a non-empty AF block is preceded by " !".
    assert " !\n address-family ipv4 unicast\n" in text


def test_ipv6_network_statement():
    instance = _new_instance()
    instance.afi_safis.ipv6_unicast.network.append(
        Instance.AfiSafis.Ipv6Unicast.Network(prefix="2001:db8::/48")
    )

    text = render_bgp_instance(instance)
    assert " !\n address-family ipv6 unicast\n" in text
    assert "  network 2001:db8::/48\n" in text


def test_address_family_omitted_when_no_networks():
    assert "address-family" not in render_bgp_instance(_new_instance())


def test_vrf_clause():
    text = render_bgp_instance(_new_instance(vrf="RED"))
    assert text.startswith("router bgp 65001 vrf RED\n")


def test_default_vrf_has_no_vrf_clause():
    text = render_bgp_instance(_new_instance(vrf="default"))
    assert text.startswith("router bgp 65001\n")
