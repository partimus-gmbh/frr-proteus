# frr-proteus

A Python library that takes structured config data -- shaped by FRR's own
YANG models, extended with project-authored YANG where FRR's own is
missing -- and renders it to FRR daemon text configuration. This is the
"YANG to text config" route: FRR's BGP daemon has no northbound backend
yet (no `bgpd/bgp_nb.c`, no `cli_show` callbacks), so there's no config
parser to go through and no way to load structured config directly. Text
config generation is the only path in.

Output aims to be functionally correct and loadable, not byte-identical
to what `show running-config` would print -- FRR's `!` lines are just
comments and are freely omitted.

## Status

- **Step 1 (done):** basic BGP config generation -- `router bgp <asn>`,
  `router-id`, neighbors with `remote-as`, `network` statements under
  `address-family ipv4/ipv6 unicast`. See `examples/basic_bgp.py`.
- **Step 2 (in progress):** EVPN config generation. FRR's own
  `frr-bgp.yang` ships an empty, contentless `l2vpn-evpn` placeholder
  container (every *other* AFI-SAFI gets real content augmented onto it;
  this one never does), so `yang/frr-proteus-bgp-evpn.yang` is a
  project-authored augmentation filling that gap: `advertise-all-vni`,
  per-VNI `rd`/`route-target`/`flooding`, `advertise-svi-ip`,
  `advertise-default-gw`, `enable-resolve-overlay-index` for the default
  BGP instance, and `rd`/`route-target`/`advertise ipv4|ipv6 unicast` for
  per-VRF L3VPN/EVPN instances. Per-neighbor EVPN knobs (`activate`,
  `route-reflector-client`, `route-map` in/out, `allowas-in`) needed no
  new YANG -- FRR's own model already augments the neighbor side of
  `l2vpn-evpn`, just not the instance side. See `examples/evpn_bgp.py`.
  Verified against most of `frr/tests/topotests/bgp_evpn_*`,
  `evpn_pim_*`, and `bgp_evpn_mh`; known gaps below.

## How it works

1. **Codegen (pyangbind):** `scripts/generate_bindings.py` runs
   [pyang](https://github.com/mbj4668/pyang) with the
   [pyangbind](https://github.com/robshakir/pyangbind) plugin against
   `frr/yang/frr-bgp.yang` (a git submodule pinned to FRR master) plus
   `yang/frr-proteus-bgp-evpn.yang` (this project's own EVPN
   augmentation), producing typed, validated Python classes under
   `src/frr_proteus/_generated/`. This is a build artifact, not checked
   into git -- regenerate it before first use.
2. **Jinja2 renderer:** `src/frr_proteus/render/templates/*.j2` walk the
   generated pyangbind objects close to directly and emit bgpd config
   text; `render/bgp.py` sets up the Jinja environment, and
   `render/helpers.py` holds the handful of functions (exposed to
   templates as globals) that don't fit cleanly in template syntax --
   enum branching on `remote-as-type`, stripping YANG's module-prefixed
   identityref strings. This layer is *not* generated -- YANG only
   describes valid config shape, not FRR's CLI syntax. Its logic is
   derived directly from reading `frr/bgpd/bgp_vty.c` and
   `frr/bgpd/bgp_evpn_vty.c`'s `DEFUN`/`DEFPY` command definitions.

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
PYTHONPATH=src python3 examples/evpn_bgp.py    # writes out/evpn_frr.conf
pytest tests/
```

## Known limitations

Verified by reading FRR's C source and comparing against topotest fixture
configs, not by loading generated config into a running bgpd -- worth
doing before trusting this beyond evaluation:

- No `bgp ebgp-requires-policy` handling yet. It defaults **on** in FRR, so
  an eBGP session from generated config will establish but FRR will filter
  all routes without an explicit policy. FRR's own topotests disable this
  knob for exactly that reason.
- `ipv6-unicast` is in the renderer's AFI-SAFI map, but nothing
  auto-activates a v6 neighbor for it (`neighbor X activate`) -- untested,
  likely incomplete for anything beyond a v4 `network` statement.
- EVPN: per-neighbor `maximum-prefix` and `addpath-tx-all-paths` are not
  modeled -- FRR's own YANG doesn't augment the neighbor's `l2vpn-evpn`
  container with prefix-limit/add-paths groupings (unlike
  `as-path-options`/`route-reflector`/`filter-config`, which it does), so
  this needs a small additional augment in
  `yang/frr-proteus-bgp-evpn.yang`, not yet done.
- EVPN: per-VNI `advertise-default-gw`/`advertise-svi-ip` overrides and
  `autort rfc8365-compatible` are not modeled (not exercised by the
  topotests read so far).
- Zebra-side Ethernet Segment (EVPN multihoming) config -- `evpn mh es-id`
  etc. -- is out of scope entirely; it's zebra's surface, not bgpd's, and
  this project is scoped to BGP.

## Repo layout

- `frr/` -- git submodule, FRR master. Source of truth for both FRR's own
  YANG models (`frr/yang/`) and the CLI behavior the renderer replicates
  (`frr/bgpd/bgp_vty.c`, `frr/bgpd/bgp_evpn_vty.c`). We do not parse or
  generate FRR C code.
- `yang/` -- project-authored YANG, for config surface FRR's own YANG
  doesn't cover (EVPN so far). Augments FRR's modules from outside rather
  than editing the vendored submodule.
- `src/frr_proteus/_generated/` -- pyangbind output (gitignored).
- `src/frr_proteus/render/` -- Jinja2 templates (`templates/*.j2`) plus
  the Python glue that wires them to pyangbind (`bgp.py`, `helpers.py`).
- `scripts/generate_bindings.py` -- codegen entry point.
- `examples/` -- runnable scripts building config data and rendering it.
- `tests/` -- renderer tests against the generated bindings.
