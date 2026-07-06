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


# --- instance-level knobs (bgp_config_write in bgpd/bgp_vty.c) ---


def test_no_bgp_default_ipv4_unicast_only_negative_form():
    instance = _new_instance()
    instance.default.ipv4_unicast = False
    assert " no bgp default ipv4-unicast\n" in render_bgp_instance(instance)
    # True is FRR's default and is never written back.
    instance.default.ipv4_unicast = True
    assert "bgp default ipv4-unicast" not in render_bgp_instance(instance)


def test_bgp_default_other_families_positive_form():
    instance = _new_instance()
    instance.default.ipv6_unicast = True
    assert " bgp default ipv6-unicast\n" in render_bgp_instance(instance)


def test_deterministic_med_three_valued():
    instance = _new_instance()
    assert "deterministic-med" not in render_bgp_instance(instance)
    instance.deterministic_med = True
    assert " bgp deterministic-med\n" in render_bgp_instance(instance)
    instance.deterministic_med = False
    assert " no bgp deterministic-med\n" in render_bgp_instance(instance)


def test_graceful_restart_modes():
    instance = _new_instance()
    instance.graceful_restart.mode = "disable"
    assert " bgp graceful-restart-disable\n" in render_bgp_instance(instance)
    instance.graceful_restart.mode = "restarter"
    assert " bgp graceful-restart\n" in render_bgp_instance(instance)


def test_bestpath_multipath_relax_and_as_set():
    instance = _new_instance()
    instance.bestpath.as_path_multipath_relax.enabled = True
    text = render_bgp_instance(instance)
    assert " bgp bestpath as-path multipath-relax\n" in text
    instance.bestpath.as_path_multipath_relax.as_set = True
    text = render_bgp_instance(instance)
    assert " bgp bestpath as-path multipath-relax as-set\n" in text


# --- peer-groups and session-level neighbor lines
#     (bgp_config_write_peer_global in bgpd/bgp_vty.c) ---


def _new_peer_group(instance: Instance, name: str) -> Instance.PeerGroup:
    group = Instance.PeerGroup(name=name)
    instance.peer_group.append(group)
    return group


def test_peer_group_declaration_before_neighbors():
    instance = _new_instance()
    _new_peer_group(instance, "SPINES")
    _add_neighbor(instance, "192.0.2.1").peer_group = "SPINES"
    text = render_bgp_instance(instance)
    declaration = text.index(" neighbor SPINES peer-group\n")
    membership = text.index(" neighbor 192.0.2.1 peer-group SPINES\n")
    assert declaration < membership


def test_session_lines_in_peer_global_order():
    instance = _new_instance()
    group = _new_peer_group(instance, "PEERS")
    group.description = "ix peers"
    group.bfd.enabled = True
    group.password = "s3cret"
    group.ebgp_multihop = 3
    group.update_source = "192.0.2.99"
    text = render_bgp_instance(instance)
    lines = [
        " neighbor PEERS peer-group\n",
        " neighbor PEERS description ix peers\n",
        " neighbor PEERS bfd\n",
        " neighbor PEERS password s3cret\n",
        " neighbor PEERS ebgp-multihop 3\n",
        " neighbor PEERS update-source 192.0.2.99\n",
    ]
    positions = [text.index(line) for line in lines]
    assert positions == sorted(positions)


def test_ebgp_multihop_255_renders_bare():
    instance = _new_instance()
    neighbor = _add_neighbor(instance, "192.0.2.1")
    neighbor.remote_as = "external"
    neighbor.ebgp_multihop = 255
    assert " neighbor 192.0.2.1 ebgp-multihop\n" in render_bgp_instance(
        instance
    )


def test_ttl_security_and_timers():
    instance = _new_instance()
    neighbor = _add_neighbor(instance, "192.0.2.1")
    neighbor.remote_as = "external"
    neighbor.ttl_security_hops = 1
    neighbor.timers.keepalive = 10
    neighbor.timers.holdtime = 30
    text = render_bgp_instance(instance)
    assert " neighbor 192.0.2.1 ttl-security hops 1\n" in text
    assert " neighbor 192.0.2.1 timers 10 30\n" in text


def test_interface_peer_v6only_with_peer_group_on_one_line():
    instance = _new_instance()
    _new_peer_group(instance, "UNDERLAY")
    neighbor = _add_neighbor(instance, "swp1")
    neighbor.interface_peer = True
    neighbor.v6only = True
    neighbor.peer_group = "UNDERLAY"
    neighbor.remote_as = 65002
    text = render_bgp_instance(instance)
    # peer-group rides on the interface line; remote-as gets its own.
    assert " neighbor swp1 interface v6only peer-group UNDERLAY\n" in text
    assert " neighbor swp1 remote-as 65002\n" in text
    assert " neighbor swp1 peer-group UNDERLAY\n" not in text


