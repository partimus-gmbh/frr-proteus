"""Pyangbind classes generated from FRR's YANG models.

``frr_bgp.py`` in this directory is a build artifact, not checked into git
(it's ~8MB of generated code). Produce it with:

    python3.11 -m venv .venv-codegen
    .venv-codegen/bin/pip install pyang pyangbind
    .venv-codegen/bin/python scripts/generate_bindings.py

See scripts/generate_bindings.py for why Python 3.11 is required for this
one-time generation step (the generated output itself runs on any modern
Python, including the one frr-proteus otherwise targets).
"""

import pathlib

if not (pathlib.Path(__file__).parent / "frr_bgp.py").exists():
    raise ImportError(
        "src/frr_proteus/_generated/frr_bgp.py is missing. Generate it with "
        "scripts/generate_bindings.py (see this package's docstring)."
    )
