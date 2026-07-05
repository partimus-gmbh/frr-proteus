"""Render proteus-bfd profiles into the 'bfd' config block.

Text source: bfdd/bfdd_cli.c's cli_show callbacks (bfdd is
northbound-converted): ' profile NAME' with two-space-indented leaves,
' exit' per profile, 'exit' closing the block. Intervals are modeled
in milliseconds, matching the CLI (FRR's own YANG stores microseconds
and divides by 1000 on write).
"""

from __future__ import annotations

from frr_proteus.render._env import env

_template = env.get_template("bfd.conf.j2")


def render_bfd(root) -> str:
    """Render the 'bfd' block of a generated ProteusBfd root.

    Returns "" when no profiles are configured (an empty 'bfd'/'exit'
    pair would be pointless, if harmless).
    """
    if not root.bfd.profile:
        return ""
    return _template.render(bfd=root.bfd)
