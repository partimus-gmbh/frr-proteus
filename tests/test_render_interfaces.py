from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, TypeAlias

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from frr_proteus.render import render_interfaces

if TYPE_CHECKING:
    from frr_proteus._generated import proteus as bindings
else:
    bindings = pytest.importorskip("frr_proteus._generated.proteus")

ProteusInterface: TypeAlias = bindings.ProteusInterface
Interface: TypeAlias = bindings.ProteusInterface.Interfaces.Interface


def test_empty_root_renders_nothing():
    assert render_interfaces(ProteusInterface()) == ""


def test_interface_blocks():
    root = ProteusInterface()
    root.interfaces.interface.append(
        Interface(name="swp1", description="to spine1")
    )
    root.interfaces.interface.append(Interface(name="swp2"))
    assert render_interfaces(root) == (
        "interface swp1\n"
        " description to spine1\n"
        "exit\n"
        "interface swp2\n"
        "exit\n"
    )
