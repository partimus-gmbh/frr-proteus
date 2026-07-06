"""Render proteus-system host-level lines (frr defaults, hostname,
log syslog, service integrated-vtysh-config).

Text sources: lib/command.c vty_write_config ('frr defaults %s') and
config_write_host ('hostname %s'), lib/log_cli.c
logging_syslog_cli_write, vtysh/vtysh_config.c for the service line.
The model is deliberately minimal -- see proteus-system.yang.
"""

from __future__ import annotations

from frr_proteus.render import helpers
from frr_proteus.render._comments import render_with_comments
from frr_proteus.render._env import env
from frr_proteus.render._heading import with_heading

_template = env.get_template("system.conf.j2")


def render_system(root, *, heading: str | None = "!") -> str:
    """Render the global lines of a generated ProteusSystem root.

    Returns "" when nothing under /system is configured. `heading` defaults to "!" -- one bare separator line before
    the section; pass a title for a three-line '!' heading instead,
    or None for no prefix at all. Skipped when the section renders
    empty -- see render._heading.
    """
    if not helpers.has_config(root):
        return ""
    return with_heading(heading, render_with_comments(_template, system=root))
