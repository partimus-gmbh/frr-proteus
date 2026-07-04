import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from frr_proteus.render import render_bgp_instance

bindings = pytest.importorskip("frr_proteus._generated.frr_bgp")

Bgp = bindings.FrrRouting.Routing.ControlPlaneProtocols.ControlPlaneProtocol.Bgp


def _new_bgp():
    return Bgp()


def _add_neighbor(bgp, addr):
    neighbor = Bgp.Neighbors.Neighbor(remote_address=addr)
    bgp.neighbors.neighbor.append(neighbor)
    return neighbor


def _add_afi_safi(bgp, name):
    afi_safi = Bgp.Global.AfiSafis.AfiSafi(afi_safi_name=name)
    bgp.global_.afi_safis.afi_safi.append(afi_safi)
    return afi_safi


def test_router_bgp_header_and_trailing_bang():
    bgp = _new_bgp()
    bgp.global_.local_as = 65001
    text = render_bgp_instance(bgp)
    assert text.startswith("router bgp 65001\n")
    assert text.endswith("!\n")


def test_local_as_required():
    bgp = _new_bgp()
    with pytest.raises(ValueError, match="local-as"):
        render_bgp_instance(bgp)


def test_router_id_omitted_when_unset():
    bgp = _new_bgp()
    bgp.global_.local_as = 65001
    assert "router-id" not in render_bgp_instance(bgp)


def test_router_id_rendered_when_set():
    bgp = _new_bgp()
    bgp.global_.local_as = 65001
    bgp.global_.router_id = "10.0.0.1"
    assert " bgp router-id 10.0.0.1\n" in render_bgp_instance(bgp)


@pytest.mark.parametrize(
    "as_type,expected",
    [
        ("external", "neighbor 192.0.2.1 remote-as external"),
        ("internal", "neighbor 192.0.2.1 remote-as internal"),
    ],
)
def test_neighbor_remote_as_type(as_type, expected):
    bgp = _new_bgp()
    bgp.global_.local_as = 65001
    n = _add_neighbor(bgp, "192.0.2.1")
    n.neighbor_remote_as.remote_as_type = as_type
    assert expected in render_bgp_instance(bgp)


def test_neighbor_remote_as_specified():
    bgp = _new_bgp()
    bgp.global_.local_as = 65001
    n = _add_neighbor(bgp, "192.0.2.1")
    n.neighbor_remote_as.remote_as_type = "as-specified"
    n.neighbor_remote_as.remote_as = 65099
    assert "neighbor 192.0.2.1 remote-as 65099" in render_bgp_instance(bgp)


def test_network_statement_under_address_family():
    bgp = _new_bgp()
    bgp.global_.local_as = 65001
    afi_safi = _add_afi_safi(bgp, "ipv4-unicast")
    afi_safi.ipv4_unicast.network_config.append(
        Bgp.Global.AfiSafis.AfiSafi.Ipv4Unicast.NetworkConfig(prefix="192.0.2.0/24")
    )

    text = render_bgp_instance(bgp)
    assert " address-family ipv4 unicast\n" in text
    assert "  network 192.0.2.0/24\n" in text
    assert " exit-address-family\n" in text
    # bgpd's vty_frame(" !\n address-family ...") only flushes once the
    # block has content -- so a non-empty AF block is preceded by " !".
    assert " !\n address-family ipv4 unicast\n" in text


def test_address_family_omitted_when_no_networks():
    bgp = _new_bgp()
    bgp.global_.local_as = 65001
    _add_afi_safi(bgp, "ipv4-unicast")
    assert "address-family" not in render_bgp_instance(bgp)


def test_vrf_clause():
    bgp = _new_bgp()
    bgp.global_.local_as = 65001
    text = render_bgp_instance(bgp, vrf="RED")
    assert text.startswith("router bgp 65001 vrf RED\n")


def test_default_vrf_has_no_vrf_clause():
    bgp = _new_bgp()
    bgp.global_.local_as = 65001
    text = render_bgp_instance(bgp, vrf="default")
    assert text.startswith("router bgp 65001\n")
