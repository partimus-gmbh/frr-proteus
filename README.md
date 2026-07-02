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
2. **Hand-written renderer:** `src/frr_proteus/render/templates/bgp.conf.j2`
   is a Jinja2 template that walks the generated pyangbind objects
   directly and emits bgpd config text; `render/bgp.py` just sets up the
   Jinja environment, and `render/helpers.py` holds the handful of
   functions (exposed to the template as globals) that don't fit cleanly
   in template syntax -- enum branching on `remote-as-type`, stripping
   YANG's module-prefixed identityref strings. This layer is *not*
   generated -- YANG only describes valid config shape, not FRR's CLI
   syntax. Its logic is derived directly from the `vty_out()` calls in
   `frr/bgpd/bgp_vty.c` (`bgp_config_write`, `bgp_config_write_family`,
   the neighbor `remote-as` printing block) and `frr/lib/vty.c`'s
   `vty_frame`/`vty_endframe` (which explains the easy-to-miss ` !`
   separator line before a non-empty `address-family` block).

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
PYTHONPATH=src python3 examples/basic_bgp.py   # writes out/r1_bgpd.conf, out/r2_bgpd.conf
pytest tests/
```

## Known limitations (step 1)

Verified by reading FRR's C source, not by loading generated config into a
running bgpd -- worth doing before trusting this beyond evaluation:

- No `bgp ebgp-requires-policy` handling yet. It defaults **on** in FRR, so
  an eBGP session from generated config will establish but FRR will filter
  all routes without an explicit policy. FRR's own topotests disable this
  knob for exactly that reason (see `frr/tests/topotests/*/bgpd.conf`).
- `ipv6-unicast` is in the renderer's AFI-SAFI map, but nothing
  auto-activates a v6 neighbor for it (`neighbor X activate`) -- untested,
  likely incomplete for anything beyond a v4 `network` statement.

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
