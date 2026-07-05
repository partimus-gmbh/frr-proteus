"""Shared Jinja2 environment for the object renderers.

Same settings as the BGP renderer's environment in bgp.py (which
predates this module and keeps its own instance): StrictUndefined so
template typos fail loudly, trim/lstrip so templates can be indented
readably, keep_trailing_newline so rendered blocks concatenate.
"""

from __future__ import annotations

import pathlib

import jinja2

_TEMPLATES_DIR = pathlib.Path(__file__).parent / "templates"

env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(_TEMPLATES_DIR),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
    undefined=jinja2.StrictUndefined,
)
