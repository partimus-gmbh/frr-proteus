"""Render a proteus-bgp YANG instance into bgpd CLI config text.

FRR's bgpd has no northbound backend: unlike staticd, ripd, and other
YANG-converted daemons, there is no bgpd/bgp_nb.c and no `cli_show`
callbacks to reuse (confirmed by `grep -rn cli_show frr/bgpd/` -- zero
hits). So there is no existing YANG-to-text mapping to derive
automatically. templates/bgp.conf.j2 hand-replicates the relevant
`vty_out` calls from bgpd/bgp_vty.c (`bgp_config_write`,
`bgp_config_write_family`, the neighbor remote-as printing block);
the Jinja environment setup lives here and the one field-picking
helper in helpers.py. Codegen (the pybind-dataclass plugin in our
pyangbind fork) only gets us the typed input structure -- not this
rendering layer.

The input schema is the custom self-contained model
(yang/custom/proteus-bgp.yang, generated as
frr_proteus._generated.proteus). The old FRR-schema bindings
(_generated/frr_bgp, from frr/yang + yang/augments) are still
generated for reference but have no renderer anymore.
"""

from __future__ import annotations

import pathlib

import jinja2

from frr_proteus.render import helpers
from frr_proteus.render._comments import render_with_comments
from frr_proteus.render._heading import with_heading

_TEMPLATES_DIR = pathlib.Path(__file__).parent / "templates"

_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(_TEMPLATES_DIR),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
    undefined=jinja2.StrictUndefined,
)
_env.globals.update(
    route_target_texts=helpers.route_target_texts,
    route_origin_text=helpers.route_origin_text,
    rd_text=helpers.rd_text,
    asn_text=helpers.asn_text,
    remote_as_text=helpers.remote_as_text,
    confederation_peers_texts=helpers.confederation_peers_texts,
)
# As a Jinja *test* so templates can write
# `selectattr('afi_safis.ipv4_unicast.filters', 'has_config')`.
_env.tests["has_config"] = helpers.has_config

_bgp_template = _env.get_template("bgp.conf.j2")
_bgp_process_template = _env.get_template("bgp_process.conf.j2")

# The stock-FRR l2vpn-evpn AF template. The experimental-syntax variant
# ("bgp_evpn_af_experimental.j2") is selected by render.experimental via
# _render_bgp_block -- bgp.conf.j2 is neutral scaffolding shared by both,
# but this standard module only ever emits the legacy one.
_STANDARD_EVPN_AF_TEMPLATE = "bgp_evpn_af.j2"


def _render_bgp_block(instance, *, evpn_af_template: str) -> str:
    """Render one 'router bgp' block (no heading) using `evpn_af_template`
    for the l2vpn-evpn AF. Shared by render_bgp_instance (legacy AF) and
    render.experimental (experimental-syntax AF); bgp.conf.j2 itself is
    format-agnostic scaffolding -- it just includes the given AF template
    and gates it on `render_evpn_af`."""
    if helpers.asn_text(instance.autonomous_system) is None:
        raise ValueError("instance autonomous-system is not set")
    return render_with_comments(
        _bgp_template,
        instance=instance,
        evpn_af_template=evpn_af_template,
        render_evpn_af=helpers.evpn_af_needed(instance),
    )


def render_bgp_instance(instance, *, heading: str | None = "!") -> str:
    """Render one BGP instance into stock-FRR bgpd config text.

    `instance` is one entry of the generated `/bgp/instance` list
    (`frr_proteus._generated.proteus.ProteusBgp.Instance`). Its `vrf`
    key selects the enclosing VRF; "default" (or unset) renders as a
    plain `router bgp <asn>` with no `vrf` clause, matching
    bgp_config_write() in bgpd/bgp_vty.c.

    This is the STANDARD renderer: it renders the proteus-bgp legacy
    model and has NO knowledge of the experimental EVPN scheme. To
    render experimental-scheme config as stock FRR, translate it first
    with render.experimental.translate_experimental_to_standard and
    render the resulting legacy model here. To render it in the
    experimental scheme's own syntax, use
    render.experimental.render_experimental_bgp_instance.

    Contract: feed a legacy (or translated) model. Any experimental
    fields still set on the instance are IGNORED, not rendered -- the
    renderer never translates. (Because the AF-block gate is a plain
    field-agnostic has_config, an *untranslated* instance whose only
    EVPN config is experimental will emit an empty 'address-family
    l2vpn evpn' block; that is misuse, and suppressing it would require
    the standard renderer to know which fields are experimental, i.e.
    the very coupling this split removes.)

    The renderer covers the full proteus-bgp.yang instance surface
    (all eight non-EVPN address families, the complete neighbor
    session/per-AF vocabulary, instance-level knobs, and the legacy
    EVPN AF incl. multihoming/dup-addr-detection/type-5 networks);
    every rendered line's CLI text is confirmed against bgpd's
    config-write code -- keep that rule for anything new. Process-wide
    'bgp ...' lines are separate: see render_bgp_process().

    `heading` defaults to "!" -- one bare separator line before
    the section; pass a title for a three-line '!' heading instead,
    or None for no prefix at all. Skipped when the section renders
    empty -- see render._heading.
    """
    return with_heading(
        heading, _render_bgp_block(instance, evpn_af_template=_STANDARD_EVPN_AF_TEMPLATE)
    )


def render_bgp_process(process, *, heading: str | None = "!") -> str:
    """Render the process-wide `/bgp/process` container into the 'bgp
    ...' lines FRR writes before any 'router bgp' block (the bm->
    globals at the top of bgp_config_write in bgpd/bgp_vty.c).

    `process` is the generated `ProteusBgp.Bgp.Process` container.
    Returns the empty string when nothing in it is configured, so
    callers can unconditionally prepend it to a composed frr.conf.
    `heading` defaults to "!" -- one bare separator line before
    the section; pass a title for a three-line '!' heading instead,
    or None for no prefix at all. Skipped when the section renders
    empty -- see render._heading.
    """
    if not helpers.has_config(process):
        return ""
    return with_heading(
        heading, render_with_comments(_bgp_process_template, process=process)
    )
