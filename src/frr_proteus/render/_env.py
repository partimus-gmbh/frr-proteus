"""Shared Jinja2 environment for the object renderers.

Same settings as the BGP renderer's environment in bgp.py (which
predates this module and keeps its own instance): StrictUndefined so
template typos fail loudly, trim/lstrip so templates can be indented
readably, keep_trailing_newline so rendered blocks concatenate.
"""

from __future__ import annotations

import pathlib

import jinja2

from frr_proteus.render import helpers

_TEMPLATES_DIR = pathlib.Path(__file__).parent / "templates"

env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(_TEMPLATES_DIR),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
    undefined=jinja2.StrictUndefined,
)

env.globals.update(
    asn_text=helpers.asn_text,
    rd_text=helpers.rd_text,
    community_texts=helpers.community_texts,
    large_community_texts=helpers.large_community_texts,
    community_value_text=helpers.community_value_text,
    extcommunity_texts=helpers.extcommunity_texts,
    extcommunity_nt_texts=helpers.extcommunity_nt_texts,
    extcommunity_color_texts=helpers.extcommunity_color_texts,
    route_target_texts=helpers.route_target_texts,
    route_origin_text=helpers.route_origin_text,
    has_config=helpers.has_config,
)
