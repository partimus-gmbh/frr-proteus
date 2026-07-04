#!/usr/bin/env python3
"""Generate pyangbind Python classes from FRR's YANG models.

Uses the forked pyangbind vendored as the ``pyangbind/`` git submodule
(install it into your venv with ``pip install -e ./pyangbind``). The fork
carries our fixes directly (e.g. the bits-position TypeError that used to
be monkeypatched here), so any Python >= 3.9 interpreter works -- the old
"must be 3.11" restriction applied only to the unpatched PyPI release.

A single venv covers codegen and the library -- pyang and the pyangbind
fork are imported only here, never by ``src/frr_proteus``.

Usage:
    python3 -m venv .venv
    .venv/bin/pip install -e ".[dev,codegen]" -e ./pyangbind
    .venv/bin/python scripts/generate_bindings.py
"""

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
FRR_YANG_DIR = REPO_ROOT / "frr" / "yang"
PROTEUS_YANG_DIR = REPO_ROOT / "yang"
OUTPUT_DIR = REPO_ROOT / "src" / "frr_proteus" / "_generated"
OUTPUT_FILE = OUTPUT_DIR / "frr_bgp.py"

# YANG modules needed to fully resolve the BGP model (frr-bgp.yang includes
# several submodules and imports these directly).
BGP_YANG_MODULES = [
    FRR_YANG_DIR / "frr-bgp.yang",
    FRR_YANG_DIR / "frr-routing.yang",
    FRR_YANG_DIR / "frr-interface.yang",
    FRR_YANG_DIR / "frr-route-types.yang",
    FRR_YANG_DIR / "frr-bgp-types.yang",
    # frr-proteus's own augmentation of frr-bgp.yang's empty l2vpn-evpn
    # placeholder container -- see yang/frr-proteus-bgp-evpn.yang for why
    # this can't just be added to the vendored FRR YANG.
    PROTEUS_YANG_DIR / "frr-proteus-bgp-evpn.yang",
]


def _plugin_dir() -> pathlib.Path:
    """Locate pyangbind's pyang plugin directory.

    Resolved via the plugin module's own __file__ rather than
    ``pyangbind.__path__``: with the fork installed editable, a process
    whose CWD is the repo root sees the submodule checkout directory
    ``pyangbind/`` (which contains the package one level down, not the
    package itself) as a same-named namespace package shadowing the
    editable install, and __path__ then points at the wrong level.
    """
    try:
        import pyangbind.plugin.pybind
    except ImportError:
        sys.exit(
            "pyangbind is not installed in this interpreter.\n"
            "Run: pip install pyang -e ./pyangbind"
        )
    return pathlib.Path(pyangbind.plugin.pybind.__file__).resolve().parent


def main() -> None:
    plugin_dir = _plugin_dir()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    import pyang.scripts.pyang_tool

    argv = [
        "pyang",
        "--plugindir",
        str(plugin_dir),
        "-f",
        "pybind-dataclass",
        # The backend generates validation and YANG defaults by default;
        # keep validation but opt out of defaults: renderers rely on
        # "unset leaf is None / falsy means not explicitly configured",
        # and applying YANG defaults would make default-valued knobs
        # indistinguishable from configured ones.
        "--no-dataclass-defaults",
        "-p",
        str(FRR_YANG_DIR),
        "-p",
        str(FRR_YANG_DIR / "ietf"),
        "-p",
        str(PROTEUS_YANG_DIR),
        "-o",
        str(OUTPUT_FILE),
        *[str(m) for m in BGP_YANG_MODULES],
    ]
    print("running (in-process):", " ".join(argv))
    old_argv = sys.argv
    sys.argv = argv
    try:
        pyang.scripts.pyang_tool.run()
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise
    finally:
        sys.argv = old_argv
    print(f"wrote {OUTPUT_FILE} ({OUTPUT_FILE.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
