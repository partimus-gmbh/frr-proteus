from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, TypeAlias

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from frr_proteus.render import render_route_maps

if TYPE_CHECKING:
    from frr_proteus._generated import proteus as bindings
else:
    bindings = pytest.importorskip("frr_proteus._generated.proteus")

ProteusRouteMap: TypeAlias = bindings.ProteusRouteMap
RouteMap: TypeAlias = bindings.ProteusRouteMap.RouteMap


def _root_with_entry(sequence: int = 10, action: str = "permit"):
    root = ProteusRouteMap()
    rm = RouteMap(name="RM")
    rm.entry.append(RouteMap.Entry(sequence=sequence, action=action))
    root.route_map.append(rm)
    return root, rm.entry[0]


def test_empty_root_renders_nothing():
    assert render_route_maps(ProteusRouteMap()) == ""


def test_block_header_and_exit():
    root, _ = _root_with_entry()
    assert render_route_maps(root) == "route-map RM permit 10\nexit\n"


def test_action_required():
    root = ProteusRouteMap()
    rm = RouteMap(name="RM")
    rm.entry.append(RouteMap.Entry(sequence=10))
    root.route_map.append(rm)
    with pytest.raises(ValueError, match="action"):
        render_route_maps(root)


def test_entry_header_leaves():
    root, entry = _root_with_entry()
    entry.description = "the description"
    entry.call = "OTHER"
    entry.on_match = "next"
    text = render_route_maps(root)
    assert " description the description\n" in text
    assert " call OTHER\n" in text
    assert " on-match next\n" in text


def test_on_match_goto():
    root, entry = _root_with_entry()
    entry.on_match = 30
    assert " on-match goto 30\n" in render_route_maps(root)


def test_match_lines():
    root, entry = _root_with_entry()
    m = entry.match
    m.interface = "swp1"
    m.ip_address = "ACL4"
    m.ip_address_prefix_list = "PL4"
    m.ip_next_hop_type_blackhole = True
    m.tag = "untagged"
    m.metric = 0
    m.as_path = "ASP"
    m.community.list_name = "CUSTOMERS"
    m.community.match_style = "exact-match"
    m.large_community.list_name = "LARGE"
    m.alias = "cust-gold"
    m.mac_address = "MACS"
    m.evpn.route_type = "macip"
    m.evpn.vni = 100
    text = render_route_maps(root)
    assert " match interface swp1\n" in text
    assert " match ip address ACL4\n" in text
    assert " match ip address prefix-list PL4\n" in text
    assert " match ip next-hop type blackhole\n" in text
    assert " match tag untagged\n" in text
    # 0 is a valid metric and must not be dropped as falsy.
    assert " match metric 0\n" in text
    assert " match as-path ASP\n" in text
    assert " match community CUSTOMERS exact-match\n" in text
    # no match-style set -> no suffix
    assert " match large-community LARGE\n" in text
    assert " match alias cust-gold\n" in text
    assert " match mac address MACS\n" in text
    assert " match evpn route-type macip\n" in text
    assert " match evpn vni 100\n" in text


def test_set_lines():
    root, entry = _root_with_entry()
    s = entry.set
    s.ip_next_hop = "peer-address"
    s.local_preference = 0
    s.metric.operation = "add"
    s.metric.variable = "rtt"
    s.community.member.append(
        type(s.community).Member(global_admin=65001, local_admin=999)
    )
    s.community.additive = True
    s.comm_list_delete = "STRIP"
    s.large_comm_list_delete = "LSTRIP"
    s.as_path_exclude_access_list = "ASP"
    s.aggregator.plain = 65001
    s.aggregator.address = "192.0.2.1"
    s.extcommunity_rt.as2.append(
        type(s.extcommunity_rt).As2(global_admin=65001, local_admin=10)
    )
    s.extcommunity_soo.ipv4.append(
        type(s.extcommunity_soo).Ipv4(global_admin="192.0.2.1", local_admin=7)
    )
    s.extcommunity_bandwidth.value = "cumulative"
    s.extcommunity_bandwidth.non_transitive = True
    s.atomic_aggregate = True
    s.evpn_rmac = "00:11:22:33:44:55"
    text = render_route_maps(root)
    assert " set ip next-hop peer-address\n" in text
    # 0 is a valid local-preference and must not be dropped as falsy.
    assert " set local-preference 0\n" in text
    assert " set metric +rtt\n" in text
    assert " set community 65001:999 additive\n" in text
    assert " set comm-list STRIP delete\n" in text
    assert " set large-comm-list LSTRIP delete\n" in text
    assert " set as-path exclude as-path-access-list ASP\n" in text
    assert " set aggregator as 65001 192.0.2.1\n" in text
    assert " set extcommunity rt 65001:10\n" in text
    assert " set extcommunity soo 192.0.2.1:7\n" in text
    assert " set extcommunity bandwidth cumulative non-transitive\n" in text
    assert " set atomic-aggregate\n" in text
    assert " set extcommunity evpn rmac 00:11:22:33:44:55\n" in text


