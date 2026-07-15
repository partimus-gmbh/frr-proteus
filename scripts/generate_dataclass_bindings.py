#!/usr/bin/env python3
"""Generic pybind-dataclass codegen driver.

Compiles an arbitrary set of YANG modules (files and/or directories,
directories searched recursively; submodules are skipped as inputs but
remain resolvable) into one Python bindings module using the
``pybind-dataclass`` backend from our pyangbind fork (install it with
``pip install -e ./pyangbind`` alongside ``pyang``).

All backend features are ON by default (validation, YANG defaults,
serde, xpaths, origin comments); use the ``--no-*`` flags to opt out.
``scripts/generate_bindings.py`` stays as the FRR-specific entry point
(it opts out of defaults deliberately); this script is for pointing the
backend at any other model tree, e.g.:

    .venv/bin/python scripts/generate_dataclass_bindings.py \\
        -o out/srlinux.py \\
        -p /path/to/models/ietf -p /path/to/models/openconfig \\
        /path/to/models/srl_nokia
"""

import argparse
import pathlib
import sys


def _plugin_dir() -> pathlib.Path:
    """Locate pyangbind's pyang plugin directory.

    Resolved via the plugin module's own __file__ rather than
    ``pyangbind.__path__``: with the fork installed editable, a process
    whose CWD sees the submodule checkout directory ``pyangbind/`` as a
    same-named namespace package shadowing the editable install, and
    __path__ then points at the wrong level.
    """
    try:
        # the editable pyangbind install resolves at runtime; the
        # namespace-package layout hides it from static checkers
        import pyangbind.plugin.pybind  # type: ignore[import-not-found] # pyright: ignore[reportMissingImports]
    except ImportError:
        sys.exit(
            "pyangbind is not installed in this interpreter.\n"
            "Run: pip install pyang -e ./pyangbind"
        )
    return pathlib.Path(pyangbind.plugin.pybind.__file__).resolve().parent


def _is_submodule(path: pathlib.Path) -> bool:
    """True if the YANG file's top-level statement is ``submodule``."""
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            stripped = line.lstrip()
            if not stripped or stripped.startswith("//"):
                continue
            return stripped.startswith("submodule")
    return False


def _collect(inputs: list[pathlib.Path]) -> tuple[list[pathlib.Path], set[pathlib.Path]]:
    """Expand file/dir inputs into (module files, dirs containing any .yang)."""
    modules: list[pathlib.Path] = []
    search_dirs: set[pathlib.Path] = set()
    for item in inputs:
        if item.is_dir():
            for yang in sorted(item.rglob("*.yang")):
                search_dirs.add(yang.parent)
                if not _is_submodule(yang):
                    modules.append(yang)
        elif item.is_file():
            search_dirs.add(item.parent)
            modules.append(item)
        else:
            sys.exit(f"input not found: {item}")
    return modules, search_dirs


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        type=pathlib.Path,
        help="YANG module files and/or directories (searched recursively; "
        "submodules found in directories are skipped as compile inputs)",
    )
    output_group = parser.add_mutually_exclusive_group(required=True)
    output_group.add_argument(
        "-o", "--output", type=pathlib.Path,
        help="output .py file (parent directories are created)",
    )
    output_group.add_argument(
        "-d", "--output-dir", type=pathlib.Path,
        help="write a multi-file package under this directory instead of "
        "one .py file (one module per YANG module; shared runtime and "
        "reusable types emitted once, in _runtime.py/_types.py)",
    )
    parser.add_argument(
        "-p", "--path", action="append", type=pathlib.Path, default=[],
        metavar="DIR",
        help="extra module search directory for imports/includes "
        "(searched recursively; repeatable). Input directories are "
        "added automatically.",
    )
    parser.add_argument(
        "--no-validation", action="store_true",
        help="pass --no-dataclass-validation to the backend",
    )
    parser.add_argument(
        "--no-defaults", action="store_true",
        help="pass --no-dataclass-defaults to the backend",
    )
    parser.add_argument(
        "--no-serde", action="store_true",
        help="omit --dataclass-serde",
    )
    parser.add_argument(
        "--no-xpaths", action="store_true",
        help="omit --dataclass-xpaths",
    )
    parser.add_argument(
        "--no-origin-comments", action="store_true",
        help="omit --dataclass-origin-comments",
    )
    args = parser.parse_args()

    modules, search_dirs = _collect(args.inputs)
    if not modules:
        sys.exit("no YANG modules found in the given inputs")
    for extra in args.path:
        if not extra.is_dir():
            sys.exit(f"search path is not a directory: {extra}")
        search_dirs.add(extra)
        for yang in extra.rglob("*.yang"):
            search_dirs.add(yang.parent)

    plugin_dir = _plugin_dir()
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)

    import pyang.scripts.pyang_tool  # type: ignore[import-untyped]

    argv = [
        "pyang",
        "--plugindir", str(plugin_dir),
        "-f", "pybind-dataclass",
    ]
    if args.no_validation:
        argv.append("--no-dataclass-validation")
    if args.no_defaults:
        argv.append("--no-dataclass-defaults")
    if not args.no_serde:
        argv.append("--dataclass-serde")
    if not args.no_xpaths:
        argv.append("--dataclass-xpaths")
    if not args.no_origin_comments:
        argv.append("--dataclass-origin-comments")
    for d in sorted(search_dirs):
        argv += ["-p", str(d)]
    if args.output_dir is not None:
        argv += ["--dataclass-split-dir", str(args.output_dir)]
    else:
        argv += ["-o", str(args.output)]
    argv += [str(m) for m in modules]

    destination = args.output_dir or args.output
    print(f"compiling {len(modules)} modules "
          f"({len(search_dirs)} search dirs) -> {destination}")
    old_argv = sys.argv
    sys.argv = argv
    try:
        pyang.scripts.pyang_tool.run()
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise
    finally:
        sys.argv = old_argv
    if args.output_dir is not None:
        files = sorted(args.output_dir.glob("*.py"))
        total = sum(f.stat().st_size for f in files)
        print(f"wrote {len(files)} files ({total} bytes) under {args.output_dir}")
    else:
        assert args.output is not None
        print(f"wrote {args.output} ({args.output.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
