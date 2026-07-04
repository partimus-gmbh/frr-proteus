"""On-assignment validation of the generated bindings.

The bindings are generated with the fork's --dataclass-validation flag
(see scripts/generate_bindings.py), so YANG type restrictions are
enforced when values are assigned -- including dataclass __init__
kwargs. These tests pin the behaviors frr-proteus relies on; the
exhaustive per-restriction coverage belongs in the pyangbind fork.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

bindings = pytest.importorskip("frr_proteus._generated.frr_bgp")

Bgp = bindings.FrrRouting.Routing.ControlPlaneProtocols.ControlPlaneProtocol.Bgp
Vni = Bgp.Global.AfiSafis.AfiSafi.L2vpnEvpn.Vni


def test_valid_values_pass():
    bgp = Bgp()
    bgp.global_.local_as = 65001
    bgp.global_.router_id = "10.0.0.1"
    Vni(vni_id=101, rd="10.10.10.10:101", route_target_import=["65000:101"])


def test_none_is_always_allowed():
    bgp = Bgp()
    bgp.global_.router_id = "10.0.0.1"
    bgp.global_.router_id = None


def test_yang_defaults_not_applied():
    # Generated WITHOUT --dataclass-defaults: even leaves that carry a
    # YANG default (e.g. local-pref 100) must be None when unset, so the
    # renderers' "falsy means not configured" contract holds.
    assert Bgp.Global().local_pref is None
    assert Bgp.Global().ebgp_requires_policy is None


def test_range_violation_rejected():
    with pytest.raises(bindings.YangValidationError, match="out of range"):
        Vni(vni_id=99999999)  # vni-id range is 1..16777215


def test_builtin_int_bounds_rejected():
    bgp = Bgp()
    with pytest.raises(bindings.YangValidationError, match="out of range"):
        bgp.global_.local_as = 2**33  # local-as is a uint32


def test_wrong_type_rejected():
    bgp = Bgp()
    with pytest.raises(bindings.YangValidationError, match="int-compatible"):
        bgp.global_.local_as = "not-an-int"


def test_enum_value_rejected():
    neighbor = Bgp.Neighbors.Neighbor(remote_address="192.0.2.1")
    with pytest.raises(bindings.YangValidationError, match="allowed values"):
        neighbor.neighbor_remote_as.remote_as_type = "bogus"


def test_identityref_accepts_bare_and_prefixed():
    Bgp.Global.AfiSafis.AfiSafi(afi_safi_name="l2vpn-evpn")
    Bgp.Global.AfiSafis.AfiSafi(afi_safi_name="frr-routing:ipv4-unicast")


def test_identityref_rejects_unknown():
    with pytest.raises(bindings.YangValidationError, match="allowed values"):
        Bgp.Global.AfiSafis.AfiSafi(afi_safi_name="no-such-afi")


def test_pattern_violation_rejected():
    bgp = Bgp()
    with pytest.raises(bindings.YangValidationError, match="pattern"):
        bgp.global_.router_id = "999.999.999.999"  # not an ipv4-address


def test_leaf_list_elements_validated_on_assignment():
    with pytest.raises(bindings.YangValidationError, match="str-compatible"):
        Vni(vni_id=101, route_target_import=[42])
