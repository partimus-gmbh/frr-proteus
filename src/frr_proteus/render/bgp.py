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
    evpn_configured=helpers.evpn_configured,
)

_bgp_template = _env.get_template("bgp.conf.j2")


def render_bgp_instance(instance) -> str:
    """Render one BGP instance into bgpd config text.

    `instance` is one entry of the generated `/bgp/instance` list
    (`frr_proteus._generated.proteus.ProteusBgp.Bgp.Instance`). Its
    `vrf` key selects the enclosing VRF; "default" (or unset) renders
    as a plain `router bgp <asn>` with no `vrf` clause, matching
    bgp_config_write() in bgpd/bgp_vty.c.

    Renderer scope is still steps 1+2 (basic BGP + EVPN); the schema
    models far more than this template renders, and every new field
    needs its CLI text confirmed against bgpd's config-write code
    before being added here.
    """
    if not instance.autonomous_system:
        raise ValueError("instance autonomous-system is not set")
    return _bgp_template.render(instance=instance)
