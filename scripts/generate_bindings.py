#!/usr/bin/env python3
"""Generate pyangbind Python classes for frr-proteus's YANG models.

Two model sets, two generated packages:

* ``frr_bgp`` -- FRR's own frr-bgp.yang plus our augment of its empty
  l2vpn-evpn placeholder (yang/augments/). The original input schema;
  the current renderers still consume this.
* ``proteus`` -- the self-contained rewrite under yang/custom/
  (proteus-bgp.yang + proteus-bgp-evpn.yang). Imports nothing from
  frr/yang/; this is the schema new work targets.

Uses the forked pyangbind vendored as the ``pyangbind/`` git submodule
(install it into your venv with ``pip install -e ./pyangbind``). The fork
carries our fixes directly (e.g. the bits-position TypeError that used to
be monkeypatched here), so any modern interpreter works (the project
requires Python >= 3.12) -- the old "must be 3.11" restriction applied
only to the unpatched PyPI release.

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
AUGMENTS_YANG_DIR = REPO_ROOT / "yang" / "augments"
CUSTOM_YANG_DIR = REPO_ROOT / "yang" / "custom"
OUTPUT_DIR = REPO_ROOT / "src" / "frr_proteus" / "_generated"

# Options shared by both runs. The backend generates validation and YANG
# defaults by default; keep validation (which includes the validate_tree()
# whole-tree pass) but opt out of defaults: renderers rely on "unset leaf
# is None / falsy means not explicitly configured", and applying YANG
# defaults would make default-valued knobs indistinguishable from
# configured ones.
COMMON_FLAGS = [
    "--no-dataclass-defaults",
    # Annotate each generated node with where it comes from (grouping/
    # augment provenance) -- essential for the augment-heavy FRR model,
    # cheap for the custom one.
    "--dataclass-origin-comments",
    # RFC 7951 JSON (to_ietf_json/from_ietf_json) and schema/instance
    # paths (_yang_schema_path, data_path) -- cheap to carry, useful
    # for debugging and tests.
    "--dataclass-serde",
    "--dataclass-xpaths",
]

# YANG modules needed to fully resolve the FRR BGP model (frr-bgp.yang
# includes several submodules and imports these directly).
FRR_BGP_MODULES = [
    FRR_YANG_DIR / "frr-bgp.yang",
    FRR_YANG_DIR / "frr-routing.yang",
    FRR_YANG_DIR / "frr-interface.yang",
    FRR_YANG_DIR / "frr-route-types.yang",
    FRR_YANG_DIR / "frr-bgp-types.yang",
    # frr-proteus's own augmentation of frr-bgp.yang's empty l2vpn-evpn
    # placeholder container -- see the module's description for why this
    # can't just be added to the vendored FRR YANG.
    AUGMENTS_YANG_DIR / "frr-proteus-bgp-evpn.yang",
]

# The self-contained custom model: no FRR imports, so the only search
# path it needs is its own directory.
CUSTOM_MODULES = [
    CUSTOM_YANG_DIR / "proteus-bgp.yang",
    CUSTOM_YANG_DIR / "proteus-bgp-evpn.yang",
    CUSTOM_YANG_DIR / "proteus-route-map.yang",
    # The experimental EVPN scheme's ADDITIONAL nodes -- always
    # compiled in; opting in/out of the scheme happens at the
    # renderer (output format), not the schema.
    CUSTOM_YANG_DIR / "proteus-bgp-evpn-experimental.yang",
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


# Each pyang invocation must run in a fresh process: pyang registers its
# plugins' optparse options globally, so a second in-process run raises
# OptionConflictError. main() therefore re-execs this script once per
# model set.
MODEL_SETS = {
    "frr": lambda: (
        [FRR_YANG_DIR, FRR_YANG_DIR / "ietf", AUGMENTS_YANG_DIR],
        FRR_BGP_MODULES,
        OUTPUT_DIR / "frr_bgp",
    ),
    "custom": lambda: (
        [CUSTOM_YANG_DIR],
        CUSTOM_MODULES,
        OUTPUT_DIR / "proteus",
    ),
}


def _run_pyang(
    plugin_dir: pathlib.Path,
    search_paths: list[pathlib.Path],
    modules: list[pathlib.Path],
    output_package: pathlib.Path,
) -> None:
    import pyang.scripts.pyang_tool

    argv = [
        "pyang",
        "--plugindir",
        str(plugin_dir),
        "-f",
        "pybind-dataclass",
        *COMMON_FLAGS,
        *[arg for p in search_paths for arg in ("-p", str(p))],
        # A multi-file package: _runtime.py/_types.py hold the shared
        # code once, one file per data-defining YANG module, and
        # __init__.py re-exports everything.
        "--dataclass-split-dir",
        str(output_package),
        *[str(m) for m in modules],
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
    files = sorted(output_package.glob("*.py"))
    total = sum(f.stat().st_size for f in files)
    print(f"wrote {len(files)} files ({total} bytes) under {output_package}")


def main() -> None:
    if len(sys.argv) == 2 and sys.argv[1] in MODEL_SETS:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        _run_pyang(_plugin_dir(), *MODEL_SETS[sys.argv[1]]())
        return

    import subprocess

    for name in MODEL_SETS:
        subprocess.run(
            [sys.executable, __file__, name],
            check=True,
        )


if __name__ == "__main__":
    main()
