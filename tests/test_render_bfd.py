from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, TypeAlias

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from frr_proteus.render import render_bfd

if TYPE_CHECKING:
    from frr_proteus._generated import proteus as bindings
else:
    bindings = pytest.importorskip("frr_proteus._generated.proteus")

ProteusBfd: TypeAlias = bindings.ProteusBfd
Profile: TypeAlias = bindings.ProteusBfd.Profile


def test_empty_root_renders_nothing():
    assert render_bfd(ProteusBfd()) == ""


def test_profile_block_structure():
    root = ProteusBfd()
    root.profile.append(
        Profile(
            name="fast",
            detect_multiplier=3,
            receive_interval=50,
            transmit_interval=50,
        )
    )
    assert render_bfd(root) == (
        "!\n"
        "bfd\n"
        " profile fast\n"
        "  detect-multiplier 3\n"
        "  receive-interval 50\n"
        "  transmit-interval 50\n"
        " exit\n"
        "exit\n"
    )


def test_echo_receive_interval_zero_renders_disabled():
    # bfd_cli_show_required_echo_receive_interval() prints 'disabled'
    # for the 0 value (bfdd/bfdd_cli.c).
    root = ProteusBfd()
    root.profile.append(Profile(name="p", echo_receive_interval=0))
    assert "  echo receive-interval disabled\n" in render_bfd(root)


def test_flags_and_echo_intervals():
    root = ProteusBfd()
    root.profile.append(
        Profile(
            name="p",
            echo_mode=True,
            echo_transmit_interval=100,
            echo_receive_interval=100,
            minimum_ttl=250,
            shutdown=True,
            passive_mode=True,
            log_session_changes=True,
        )
    )
    text = render_bfd(root)
    assert "  echo-mode\n" in text
    assert "  echo transmit-interval 100\n" in text
    assert "  echo receive-interval 100\n" in text
    assert "  minimum-ttl 250\n" in text
    assert "  shutdown\n" in text
    assert "  passive-mode\n" in text
    assert "  log-session-changes\n" in text


def test_unset_leaves_render_nothing():
    root = ProteusBfd()
    root.profile.append(Profile(name="bare"))
    assert render_bfd(root) == "!\nbfd\n profile bare\n exit\nexit\n"
