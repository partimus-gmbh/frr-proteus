"""Experimental EVPN scheme: its own-syntax renderers, and a translator
to the standard (legacy) proteus model.

This module is the ONLY place that knows about the experimental EVPN
scheme (proteus-bgp-evpn-experimental.yang: vxlan-underlay,
auto-discover-vnis, underlay-vrf, origination-l3vni, vlan-based-evi, the
global 'evpn' block). The standard renderer (render.bgp / bgp_evpn_af.j2
/ render.vrf) is kept completely free of it.

Two ways to get config out:

  - render_experimental_bgp_instance / render_experimental_evpn_global
    emit the experimental scheme's OWN syntax (lossless -- no warnings).

  - translate_experimental_to_standard converts an experimental-scheme
    config into a pure legacy proteus model plus the zebra VRF L3VNI
    mappings, which you then hand to the STANDARD renderer
    (render_bgp_instance / render_vrfs). The workflow is:

        experimental config -> translate -> standard model -> standard
        renderer (which has no idea it ever came from the experimental
        model).

    The conversion is lossy wherever stock FRR has no equivalent; every
    loss raises an EvpnTranslationWarning here in the translator, so the
    standard renderer never has to warn about anything.
"""

from __future__ import annotations

import copy
import warnings
import typing
from typing import NamedTuple

from frr_proteus.render import helpers
from frr_proteus.render._comments import render_with_comments
from frr_proteus.render._heading import with_heading
from frr_proteus.render.bgp import _env, _render_bgp_block

__all__ = [
    "EvpnTranslationWarning",
    "StandardTranslation",
    "render_experimental_bgp_instance",
    "render_experimental_evpn_global",
    "translate_experimental_to_standard",
]

_evpn_global_template = _env.get_template("evpn_global.conf.j2")
_EXPERIMENTAL_EVPN_AF_TEMPLATE = "bgp_evpn_af_experimental.j2"


class EvpnTranslationWarning(UserWarning):
    """A configured experimental-EVPN statement was dropped or only
    approximately represented when translating to the standard (stock
    FRR) model. Raised only by translate_experimental_to_standard;
    rendering never warns."""


# --------------------------------------------------------------------------
# Experimental-syntax rendering (the scheme's own CLI, lossless)
# --------------------------------------------------------------------------


def render_experimental_bgp_instance(
    instance, *, heading: str | None = "!"
) -> str:
    """Render one BGP instance in the EXPERIMENTAL EVPN scheme's syntax
    (vxlan-underlay / auto-discover-vnis / underlay-vrf / origination-
    l3vni / vlan-based-evi); legacy EVPN command syntax is removed from
    the l2vpn-evpn AF. Everything outside that AF is identical to the
    standard render_bgp_instance -- both share bgp.conf.j2, which is
    format-agnostic scaffolding; only the AF template differs. Lossless,
    so no warnings.

    `heading` behaves as in render_bgp_instance (see render._heading).
    """
    return with_heading(
        heading,
        _render_bgp_block(
            instance, evpn_af_template=_EXPERIMENTAL_EVPN_AF_TEMPLATE
        ),
    )


def render_experimental_evpn_global(evpn, *, heading: str | None = "!") -> str:
    """Render the experimental scheme's global 'evpn' ... 'exit' block
    (proteus-bgp-evpn-experimental.yang's top-level `evpn` container).
    Returns "" when unconfigured. Experimental syntax only -- stock FRR
    has no equivalent, so translate_experimental_to_standard drops it
    (with a warning) rather than emitting anything for it.

    `heading` behaves as elsewhere (see render._heading).
    """
    if not helpers.has_config(evpn):
        return ""
    return with_heading(
        heading, render_with_comments(_evpn_global_template, evpn=evpn)
    )


# --------------------------------------------------------------------------
# Translation to the standard (legacy) model
# --------------------------------------------------------------------------


class StandardTranslation(NamedTuple):
    """The result of translate_experimental_to_standard -- a pure legacy
    proteus config the STANDARD renderer consumes.

    - ``bgp``: a ProteusBgp whose instances carry only legacy EVPN
      fields (the experimental ones are cleared). Render each entry with
      render_bgp_instance.
    - ``vrfs``: a ProteusVrf holding the named-VRF ``vrf NAME / vni N``
      L3VNI mappings translated from per-tenant origination-l3vni.
    - ``default_l3vni`` / ``default_l3vni_prefix_routes_only``: the
      default VRF's L3VNI, which is a GLOBAL top-level ``vni`` line with
      no proteus-vrf node -- pass both to render_vrfs.

    Render as, e.g.::

        t = translate_experimental_to_standard(bgp, evpn_global)
        text = (
            render_vrfs(
                t.vrfs,
                default_l3vni=t.default_l3vni,
                default_l3vni_prefix_routes_only=t.default_l3vni_prefix_routes_only,
            )
            + "".join(render_bgp_instance(i) for i in t.bgp.instance)
        )
    """

    # typing.Any, not the bindings classes: the generated package is
    # imported lazily so the render layer stays importable without it
    bgp: typing.Any
    vrfs: typing.Any
    default_l3vni: int | None
    default_l3vni_prefix_routes_only: bool


