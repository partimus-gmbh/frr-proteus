"""Showcase the experimental EVPN config scheme AND its stock-FRR
translation from one structured tree.

The whole point of the experimental EVPN models
(proteus-bgp-evpn-experimental.yang) is that the *typing* is richer
than stock FRR's CLI: `vxlan-underlay`, `auto-discover-vnis`,
`underlay-vrf` leafrefs, per-VRF `origination-l3vni`, `vlan-based-evi`
blocks and a global `evpn` block. This example builds ONE experimental
config object and emits it two ways -- via two SEPARATE code paths:

  1. Experimental syntax, rendered directly by the experimental
     renderers (render_experimental_bgp_instance /
     render_experimental_evpn_global): the new scheme's own CLI,
     verbatim and lossless.

  2. Stock FRR syntax, via the TRANSLATOR: the experimental config goes
     through translate_experimental_to_standard, which converts it into
     a pure *legacy* proteus model (advertise-all-vni, legacy `vni`
     blocks, zebra `vrf`/global `vni` L3VNI mappings), which the STANDARD
     renderers (render_bgp_instance / render_vrfs) then emit. The
     standard renderers never see -- or know about -- the experimental
     scheme; they just render a legacy model:

         experimental config -> translate -> standard model -> standard
         renderer

     The conversion is lossy where stock FRR has no equivalent
     (auto-discover-vnis, non-default underlay-vrf, wildcard/auto RTs on
     a translated EVI, an EVI with no L2VNI, the global block's
     default-underlay-vrf); the translator raises an
     EvpnTranslationWarning for each, which this example captures and
     prints. Where stock FRR does have an equivalent the translation is
     faithful: EVIs (including the global block's) become 'vni' blocks
     in the default instance, and origination-l3vni becomes the zebra
     L3VNI mapping ('advertise ipv4/ipv6 unicast' is explicit shared
     config, never synthesized).

Topology: one EVPN VTEP. The default instance is the VXLAN underlay
(marked vxlan-underlay, VNIs auto-discovered, a default-VRF L3VNI) with
an eBGP EVPN overlay neighbor; two tenant VRFs ride that underlay via
underlay-vrf leafrefs, each originating an L3VNI; a couple of
vlan-based-evi blocks map L2VNIs; and a global `evpn` block sets the
default underlay VRF and one shared EVI.

Run with the generated bindings on the path:
    PYTHONPATH=src python3 examples/evpn_experimental.py
"""

import ipaddress
import pathlib
import sys
import warnings
from typing import TypeAlias

sys.path.insert(0, "src")

from frr_proteus._generated.proteus import (
    ProteusBgp,
    ProteusBgpEvpnExperimental,
    validate_tree,
)
from frr_proteus.render import (
    EvpnTranslationWarning,
    heading,
    render_bgp_instance,
    render_experimental_bgp_instance,
    render_experimental_evpn_global,
    render_vrfs,
    translate_experimental_to_standard,
)

OUT_DIR = pathlib.Path(__file__).resolve().parent.parent / "out"

Instance: TypeAlias = ProteusBgp.Instance
EvpnAf: TypeAlias = Instance.AfiSafis.L2vpnEvpn
GlobalEvpn: TypeAlias = ProteusBgpEvpnExperimental.Evpn

LOCAL_AS = 65000
ROUTER_ID = "10.10.10.10"
UNDERLAY_VRF = "default"  # the instance marked vxlan-underlay

# tenant VRF -> L3VNI it originates
TENANTS = {"vrf-red": 5001, "vrf-blue": 5002}
# vlan-based-evi name -> L2VNI, on the underlay instance
EVIS = {"evi-100": 100, "evi-200": 200}


def build_underlay_instance() -> Instance:
    """The default instance IS the VXLAN underlay: vxlan-underlay
    (translates to advertise-all-vni in frr format) + auto-discover-vnis
    (no stock equivalent, dropped in frr format), an eBGP EVPN overlay
    neighbor (shared, renders in both formats), and vlan-based-evi
    blocks whose L2VNIs translate to `vni` blocks."""
    inst = Instance(vrf=UNDERLAY_VRF, router_id=ROUTER_ID)
    inst.autonomous_system.plain = LOCAL_AS

    neighbor = Instance.Neighbor(address=ipaddress.ip_address("10.30.30.30"))
    neighbor.remote_as.type = "external"
    neighbor.afi_safis.l2vpn_evpn.activate = True
    inst.neighbor.append(neighbor)

    evpn = inst.afi_safis.l2vpn_evpn
    evpn.vxlan_underlay = True
    evpn.auto_discover_vnis = True
    # An L3VNI on the default VRF: the translator turns this into a
    # GLOBAL, unindented top-level `vni N` statement (not a `vrf default`
    # block) -- surfaced as render_vrfs's default_l3vni scalar.
    evpn.origination_l3vni.vni = 4000
    # Shared route-targets: plain AS:NN, expressible in both syntaxes,
    # so they render identically either way.
    evpn.route_target_import.as2.append(
        EvpnAf.RouteTargetImport.As2(global_admin=LOCAL_AS, local_admin=1)
    )
    evpn.route_target_export.as2.append(
        EvpnAf.RouteTargetExport.As2(global_admin=LOCAL_AS, local_admin=1)
    )

    for name, l2vni in EVIS.items():
        evi = EvpnAf.VlanBasedEvi(name=name, origination_l2vni=l2vni)
        evi.underlay_vrf = UNDERLAY_VRF
        evi.route_target_both.as2.append(
            EvpnAf.VlanBasedEvi.RouteTargetBoth.As2(
                global_admin=LOCAL_AS, local_admin=l2vni
            )
        )
        evpn.vlan_based_evi.append(evi)

    # An auto-derived import RT on one EVI: valid in the experimental
    # scheme, but a stock-FRR 'vni' block's RT lines can't express
    # 'auto' -- so the frr translation drops it and warns.
    evpn.vlan_based_evi[0].route_target_import.auto = True

    return inst


