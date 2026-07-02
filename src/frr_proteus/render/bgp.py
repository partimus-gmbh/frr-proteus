"""Render a pyangbind FRR-BGP YANG instance into bgpd CLI config text.

FRR's bgpd has no northbound backend: unlike staticd, ripd, and other
YANG-converted daemons, there is no bgpd/bgp_nb.c and no `cli_show`
callbacks to reuse (confirmed by `grep -rn cli_show frr/bgpd/` -- zero
hits). So there is no existing YANG-to-text mapping to derive
automatically. templates/bgp.conf.j2 hand-replicates the relevant
`vty_out` calls from bgpd/bgp_vty.c (`bgp_config_write`,
`bgp_config_write_family`, the neighbor remote-as printing block); the
Jinja environment setup and field-picking helpers live here and in
helpers.py. Codegen (pyangbind) only gets us the typed, validated input
structure -- not this rendering layer.
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
    remote_as_text=helpers.remote_as_text,
    afi_safi_name=helpers.afi_safi_name,
    afi_safi_cli_text=helpers.afi_safi_cli_text,
    afi_safi_networks=helpers.afi_safi_networks,
    neighbor_afi_safi=helpers.neighbor_afi_safi,
)

_bgp_template = _env.get_template("bgp.conf.j2")


def render_bgp_instance(bgp, *, vrf: str | None = None) -> str:
    """Render one BGP YANG instance into bgpd config text.

    `bgp` is the pyangbind `bgp` container reachable at
    `.../control-plane-protocol/bgp` (i.e. `control_plane_protocol.bgp`,
    not the list entry itself). `vrf` is the name of the VRF this instance
    is bound to; leave it as None (or pass "default") for bgpd's default
    instance, which renders as a plain `router bgp <asn>` with no `vrf`
    clause, matching bgp_config_write() in bgpd/bgp_vty.c.
    """
    if not bgp.global_.local_as:
        raise ValueError("bgp global/local-as is not set")
    return _bgp_template.render(bgp=bgp, vrf=vrf)
