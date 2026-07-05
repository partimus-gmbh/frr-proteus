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
RouteMap: TypeAlias = bindings.ProteusRouteMap.RouteMaps.RouteMap


def _root_with_entry(sequence: int = 10, action: str = "permit"):
    root = ProteusRouteMap()
    rm = RouteMap(name="RM")
    rm.entry.append(RouteMap.Entry(sequence=sequence, action=action))
    root.route_maps.route_map.append(rm)
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
    root.route_maps.route_map.append(rm)
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
    s.metric = "+rtt"
    s.community = "65001:999 additive"
    s.comm_list_delete = "STRIP"
    s.large_comm_list_delete = "LSTRIP"
    s.as_path_exclude_access_list = "ASP"
    s.aggregator.as_ = 65001
    s.aggregator.address = "192.0.2.1"
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
    assert " set extcommunity bandwidth cumulative non-transitive\n" in text
    assert " set atomic-aggregate\n" in text
    assert " set extcommunity evpn rmac 00:11:22:33:44:55\n" in text


def test_multiple_entries_each_get_a_block():
    root, _ = _root_with_entry()
    rm = root.route_maps.route_map[0]
    rm.entry.append(RouteMap.Entry(sequence=20, action="deny"))
    text = render_route_maps(root)
    assert "route-map RM permit 10\nexit\nroute-map RM deny 20\nexit\n" == text