def test_set_community_none_and_raw_fallback():
    root, entry = _root_with_entry()
    entry.set.community.none = True
    assert " set community none\n" in render_route_maps(root)

    root2, entry2 = _root_with_entry()
    # raw fallback: deliberately setting a value outside the standard
    # forms renders verbatim.
    entry2.set.community.raw.append("4294967296:1")
    assert " set community 4294967296:1\n" in render_route_maps(root2)


def test_set_extcommunity_nt_and_color():
    root, entry = _root_with_entry()
    s = entry.set
    # Node Target IDs are BGP Identifiers (router IDs), rendered with
    # the reserved ':0' FRR's tokenizer requires.
    s.extcommunity_nt.node_id.append("10.0.0.1")
    assert " set extcommunity nt 10.0.0.1:0\n" in render_route_maps(root)

    root2, entry2 = _root_with_entry()
    Color = type(entry2.set.extcommunity_color).Color
    entry2.set.extcommunity_color.color.append(Color(value=100))
    entry2.set.extcommunity_color.color.append(Color(value=200, co_flags="01"))
    assert " set extcommunity color 100 01:200\n" in render_route_maps(root2)


def test_match_evpn_rd_structured():
    root, entry = _root_with_entry()
    entry.match.evpn.rd.as2.administrator = 65001
    entry.match.evpn.rd.as2.assigned_number = 100
    assert " match evpn rd 65001:100\n" in render_route_maps(root)


def test_multiple_entries_each_get_a_block():
    root, _ = _root_with_entry()
    rm = root.route_map[0]
    rm.entry.append(RouteMap.Entry(sequence=20, action="deny"))
    text = render_route_maps(root)
    assert "route-map RM permit 10\nexit\nroute-map RM deny 20\nexit\n" == text


def test_set_metric_operations():
    # The CLI's bare/'+'/'-' prefix is the structured 'operation' leaf
    # (route_value_compile in bgpd/bgp_routemap.c: bare sets, '+' adds
    # to / '-' subtracts from the existing metric); the operand is a
    # real uint32, never a sign-carrying value.
    root, entry = _root_with_entry()
    entry.set.metric.value = 100
    assert " set metric 100\n" in render_route_maps(root)
    entry.set.metric.operation = "add"
    assert " set metric +100\n" in render_route_maps(root)
    entry.set.metric.operation = "subtract"
    assert " set metric -100\n" in render_route_maps(root)


def test_set_metric_value_and_variable_mutually_exclusive():
    root, entry = _root_with_entry()
    entry.set.metric.value = 100
    entry.set.metric.variable = "igp"
    with pytest.raises(bindings.YangValidationError):
        bindings.validate_tree(root)


def test_set_metric_only_rtt_adjustable():
    root, entry = _root_with_entry()
    entry.set.metric.operation = "add"
    entry.set.metric.variable = "igp"
    with pytest.raises(bindings.YangValidationError):
        bindings.validate_tree(root)


def test_set_metric_operation_alone_needs_operand():
    # The operand is a mandatory choice: once anything under metric is
    # set the container exists, so a bare operation is rejected.
    root, entry = _root_with_entry()
    entry.set.metric.operation = "add"
    with pytest.raises(bindings.YangValidationError):
        bindings.validate_tree(root)


def test_set_aigp_metric_zero_renders():
    # Regression: `set aigp-metric 0` is schema-valid but falsy; a
    # truthiness guard used to drop it silently.
    root, entry = _root_with_entry()
    entry.set.aigp_metric = 0
    assert " set aigp-metric 0\n" in render_route_maps(root)
    entry.set.aigp_metric = "igp-metric"
    assert " set aigp-metric igp-metric\n" in render_route_maps(root)