def test_interface_peer_without_group():
    instance = _new_instance()
    neighbor = _add_neighbor(instance, "swp1")
    neighbor.interface_peer = True
    neighbor.remote_as = "external"
    text = render_bgp_instance(instance)
    assert " neighbor swp1 interface\n" in text
    assert " neighbor swp1 remote-as external\n" in text


# --- per-AF neighbor lines (bgp_config_write_peer_af) ---


def test_af_activate_three_valued():
    instance = _new_instance()
    neighbor = _add_neighbor(instance, "192.0.2.1")
    neighbor.remote_as = "external"
    assert "activate" not in render_bgp_instance(instance)
    neighbor.afi_safis.ipv4_unicast.activate = True
    assert "  neighbor 192.0.2.1 activate\n" in render_bgp_instance(instance)
    neighbor.afi_safis.ipv4_unicast.activate = False
    assert "  no neighbor 192.0.2.1 activate\n" in render_bgp_instance(
        instance
    )


def test_af_lines_render_for_peer_groups_too():
    instance = _new_instance()
    group = _new_peer_group(instance, "PEERS")
    af = group.afi_safis.ipv4_unicast
    af.activate = True
    af.soft_reconfiguration_inbound = True
    af.filters.route_map_in = None  # leafref left unset on purpose
    text = render_bgp_instance(instance)
    assert " !\n address-family ipv4 unicast\n" in text
    assert "  neighbor PEERS activate\n" in text
    assert "  neighbor PEERS soft-reconfiguration inbound\n" in text


def test_af_policy_lines_in_peer_af_order():
    instance = _new_instance()
    neighbor = _add_neighbor(instance, "192.0.2.1")
    neighbor.remote_as = "internal"
    af = neighbor.afi_safis.ipv4_unicast
    af.activate = True
    af.route_reflector_client = True
    af.next_hop_self.enabled = True
    af.remove_private_as = "all-replace-as"
    af.soft_reconfiguration_inbound = True
    af.maximum_prefix.count = 1000
    af.maximum_prefix.restart_interval = 30
    af.allowas_in.enabled = True
    af.allowas_in.count = 2
    af.weight = 100
    af.filters.route_map_in = None
    text = render_bgp_instance(instance)
    lines = [
        "  neighbor 192.0.2.1 activate\n",
        "  neighbor 192.0.2.1 route-reflector-client\n",
        "  neighbor 192.0.2.1 next-hop-self\n",
        "  neighbor 192.0.2.1 remove-private-AS all replace-AS\n",
        "  neighbor 192.0.2.1 soft-reconfiguration inbound\n",
        "  neighbor 192.0.2.1 maximum-prefix 1000 restart 30\n",
        "  neighbor 192.0.2.1 allowas-in 2\n",
        "  neighbor 192.0.2.1 weight 100\n",
    ]
    positions = [text.index(line) for line in lines]
    assert positions == sorted(positions)


def test_send_community_negations():
    instance = _new_instance()
    neighbor = _add_neighbor(instance, "192.0.2.1")
    neighbor.remote_as = "external"
    af = neighbor.afi_safis.ipv4_unicast
    af.send_community.large = False
    text = render_bgp_instance(instance)
    assert "  no neighbor 192.0.2.1 send-community large\n" in text
    af.send_community.standard = False
    af.send_community.extended = False
    text = render_bgp_instance(instance)
    assert "  no neighbor 192.0.2.1 send-community all\n" in text
    assert "send-community large\n  " not in text


def test_enforce_first_as_three_valued():
    instance = _new_instance()
    neighbor = _add_neighbor(instance, "192.0.2.1")
    neighbor.remote_as = "external"
    assert "enforce-first-as" not in render_bgp_instance(instance)
    neighbor.enforce_first_as = False
    assert " no neighbor 192.0.2.1 enforce-first-as\n" in render_bgp_instance(
        instance
    )
    neighbor.enforce_first_as = True
    assert " neighbor 192.0.2.1 enforce-first-as\n" in render_bgp_instance(
        instance
    )


def test_attribute_unchanged_combined_line():
    instance = _new_instance()
    neighbor = _add_neighbor(instance, "192.0.2.1")
    neighbor.remote_as = "external"
    af = neighbor.afi_safis.ipv4_unicast
    af.attribute_unchanged.next_hop = True
    text = render_bgp_instance(instance)
    assert "  neighbor 192.0.2.1 attribute-unchanged next-hop\n" in text
    af.attribute_unchanged.as_path = True
    af.attribute_unchanged.med = True
    text = render_bgp_instance(instance)
    assert (
        "  neighbor 192.0.2.1 attribute-unchanged as-path next-hop med\n"
        in text
    )
