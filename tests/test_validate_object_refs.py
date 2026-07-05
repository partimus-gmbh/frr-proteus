"""validate_tree() referential integrity for the new object modules.

Every reference that used to be a `// TODO(leafref)` string is now a
real leafref; these tests pin that validate_tree resolves them across
module roots (pass the MODULE ROOTS, never sub-containers -- see
CLAUDE.md) and that a dangling name fails.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, TypeAlias

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

if TYPE_CHECKING:
    from frr_proteus._generated import proteus as bindings
else:
    bindings = pytest.importorskip("frr_proteus._generated.proteus")

Instance: TypeAlias = bindings.ProteusBgp.Bgp.Instance
RouteMap: TypeAlias = bindings.ProteusRouteMap.RouteMaps.RouteMap
PrefixList4: TypeAlias = bindings.ProteusFilter.PrefixLists.Ipv4.PrefixList
AccessList4: TypeAlias = bindings.ProteusFilter.AccessLists.Ipv4.AccessList
AccessList6: TypeAlias = bindings.ProteusFilter.AccessLists.Ipv6.AccessList


def _all_roots():
    return (
        bindings.ProteusBgp(),
        bindings.ProteusRouteMap(),
        bindings.ProteusFilter(),
        bindings.ProteusBgpFilter(),
        bindings.ProteusBfd(),
        bindings.ProteusInterface(),
    )


def _route_map_entry(rm_root, name="RM"):
    rm = RouteMap(name=name)
    rm.entry.append(RouteMap.Entry(sequence=10, action="permit"))
    rm_root.route_maps.route_map.append(rm)
    return rm.entry[0]


def _bgp_neighbor(bgp_root):
    instance = Instance(vrf="default", autonomous_system=65001)
    neighbor = Instance.Neighbor(address="192.0.2.1", remote_as="external")
    instance.neighbor.append(neighbor)
    bgp_root.bgp.instance.append(instance)
    return neighbor


def test_route_map_prefix_list_ref():
    roots = _all_roots()
    _, rm_root, filter_root = roots[:3]
    entry = _route_map_entry(rm_root)
    entry.match.ip_address_prefix_list = "PL"
    with pytest.raises(bindings.YangValidationError, match="no matching instance"):
        bindings.validate_tree(*roots)
    pl = PrefixList4(name="PL")
    pl.entry.append(PrefixList4.Entry(sequence=5, action="permit", any=True))
    filter_root.prefix_lists.ipv4.prefix_list.append(pl)
    bindings.validate_tree(*roots)


def test_route_map_prefix_list_ref_is_family_precise():
    # An IPv6 prefix-list must NOT satisfy 'match ip address prefix-list'.
    roots = _all_roots()
    _, rm_root, filter_root = roots[:3]
    entry = _route_map_entry(rm_root)
    entry.match.ip_address_prefix_list = "PL"
    pl6 = bindings.ProteusFilter.PrefixLists.Ipv6.PrefixList(name="PL")
    filter_root.prefix_lists.ipv6.prefix_list.append(pl6)
    with pytest.raises(bindings.YangValidationError, match="no matching instance"):
        bindings.validate_tree(*roots)


def test_route_map_bgp_filter_refs():
    roots = _all_roots()
    _, rm_root, _, bgpfilter_root = roots[:4]
    entry = _route_map_entry(rm_root)
    entry.match.as_path = "ASP"
    entry.match.community.list_name = "CL"
    entry.match.alias = "gold"
    with pytest.raises(bindings.YangValidationError, match="no matching instance"):
        bindings.validate_tree(*roots)
    Filters = bindings.ProteusBgpFilter.BgpFilters
    asp = Filters.AsPathAccessList(name="ASP")
    asp.entry.append(Filters.AsPathAccessList.Entry(sequence=5, action="permit", regex=".*"))
    bgpfilter_root.bgp_filters.as_path_access_list.append(asp)
    cl = Filters.CommunityList(name="CL", type="standard")
    cl.entry.append(Filters.CommunityList.Entry(sequence=5, action="permit", community=["65001:1"]))
    bgpfilter_root.bgp_filters.community_list.append(cl)
    bgpfilter_root.community_aliases.alias.append(
        bindings.ProteusBgpFilter.CommunityAliases.Alias(name="gold", community="65001:1")
    )
    bindings.validate_tree(*roots)


def test_neighbor_bfd_profile_and_source_interface_refs():
    roots = _all_roots()
    bgp_root, *_ , bfd_root, intf_root = roots
    neighbor = _bgp_neighbor(bgp_root)
    neighbor.bfd.profile = "fast"
    neighbor.source_interface = "swp1"
    with pytest.raises(bindings.YangValidationError, match="no matching instance"):
        bindings.validate_tree(*roots)
    bfd_root.bfd.profile.append(bindings.ProteusBfd.Bfd.Profile(name="fast"))
    intf_root.interfaces.interface.append(
        bindings.ProteusInterface.Interfaces.Interface(name="swp1")
    )
    bindings.validate_tree(*roots)


def test_neighbor_af_filters_family_split():
    # ipv4-unicast filters leafref into the IPv4 lists, ipv6-unicast
    # into the IPv6 lists.
    roots = _all_roots()
    bgp_root, _, filter_root = roots[:3]
    neighbor = _bgp_neighbor(bgp_root)
    neighbor.afi_safis.ipv4_unicast.filters.distribute_list_in = "ACL"
    neighbor.afi_safis.ipv6_unicast.filters.distribute_list_in = "ACL"
    acl4 = AccessList4(name="ACL")
    acl4.entry.append(AccessList4.Entry(sequence=5, action="permit", any=True))
    filter_root.access_lists.ipv4.access_list.append(acl4)
    # IPv4 list alone satisfies only the ipv4-unicast reference.
    with pytest.raises(bindings.YangValidationError, match="ipv6"):
        bindings.validate_tree(*roots)
    acl6 = AccessList6(name="ACL")
    acl6.entry.append(AccessList6.Entry(sequence=5, action="permit", any=True))
    filter_root.access_lists.ipv6.access_list.append(acl6)
    bindings.validate_tree(*roots)


def test_evpn_filters_are_unchecked_strings():
    # The l2vpn-evpn filters keep plain strings (no family-correct
    # leafref target) -- any name passes validation.
    roots = _all_roots()
    neighbor = _bgp_neighbor(roots[0])
    neighbor.afi_safis.l2vpn_evpn.filters.prefix_list_in = "whatever"
    bindings.validate_tree(*roots)


def test_community_list_type_value_must():
    # The YANG 'must' pair ties entry values to the list's type.
    roots = _all_roots()
    bgpfilter_root = roots[3]
    Filters = bindings.ProteusBgpFilter.BgpFilters
    cl = Filters.CommunityList(name="BROKEN", type="expanded")
    cl.entry.append(
        Filters.CommunityList.Entry(sequence=5, action="permit", community=["65001:1"])
    )
    bgpfilter_root.bgp_filters.community_list.append(cl)
    with pytest.raises(bindings.YangValidationError, match="standard-type"):
        bindings.validate_tree(*roots)