# stock FRR has no multi-underlay EVPN: only the default VRF can be the
# VXLAN underlay, so any non-"default" underlay reference is dropped.
_MULTI_UNDERLAY = (
    "'underlay-vrf {vrf}' has no equivalent in the standard (stock FRR) "
    "model and is dropped: FRR supports only a single default-VRF EVPN "
    "underlay (no multi-underlay EVPN)."
)

# route-target-set encodings shared by the EVI and legacy-VNI containers.
_RT_ENCODINGS = {"as2": "As2", "as4": "As4", "ipv4": "Ipv4"}


def _warn(message: str) -> None:
    # stacklevel=3: _warn -> _translate_* -> translate_experimental_to_standard
    warnings.warn(message, EvpnTranslationWarning, stacklevel=3)


def _copy_rt_values(src, dst) -> None:
    """Copy the fully qualified route targets (as2/as4/ipv4 global/local
    admin pairs) from one route-target-set container to another. Used to
    build a legacy per-VNI RT set from an EVI's; wildcard and auto are
    NOT copied -- a stock 'vni' block's RT lines can't express them."""
    for attr, cls_name in _RT_ENCODINGS.items():
        cls = getattr(type(dst), cls_name)
        for item in getattr(src, attr):
            getattr(dst, attr).append(
                cls(
                    global_admin=item.global_admin,
                    local_admin=item.local_admin,
                )
            )


def _copy_rd(src, dst) -> None:
    """Copy a pt:route-distinguisher container's encoding fields onto
    another instance of the grouping (the EVI's rd class and the legacy
    Vni's rd class are distinct generated types)."""
    for enc in ("as2", "ipv4", "as4"):
        getattr(dst, enc).administrator = getattr(src, enc).administrator
        getattr(dst, enc).assigned_number = getattr(src, enc).assigned_number
    dst.mac = src.mac
    dst.raw = src.raw


def _dropped_evi_rt_options(evi) -> list[str]:
    """RT options on `evi` a stock 'vni' block cannot express: import
    wildcard '*:NN', import auto, export auto."""
    dropped = []
    if evi.route_target_import.wildcard:
        dropped.append("import '*:NN' wildcard")
    if evi.route_target_import.auto:
        dropped.append("import auto")
    if evi.route_target_export.auto:
        dropped.append("export auto")
    return dropped


