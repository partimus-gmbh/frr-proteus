"""Dataclass bindings generated from FRR's YANG models.

The ``frr_bgp/`` package in this directory is a build artifact, not
checked into git (~1.3MB of generated code, trivially reproducible).
Produce it with:

    python3 -m venv .venv
    .venv/bin/pip install -e ".[dev,codegen]" -e ./pyangbind
    .venv/bin/python scripts/generate_bindings.py

It is a multi-file package: shared code lives once in ``_runtime.py`` /
``_types.py``, each data-defining YANG module gets its own file, and the
package ``__init__`` re-exports everything -- so import
``frr_proteus._generated.frr_bgp`` exactly as when it was a single file.
"""

import pathlib

if not (pathlib.Path(__file__).parent / "frr_bgp" / "__init__.py").exists():
    raise ImportError(
        "src/frr_proteus/_generated/frr_bgp/ is missing. Generate it with "
        "scripts/generate_bindings.py (see this package's docstring)."
    )
