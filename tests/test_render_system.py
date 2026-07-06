from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, TypeAlias

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from frr_proteus.render import render_system

if TYPE_CHECKING:
    from frr_proteus._generated import proteus as bindings
else:
    bindings = pytest.importorskip("frr_proteus._generated.proteus")

ProteusSystem: TypeAlias = bindings.ProteusSystem


def test_empty_root_renders_nothing():
    assert render_system(ProteusSystem()) == ""


def test_all_lines_in_frr_write_order():
    root = ProteusSystem()
    root.frr_defaults = "datacenter"
    root.hostname = "vtep-host-01"
    root.log.syslog = "informational"
    root.service.integrated_vtysh_config = True
    assert render_system(root) == (
        "frr defaults datacenter\n"
        "hostname vtep-host-01\n"
        "log syslog informational\n"
        "service integrated-vtysh-config\n"
    )


def test_integrated_vtysh_config_negative_form():
    root = ProteusSystem()
    root.service.integrated_vtysh_config = False
    assert render_system(root) == "no service integrated-vtysh-config\n"


def test_single_line():
    root = ProteusSystem()
    root.hostname = "r1"
    assert render_system(root) == "hostname r1\n"
