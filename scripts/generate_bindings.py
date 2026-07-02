#!/usr/bin/env python3
"""Generate pyangbind Python classes from FRR's YANG models.

Run this with a Python 3.11 interpreter (pyangbind's pyang plugin does not
work on 3.12+ due to an unrelated CPython change, and hits a real pyangbind
bug on 3.14 -- see _patch_pyangbind_bits_bug below). The *generated* output
is plain Python and runs fine on any interpreter frr-proteus itself supports.

Usage:
    python3.11 -m venv .venv-codegen
    .venv-codegen/bin/pip install pyang pyangbind
    .venv-codegen/bin/python scripts/generate_bindings.py
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


def _patch_pyangbind_bits_bug(plugin_dir: pathlib.Path) -> None:
    """Monkeypatch a pyangbind bug in its YANG 'bits' typedef handling.

    pyangbind 0.8.7's build_elemtype() computes the position of a bit
    without an explicit `position` statement as
    ``1 + max(allowed_bits.values())``. But explicit positions are stored
    as *strings* (`position.arg`), so this raises
    ``TypeError: unsupported operand type(s) for +: 'int' and 'str'``
    whenever a bits typedef mixes explicit and implicit positions -- which
    ietf-bgp-types.yang's `community-type` typedef does. This is a real
    upstream defect (reproduces on CPython 3.11 and 3.14 alike), not a
    Python-version issue.

    This patches the function in memory for this process only -- it does
    not touch the installed pyangbind package on disk, so re-running this
    script (or using the same venv for anything else) always starts from
    pyangbind's unmodified, pip-installed source.

    Subtlety: pyang's plugin loader (pyang.plugin.init) does not import
    pyangbind's plugin as the package module `pyangbind.plugin.pybind`. It
    prepends the plugin directory to sys.path and does a bare
    ``__import__("pybind")``, which creates a *second*, distinct module
    object under ``sys.modules["pybind"]``. Patching only the
    `pyangbind.plugin.pybind` package module (as a first attempt at this
    did) is silently ineffective -- pyang never calls into that object. So
    we import it the same way pyang does, and patch that module.
    """
    import inspect
    import sys

    if str(plugin_dir) not in sys.path:
        sys.path.insert(0, str(plugin_dir))
    import pybind as pybind_plugin  # the top-level module name pyang itself uses

    orig = pybind_plugin.build_elemtype
    src = inspect.getsource(orig)
    broken = "pos = position.arg\n"
    fixed = "pos = int(position.arg)\n"
    if fixed in src:
        print("pyangbind build_elemtype already fixed upstream, no patch needed")
        return
    if broken not in src:
        raise RuntimeError(
            "expected pyangbind bug pattern not found in build_elemtype(); "
            "pyangbind version may have changed, re-check the fix"
        )
    patched_src = src.replace(broken, fixed)

    namespace: dict = {}
    exec(  # noqa: S102 -- rebuilding a single stdlib-adjacent function from its own source
        compile(patched_src, f"<patched {orig.__module__}.build_elemtype>", "exec"),
        pybind_plugin.__dict__,
        namespace,
    )
    pybind_plugin.build_elemtype = namespace["build_elemtype"]
    print("monkeypatched pybind.build_elemtype in-memory (bits-position bug)")


def main() -> None:
    try:
        import pyangbind
    except ImportError:
        sys.exit(
            "pyangbind is not installed in this interpreter.\n"
            "Run: pip install pyang pyangbind"
        )

    plugin_dir = pathlib.Path(pyangbind.__path__[0]) / "plugin"

    # The bits-typedef bug is patched in-memory in *this* process (see
    # docstring above), so pyang must run in-process too -- shelling out to
    # a `pyang` subprocess would start from an unpatched, unmodified
    # pyangbind and hit the crash again.
    _patch_pyangbind_bits_bug(plugin_dir)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    import pyang.scripts.pyang_tool

    argv = [
        "pyang",
        "--plugindir",
        str(plugin_dir),
        "-f",
        "pybind",
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
