"""Rendering of the RFC 7952 `comment` annotation
(proteus-configuration-metadata.yang) into the generated FRR config.

FRR only has whole-line comments -- a line whose first non-whitespace
character is '!' or '#' (lib/command.c cmd_make_strvec, vtysh/vtysh.c
vtysh_read_file); there are no inline comments -- so every comment
renders as its own '!' line(s) immediately before the annotated
element's first config line, one line per line of the comment value,
and empty / whitespace-only comments render nothing."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from frr_proteus.render import (
    render_bfd,
    render_bgp_instance,
    render_filters,
    render_interfaces,
    render_route_maps,
    render_system,
    render_vrfs,
)

if TYPE_CHECKING:
    from frr_proteus._generated import proteus as bindings
else:
    bindings = pytest.importorskip("frr_proteus._generated.proteus")

annotate = bindings.annotate
ProteusBgp = bindings.ProteusBgp


def _instance() -> bindings.ProteusBgp.Instance:
    instance = ProteusBgp.Instance(vrf="default")
    instance.autonomous_system.plain = 65001
    return instance


def test_instance_comment_before_router_bgp():
    instance = _instance()
    annotate(instance, comment="edge router main instance")
    rendered = render_bgp_instance(instance)
    assert rendered.startswith(
        "! edge router main instance\nrouter bgp 65001\n"
    )


def test_neighbor_and_peer_group_comments():
    instance = _instance()
    group = ProteusBgp.Instance.PeerGroup(name="FABRIC")
    group.remote_as.type = "external"
    annotate(group, comment="underlay fabric peers")
    instance.peer_group.append(group)
    neighbor = ProteusBgp.Instance.Neighbor(address="192.0.2.1")
    neighbor.remote_as.plain = 65010
    annotate(neighbor, comment="uplink to spine1")
    instance.neighbor.append(neighbor)
    rendered = render_bgp_instance(instance)
    assert " ! underlay fabric peers\n neighbor FABRIC peer-group\n" in rendered
    assert (
        " ! uplink to spine1\n neighbor 192.0.2.1 remote-as 65010\n" in rendered
    )


def test_multiline_comment_one_bang_line_each_and_blank_lines_dropped():
    instance = _instance()
    neighbor = ProteusBgp.Instance.Neighbor(address="192.0.2.1")
    neighbor.remote_as.plain = 65010
    annotate(neighbor, comment="first line\n\nsecond line\n   \n")
    instance.neighbor.append(neighbor)
    rendered = render_bgp_instance(instance)
    assert " ! first line\n ! second line\n neighbor 192.0.2.1" in rendered


def test_whitespace_only_comment_renders_nothing():
    instance = _instance()
    annotate(instance, comment="   \n  ")
    assert render_bgp_instance(instance).startswith("router bgp 65001\n")


def test_af_and_network_comments():
    instance = _instance()
    af = instance.afi_safis.ipv4_unicast
    annotate(af, comment="v4 table")
    network = ProteusBgp.Instance.AfiSafis.Ipv4Unicast.Network(
        prefix="203.0.113.0/24"
    )
    annotate(network, comment="customer prefix")
    af.network.append(network)
    rendered = render_bgp_instance(instance)
    assert " ! v4 table\n address-family ipv4 unicast\n" in rendered
    assert "  ! customer prefix\n  network 203.0.113.0/24\n" in rendered


def test_route_map_and_entry_comments():
    root = bindings.ProteusRouteMap()
    route_map = bindings.ProteusRouteMap.RouteMap(name="RM-IN")
    annotate(route_map, comment="ingress policy")
    entry = bindings.ProteusRouteMap.RouteMap.Entry(sequence=10, action="permit")
    annotate(entry, comment="allow all")
    route_map.entry.append(entry)
    root.route_map.append(route_map)
    assert render_route_maps(root) == (
        "! ingress policy\n"
        "! allow all\n"
        "route-map RM-IN permit 10\n"
        "exit\n"
    )


def test_prefix_list_and_entry_comments():
    root = bindings.ProteusFilter()
    prefix_list = bindings.ProteusFilter.PrefixLists.Ipv4.PrefixList(name="PL")
    annotate(prefix_list, comment="bogon filter")
    entry = bindings.ProteusFilter.PrefixLists.Ipv4.PrefixList.Entry(
        sequence=5, action="deny", prefix="10.0.0.0/8", le=32
    )
    annotate(entry, comment="rfc1918")
    prefix_list.entry.append(entry)
    root.prefix_lists.ipv4.prefix_list.append(prefix_list)
    assert render_filters(root) == (
        "! bogon filter\n"
        "! rfc1918\n"
        "ip prefix-list PL seq 5 deny 10.0.0.0/8 le 32\n"
    )


def test_bfd_profile_comment():
    root = bindings.ProteusBfd()
    profile = bindings.ProteusBfd.Profile(name="fast", receive_interval=100)
    annotate(profile, comment="fabric links")
    root.profile.append(profile)
    assert " ! fabric links\n profile fast\n" in render_bfd(root)


def test_vrf_interface_and_system_comments():
    vrfs = bindings.ProteusVrf()
    vrf = bindings.ProteusVrf.Vrf(name="tnt1", l3vni=15000001)
    annotate(vrf, comment="tenant one")
    vrfs.vrf.append(vrf)
    assert render_vrfs(vrfs).startswith("! tenant one\nvrf tnt1\n")

    interfaces = bindings.ProteusInterface()
    interface = bindings.ProteusInterface.Interface(name="lo")
    annotate(interface, comment="router loopback")
    interfaces.interface.append(interface)
    assert render_interfaces(interfaces).startswith(
        "! router loopback\ninterface lo\n"
    )

    system = bindings.ProteusSystem()
    system.hostname = "leaf1"
    annotate(system, comment="host preamble")
    assert render_system(system).startswith("! host preamble\nhostname leaf1\n")
