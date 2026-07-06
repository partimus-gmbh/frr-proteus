#!/usr/bin/env bash
#
# Build a self-contained, installable wheel of frr-proteus.
#
# The generated pyangbind bindings (src/frr_proteus/_generated/{proteus,frr_bgp})
# are gitignored but ARE real Python sub-packages. setuptools' package discovery
# picks them up at build time, so a wheel bundles them alongside the templates and
# py.typed. gitignore only affects the sdist/SCM file list, never wheel package
# discovery -- that is why we build a WHEEL here, not an sdist: a clean sdist would
# ship without the (gitignored) bindings, a wheel ships with them.
#
# Result: dist/frr_proteus-<version>-py3-none-any.whl -- installable in any other
# project, non-editable, with jinja2 as its only runtime dependency. pyangbind /
# pyang are codegen-time only and are NOT pulled in by the wheel.
#
# Usage:  scripts/build_package.sh
# Env:    PYTHON=/path/to/python   (default: .venv/bin/python, else python3)
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$(pwd)

# Pick an interpreter: prefer the project venv, fall back to python3.
if [[ -n "${PYTHON:-}" ]]; then
    PY=$PYTHON
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
    PY="$ROOT/.venv/bin/python"
else
    PY=python3
fi
echo ">> using interpreter: $PY"

# 1. Ensure the generated bindings exist (they are gitignored / not in a fresh
#    checkout). Regenerate unconditionally so the wheel always matches the current
#    YANG. Needs the codegen extras + the pyangbind fork installed editable:
#        $PY -m pip install -e ".[codegen]" -e ./pyangbind
echo ">> generating bindings"
"$PY" scripts/generate_bindings.py

# 2. Sanity-check that both sub-packages landed on disk before building.
for pkg in proteus frr_bgp; do
    if [[ ! -f "src/frr_proteus/_generated/$pkg/__init__.py" ]]; then
        echo "!! src/frr_proteus/_generated/$pkg is missing after codegen -- aborting" >&2
        exit 1
    fi
done

# 3. Build the wheel. Clean old artifacts first so stale bindings can't linger.
echo ">> building wheel"
rm -rf dist build ./*.egg-info src/*.egg-info
"$PY" -m pip wheel . --no-deps -w dist/

WHEEL=$(ls -t dist/*.whl | head -1)
echo
echo ">> built: $WHEEL"
echo ">> contents (bindings + templates):"
"$PY" -m zipfile -l "$WHEEL" | grep -E '_generated/.*/__init__|templates/|py\.typed' | sed 's/^/     /'
echo
echo ">> install it in another project with:"
echo "     pip install $ROOT/$WHEEL"