def build_tenant_instance(vrf: str, l3vni: int) -> Instance:
    """A tenant VRF riding the underlay: an underlay-vrf leafref (its
    'default' target is representable, so no warning) plus
    origination-l3vni, which the frr format turns into the zebra
    'vrf NAME / vni N' mapping. Type-5 advertisement is EXPLICIT
    config (origination-l3vni deliberately does not imply it): the
    legacy advertise-ipv4-/ipv6-unicast containers are shared
    vocabulary rendering identically in both formats, like the
    auto/wildcard route-targets."""
    inst = Instance(vrf=vrf)
    inst.autonomous_system.plain = LOCAL_AS

    evpn = inst.afi_safis.l2vpn_evpn
    evpn.underlay_vrf = UNDERLAY_VRF
    evpn.origination_l3vni.vni = l3vni
    evpn.origination_l3vni.prefix_routes_only = True
    evpn.advertise_ipv4_unicast.enabled = True
    evpn.advertise_ipv6_unicast.enabled = True
    evpn.route_target_import.auto = True
    evpn.route_target_export.auto = True
    evpn.route_target_import.wildcard = [l3vni]
    return inst


def build_global_evpn() -> GlobalEvpn:
    """The global `evpn` block: only the experimental renderer emits the
    block itself, but its EVIs still translate -- stock FRR has no
    global EVI construct, so the translator moves them into the default
    instance's 'vni' list (the only place a 'vni' block may live)."""
    evpn = GlobalEvpn()
    evpn.default_underlay_vrf = UNDERLAY_VRF

    evi = GlobalEvpn.VlanBasedEvi(name="evi-shared", origination_l2vni=999)
    evi.underlay_vrf = UNDERLAY_VRF
    evi.route_target_import.as2.append(
        GlobalEvpn.VlanBasedEvi.RouteTargetImport.As2(
            global_admin=LOCAL_AS, local_admin=999
        )
    )
    evpn.vlan_based_evi.append(evi)
    return evpn


def render_experimental(bgp: ProteusBgp, global_evpn: GlobalEvpn) -> str:
    """Emit the experimental scheme's OWN syntax, directly (path 1)."""
    return (
        heading("bgp")
        + "".join(
            render_experimental_bgp_instance(inst) for inst in bgp.instance
        )
        + render_experimental_evpn_global(global_evpn, heading="evpn global")
    )


def render_standard(bgp: ProteusBgp, global_evpn: GlobalEvpn) -> str:
    """Translate the experimental config to a legacy model, then emit it
    with the STANDARD renderers (path 2).

    The translator yields a legacy ProteusBgp plus the zebra VRF L3VNI
    mappings (named `vrf` blocks and the default VRF's global `vni`
    scalar). We render them dependency-first: the zebra `vrf`/global-vni
    section before the `router bgp` blocks. Nothing here is aware of the
    experimental scheme -- render_bgp_instance / render_vrfs just see a
    legacy model."""
    result = translate_experimental_to_standard(bgp, global_evpn)
    return (
        render_vrfs(
            result.vrfs,
            heading="vrf l3vni mappings (translated)",
            default_l3vni=result.default_l3vni,
            default_l3vni_prefix_routes_only=(
                result.default_l3vni_prefix_routes_only
            ),
        )
        + heading("bgp")
        + "".join(render_bgp_instance(inst) for inst in result.bgp.instance)
    )


def main() -> None:
    bgp = ProteusBgp()
    bgp.instance.append(build_underlay_instance())
    bgp.instance.extend(
        build_tenant_instance(vrf, l3vni) for vrf, l3vni in TENANTS.items()
    )
    global_evpn = build_global_evpn()

    # Both module roots together: the underlay-vrf/default-underlay-vrf
    # leafrefs and their vxlan-underlay `must` guards resolve across
    # the two roots (the experimental refs point into proteus-bgp's
    # instance list).
    validate_tree(bgp, global_evpn)

    OUT_DIR.mkdir(exist_ok=True)

    # Path 1: experimental syntax (lossless, no warnings).
    exp_text = render_experimental(bgp, global_evpn)
    (OUT_DIR / "evpn_experimental_exp.conf").write_text(exp_text)
    print("--- out/evpn_experimental_exp.conf (experimental syntax) ---")
    print(exp_text, end="")
    print()

    # Path 2: translate -> standard model -> standard renderer. Capture
    # the translator's lossiness warnings and show them.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", EvpnTranslationWarning)
        std_text = render_standard(bgp, global_evpn)
    (OUT_DIR / "evpn_experimental_frr.conf").write_text(std_text)
    print("--- out/evpn_experimental_frr.conf (stock FRR, via translator) ---")
    print(std_text, end="")
    print()
    for w in caught:
        print(f"[translation warning] {w.message}")


if __name__ == "__main__":
    main()
