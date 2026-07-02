# frr-proteus

A Python library that takes structured config data -- shaped by FRR's own
YANG models -- and renders it to FRR daemon text configuration
(`bgpd.conf`-style). This is the "YANG to text config" route: FRR's BGP
daemon has no northbound backend yet (no `bgpd/bgp_nb.c`, no `cli_show`
callbacks), so there's no config parser to go through and no way to load
structured config directly. Text config generation is the only path in.

## Status

Step 1 prototype: basic BGP config generation works --
`router bgp <asn>`, `router-id`, one neighbor with `remote-as`, and
`network` statements under `address-family <afi> unicast`. See
`examples/basic_bgp.py`.

EVPN is not yet modeled -- FRR's `frr-bgp.yang` has no EVPN coverage at
all (checked: no `evpn` hits anywhere under `frr/yang/`). Step 2 is to
write an EVPN YANG model by reading `bgpd`'s EVPN C code, then extend the
renderer.

## How it works

1. **Codegen (pyangbind):** `scripts/generate_bindings.py` runs
   [pyang](https://github.com/mbj4668/pyang) with the
   [pyangbind](https://github.com/robshakir/pyangbind) plugin against
   `frr/yang/frr-bgp.yang` (a git submodule pinned to FRR master), producing
   typed, validated Python classes under `src/frr_proteus/_generated/`.
   This is a build artifact, not checked into git -- regenerate it before
   first use.
2. **Hand-written renderer:** `src/frr_proteus/render/bgp.py` walks those
   generated objects and emits bgpd config text. This part is *not*
   generated -- YANG only describes valid config shape, not FRR's CLI
   syntax. The renderer's logic is derived directly from the `vty_out()`
   calls in `frr/bgpd/bgp_vty.c` (`bgp_config_write`,
   `bgp_config_write_family`, the neighbor `remote-as` printing block).

## Setup

Generating the pyangbind bindings needs a Python 3.11 interpreter
specifically -- pyangbind's `pyang` plugin doesn't run on 3.12+, and hits a
real upstream bug on 3.14 that `scripts/generate_bindings.py` monkeypatches
in-memory (see that file's docstring for why, and why it's not a simple
version issue). The bindings it produces run fine on any modern Python.

```sh
git submodule update --init

python3.11 -m venv .venv-codegen
.venv-codegen/bin/pip install pyang pyangbind
.venv-codegen/bin/python scripts/generate_bindings.py

# now use any Python >=3.9 for the actual library:
pip install -e ".[dev]"
PYTHONPATH=src python3 examples/basic_bgp.py
pytest tests/
```

## Repo layout

- `frr/` -- git submodule, FRR master. Source of truth for both the YANG
  models (`frr/yang/`) and the CLI behavior the renderer replicates
  (`frr/bgpd/bgp_vty.c`). We do not parse or generate FRR C code.
- `src/frr_proteus/_generated/` -- pyangbind output (gitignored).
- `src/frr_proteus/render/` -- hand-written YANG-object -> CLI-text
  renderers, one module per daemon/protocol.
- `scripts/generate_bindings.py` -- codegen entry point.
- `examples/` -- runnable scripts building config data and rendering it.
- `tests/` -- renderer tests against the generated bindings.
