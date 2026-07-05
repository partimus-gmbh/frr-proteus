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

_TEMPLATES_DIR = pathlib.Path(__file__).parent / "templates"

_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(_TEMPLATES_DIR),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
    undefined=jinja2.StrictUndefined,
)
_env.globals.update(
    evpn_af_needed=helpers.evpn_af_needed,
    route_target_texts=helpers.route_target_texts,
)
# As a Jinja *test* so templates can write
# `selectattr('afi_safis.ipv4_unicast.filters', 'has_config')`.
_env.tests["has_config"] = helpers.has_config

_bgp_template = _env.get_template("bgp.conf.j2")
_evpn_global_template = _env.get_template("evpn_global.conf.j2")

# Output format -> the template rendering the l2vpn evpn AF block.
# "frr": stock FRR syntax; legacy fields render as-is and the
#   experimental-scheme typing is translated where stock FRR can
#   express it (vlan-based-evi -> 'vni' block) and left out where it
#   can't (vxlan-underlay, underlay-vrf, origination-l3vni, ...).
# "experimental": the experimental config scheme's syntax; legacy
#   EVPN command syntax is removed from the output.
_EVPN_AF_TEMPLATES = {
    "frr": "bgp_evpn_af.j2",
    "experimental": "bgp_evpn_af_experimental.j2",
}


def _evpn_af_template(format: str) -> str:
    try:
        return _EVPN_AF_TEMPLATES[format]
    except KeyError:
        raise ValueError(
            f"unknown output format {format!r}; expected one of "
            f"{sorted(_EVPN_AF_TEMPLATES)}"
        ) from None


def render_bgp_instance(instance, *, format: str = "frr") -> str:
    """Render one BGP instance into bgpd config text.

    `instance` is one entry of the generated `/bgp/instance` list
    (`frr_proteus._generated.proteus.ProteusBgp.Bgp.Instance`). Its
    `vrf` key selects the enclosing VRF; "default" (or unset) renders
    as a plain `router bgp <asn>` with no `vrf` clause, matching
    bgp_config_write() in bgpd/bgp_vty.c.

    `format` picks the output syntax for the EVPN address-family:
    "frr" (default, stock FRR; experimental-scheme fields are
    translated where possible and otherwise left out) or
    "experimental" (the experimental EVPN config scheme; legacy EVPN
    command syntax is removed). Everything outside the EVPN AF renders
    identically in both formats.

    Renderer scope is still steps 1+2 (basic BGP + EVPN) plus the
    experimental scheme; the schema models far more than these
    templates render, and every new *stock* field needs its CLI text
    confirmed against bgpd's config-write code before being added.
    """
    if not instance.autonomous_system:
        raise ValueError("instance autonomous-system is not set")
    return _bgp_template.render(
        instance=instance,
        format=format,
        evpn_af_template=_evpn_af_template(format),
    )


def render_evpn_global(evpn, *, format: str = "frr") -> str:
    """Render the experimental scheme's global 'evpn' ... 'exit' block.

    `evpn` is the generated top-level container
    (`frr_proteus._generated.proteus.ProteusBgpEvpnExperimental`'s
    `.evpn`). Only the "experimental" format has this block; in the
    "frr" format (and whenever the container holds no config) the
    result is the empty string -- stock FRR has no equivalent to
    translate it to, so per the compatibility rules it is left out.
    """
    _evpn_af_template(format)  # validate the format name
    if format != "experimental" or not helpers.has_config(evpn):
        return ""
    return _evpn_global_template.render(evpn=evpn)
