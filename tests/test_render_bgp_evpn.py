import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from frr_proteus.render import render_bgp_instance

pyangbind_bindings = pytest.importorskip("frr_proteus._generated.frr_bgp")


def _new_bgp(vrf="default"):
    routing = pyangbind_bindings.frr_routing()
    proto = routing.routing.control_plane_protocols.control_plane_protocol.add(
        f"frr-bgp:bgp bgp {vrf}"
    )
    return proto.bgp


def _evpn_af(bgp):
    return bgp.global_.afi_safis.afi_safi.add("frr-rt:l2vpn-evpn").l2vpn_evpn


def test_advertise_all_vni():
    bgp = _new_bgp()
    bgp.global_.local_as = 65000
    _evpn_af(bgp).advertise_all_vni = True

    text = render_bgp_instance(bgp)
    assert " address-family l2vpn evpn\n" in text
    assert "  advertise-all-vni\n" in text
    assert " exit-address-family\n" in text


def test_advertise_default_gw_and_svi_ip_and_resolve_overlay():
    bgp = _new_bgp()
    bgp.global_.local_as = 65000
    evpn = _evpn_af(bgp)
    evpn.advertise_default_gw = True
    evpn.advertise_svi_ip = True
    evpn.enable_resolve_overlay_index = True

    text = render_bgp_instance(bgp)
    assert "  advertise-default-gw\n" in text
    assert "  advertise-svi-ip\n" in text
    assert "  enable-resolve-overlay-index\n" in text


@pytest.mark.parametrize("value", ["disable", "head-end-replication"])
def test_flooding(value):
    bgp = _new_bgp()
    bgp.global_.local_as = 65000
    _evpn_af(bgp).flooding = value

    assert f"  flooding {value}\n" in render_bgp_instance(bgp)


def test_vni_block():
    bgp = _new_bgp()
    bgp.global_.local_as = 65000
    vni = _evpn_af(bgp).vni.add(101)
    vni.rd = "10.10.10.10:101"
    vni.route_target_import.append("65000:101")
    vni.route_target_export.append("65000:101")
    vni.route_target_both.append("65000:999")
    vni.flooding = "disable"

    text = render_bgp_instance(bgp)
    assert "  vni 101\n" in text
    assert "   rd 10.10.10.10:101\n" in text
    assert "   route-target import 65000:101\n" in text
    assert "   route-target export 65000:101\n" in text
    assert "   route-target both 65000:999\n" in text
    assert "   flooding disable\n" in text
    assert "  exit-vni\n" in text


def test_vrf_rd_and_route_target():
    bgp = _new_bgp(vrf="vrf-red")
    bgp.global_.local_as = 65000
    evpn = _evpn_af(bgp)
    evpn.rd = "10.10.10.10:101"
    evpn.route_target_import.append("*:300")
    evpn.route_target_import.append("auto")

    text = render_bgp_instance(bgp, vrf="vrf-red")
    assert "  rd 10.10.10.10:101\n" in text
    assert "  route-target import *:300\n" in text
    assert "  route-target import auto\n" in text


@pytest.mark.parametrize(
    "gateway_ip,route_map,expected",
    [
        (False, None, "advertise ipv4 unicast\n"),
        (True, None, "advertise ipv4 unicast gateway-ip\n"),
        (False, "RMAP4", "advertise ipv4 unicast route-map RMAP4\n"),
        (True, "RMAP4", "advertise ipv4 unicast gateway-ip route-map RMAP4\n"),
    ],
)
def test_advertise_ipv4_unicast(gateway_ip, route_map, expected):
    bgp = _new_bgp(vrf="vrf-purple")
    bgp.global_.local_as = 65000
    evpn = _evpn_af(bgp)
    evpn.advertise_ipv4_unicast.enabled = True
    evpn.advertise_ipv4_unicast.gateway_ip = gateway_ip
    if route_map:
        evpn.advertise_ipv4_unicast.route_map = route_map

    text = render_bgp_instance(bgp, vrf="vrf-purple")
    assert f"  {expected}" in text


def test_advertise_ipv6_unicast():
    bgp = _new_bgp(vrf="vrf-purple")
    bgp.global_.local_as = 65000
    _evpn_af(bgp).advertise_ipv6_unicast.enabled = True

    assert "  advertise ipv6 unicast\n" in render_bgp_instance(bgp, vrf="vrf-purple")


def test_neighbor_evpn_activate():
    bgp = _new_bgp()
    bgp.global_.local_as = 65000
    _evpn_af(bgp)  # "address-family l2vpn evpn" must be entered at the instance level too
    n = bgp.neighbors.neighbor.add("192.0.2.1")
    n.neighbor_remote_as.remote_as_type = "internal"
    n.afi_safis.afi_safi.add("frr-rt:l2vpn-evpn").enabled = True

    assert "  neighbor 192.0.2.1 activate\n" in render_bgp_instance(bgp)


def test_neighbor_evpn_route_reflector_client():
    bgp = _new_bgp()
    bgp.global_.local_as = 65000
    _evpn_af(bgp)
    n = bgp.neighbors.neighbor.add("192.0.2.1")
    n_afi = n.afi_safis.afi_safi.add("frr-rt:l2vpn-evpn")
    n_afi.l2vpn_evpn.route_reflector.route_reflector_client = True

    assert "  neighbor 192.0.2.1 route-reflector-client\n" in render_bgp_instance(bgp)


def test_neighbor_evpn_route_map_in_and_out():
    bgp = _new_bgp()
    bgp.global_.local_as = 65000
    _evpn_af(bgp)
    n = bgp.neighbors.neighbor.add("192.0.2.1")
    n_afi = n.afi_safis.afi_safi.add("frr-rt:l2vpn-evpn")
    n_afi.l2vpn_evpn.filter_config.rmap_import = "RM-IN"
    n_afi.l2vpn_evpn.filter_config.rmap_export = "RM-OUT"

    text = render_bgp_instance(bgp)
    assert "  neighbor 192.0.2.1 route-map RM-IN in\n" in text
    assert "  neighbor 192.0.2.1 route-map RM-OUT out\n" in text


def test_neighbor_evpn_allowas_in():
    bgp = _new_bgp()
    bgp.global_.local_as = 65000
    _evpn_af(bgp)
    n = bgp.neighbors.neighbor.add("192.0.2.1")
    n_afi = n.afi_safis.afi_safi.add("frr-rt:l2vpn-evpn")
    n_afi.l2vpn_evpn.as_path_options.allow_own_as = 2

    assert "  neighbor 192.0.2.1 allowas-in 2\n" in render_bgp_instance(bgp)


def test_evpn_af_omitted_when_instance_not_evpn_enabled():
    bgp = _new_bgp()
    bgp.global_.local_as = 65000
    n = bgp.neighbors.neighbor.add("192.0.2.1")
    n.neighbor_remote_as.remote_as_type = "internal"
    # No l2vpn-evpn afi-safi entry anywhere -- the AF block itself must
    # not appear at all.
    assert "address-family l2vpn evpn" not in render_bgp_instance(bgp)