def translate_experimental_to_standard(bgp, evpn_global=None):
    """Convert an experimental-scheme config into the standard (legacy)
    proteus model the stock-FRR renderer consumes. Returns a
    StandardTranslation; emits an EvpnTranslationWarning per lossy drop.

    `bgp` is a ProteusBgp root; `evpn_global` is the optional
    ProteusBgpEvpnExperimental.Evpn container. The input is NOT mutated
    (it is deep-copied first), so the same tree can also be rendered
    natively via render_experimental_* without interference.

    Translations:
      - vxlan-underlay -> advertise-all-vni (warns when auto-discover-vnis
        is unset: advertise-all-vni auto-discovers regardless).
      - vlan-based-evi with origination-l2vni N -> a legacy 'vni N' block
        (rd, flooding, the advertise-default-gw/-svi-ip/-subnet overrides
        and the fully qualified route-targets are carried over; import
        wildcard/auto and export auto are dropped, with a warning; an EVI
        without an origination-l2vni is dropped entirely, with a
        warning). The block is placed in the DEFAULT-VRF instance
        regardless of where the EVI was declared -- including EVIs of
        the global 'evpn' block -- because stock FRR accepts 'vni'
        blocks only there; if no default-VRF instance exists, the EVI is
        dropped with a warning.
      - origination-l3vni -> a named 'vrf NAME / vni N' block (tenant
        VRFs) or the default VRF's global top-level 'vni N' line. It
        does NOT imply type-5 advertisement: 'advertise ipv4|ipv6
        unicast' is explicit config via the legacy
        advertise-ipv4-/ipv6-unicast containers (shared vocabulary,
        passed through untouched).
      - non-'default' underlay-vrf (instance, EVI, or the global
        default-underlay-vrf) has no stock-FRR equivalent and is dropped
        with a warning (FRR has no multi-underlay EVPN).
    """
    # Lazy import: the render layer stays importable without generated
    # bindings (tests importorskip them); only translation needs them.
    from frr_proteus._generated.proteus import (
        ProteusBgp,
        ProteusVrf,
        annotate,
        annotations,
    )

    Vni = ProteusBgp.Instance.AfiSafis.L2vpnEvpn.Vni

    std = copy.deepcopy(bgp)
    vrfs = ProteusVrf()
    default_l3vni: int | None = None
    default_l3vni_prefix_routes_only = False

    # Stock FRR accepts 'vni' blocks only in the default-VRF instance, so
    # every translated EVI lands there, wherever it was declared.
    default_instance = next(
        (i for i in std.instance if not i.vrf or i.vrf == "default"), None
    )

    def translate_evi(evi, eat: str) -> None:
        """Translate one vlan-based-evi (instance-level or global) into a
        legacy 'vni' block on the default instance, warning per lossy
        drop. `eat` names the EVI's declaration site in warnings."""
        if evi.underlay_vrf and evi.underlay_vrf != "default":
            _warn(f"{eat}: " + _MULTI_UNDERLAY.format(vrf=evi.underlay_vrf))
        if evi.origination_l2vni is None:
            _warn(
                f"{eat}: EVI has no origination-l2vni, so it has no "
                "stock-FRR 'vni' block to translate to and is dropped "
                "entirely."
            )
            return
        if default_instance is None:
            _warn(
                f"{eat}: no default-VRF BGP instance exists to hold the "
                "translated 'vni' block (stock FRR accepts 'vni' blocks "
                "only in the default instance), so the EVI is dropped "
                "entirely."
            )
            return
        dropped = _dropped_evi_rt_options(evi)
        if dropped:
            _warn(
                f"{eat}: route-target option(s) {', '.join(dropped)} have "
                "no equivalent in a stock-FRR 'vni' block and are dropped."
            )
        vni = Vni(vni_id=evi.origination_l2vni)
        _copy_rd(evi.rd, vni.rd)
        vni.flooding = evi.flooding
        _copy_rt_values(evi.route_target_import, vni.route_target_import)
        _copy_rt_values(evi.route_target_export, vni.route_target_export)
        _copy_rt_values(evi.route_target_both, vni.route_target_both)
        vni.advertise_default_gw = evi.advertise_default_gw
        vni.advertise_svi_ip = evi.advertise_svi_ip
        vni.advertise_subnet = evi.advertise_subnet
        # A stock 'vni N' block has no field for the EVI's name, so
        # preserve it as a comment on the synthesized node -- the
        # standard renderer emits it as a '!' line above the block.
        # Any comment the EVI itself carried is kept above it.
        name_comment = f"vlan-based-evi {evi.name}"
        existing = annotations(evi).get("comment")
        annotate(
            vni,
            comment=(
                f"{existing}\n{name_comment}" if existing else name_comment
            ),
        )
        default_instance.afi_safis.l2vpn_evpn.vni.append(vni)

    for instance in std.instance:
        evpn = instance.afi_safis.l2vpn_evpn
        at = f"router bgp vrf {instance.vrf}"

        if evpn.vxlan_underlay:
            evpn.advertise_all_vni = True
            if not evpn.auto_discover_vnis:
                _warn(
                    f"{at}: 'vxlan-underlay' becomes 'advertise-all-vni', "
                    "which auto-discovers all local VNIs -- "
                    "'auto-discover-vnis' is not set, but stock FRR behaves "
                    "as though it were (VNI auto-discovery cannot be "
                    "disabled)."
                )

        if evpn.underlay_vrf and evpn.underlay_vrf != "default":
            _warn(f"{at}: " + _MULTI_UNDERLAY.format(vrf=evpn.underlay_vrf))

        for evi in evpn.vlan_based_evi:
            translate_evi(evi, f"{at} vlan-based-evi {evi.name!r}")

        l3 = evpn.origination_l3vni
        if l3.vni is not None:
            if not instance.vrf or instance.vrf == "default":
                # default VRF -> global 'vni' line, not a block (unique
                # vrf key means at most one such instance).
                default_l3vni = l3.vni
                default_l3vni_prefix_routes_only = bool(l3.prefix_routes_only)
            else:
                vrfs.vrf.append(
                    ProteusVrf.Vrf(
                        name=instance.vrf,
                        l3vni=l3.vni,
                        prefix_routes_only=l3.prefix_routes_only or None,
                    )
                )

        # Strip every experimental field so the result is a pure legacy
        # model: the standard renderer's evpn_af_needed / has_config must
        # not see them, and bgp_evpn_af.j2 does not read them anyway.
        evpn.vxlan_underlay = None
        evpn.auto_discover_vnis = None
        evpn.underlay_vrf = None
        l3.vni = None
        l3.prefix_routes_only = None
        evpn.vlan_based_evi.clear()

    if evpn_global is not None:
        # The block itself has no stock-FRR equivalent, but its EVIs
        # translate exactly like instance-level ones; only the
        # default-underlay-vrf (when non-default) is a real loss.
        if (
            evpn_global.default_underlay_vrf
            and evpn_global.default_underlay_vrf != "default"
        ):
            _warn(
                "global 'evpn' block: 'default-underlay-vrf "
                f"{evpn_global.default_underlay_vrf}' has no equivalent in "
                "the standard (stock FRR) model and is dropped: FRR "
                "supports only a single default-VRF EVPN underlay (no "
                "multi-underlay EVPN)."
            )
        for evi in evpn_global.vlan_based_evi:
            translate_evi(evi, f"global 'evpn' vlan-based-evi {evi.name!r}")

    return StandardTranslation(
        std, vrfs, default_l3vni, default_l3vni_prefix_routes_only
    )
