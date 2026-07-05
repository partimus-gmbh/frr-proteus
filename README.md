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
  this one never does), so `yang/augments/frr-proteus-bgp-evpn.yang` is a
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
- **Custom YANG models (in progress):** FRR's own YANG is nearly
  unreadable -- the configuration tree is scattered across a dozen files
  of `augment` statements onto a generic control-plane-protocol list.
  `yang/custom/` is a self-contained rewrite (`proteus-bgp.yang`,
  `proteus-bgp-evpn.yang`, `proteus-route-map.yang`,
  `proteus-types.yang`) that states the whole tree top-down in one
  place, imports nothing from `frr/yang/`, and models address families
  as nested containers instead of an identityref-keyed `afi-safi` list.
  It covers the full config surface bgpd's own `bgp_config_write()`
  path can persist -- instance/process options, peer-groups, the whole
  neighbor session + per-AF surface, per-AF
  network/aggregate/redistribute/distance/dampening, the complete
  route-map match/set vocabulary (generic + BGP), and all of
  `address-family l2vpn evpn` -- with route-map references as real
  `leafref`s (checked by `validate_tree`). Deliberate exclusions
  (SRv6, the detailed L3VPN `vpn_policy` block, encap/flowspec/
  link-state families, RPKI caches, BMP, VNC) are listed in
  `proteus-bgp.yang`'s description. Codegen produces bindings for both
  schemas (`_generated/frr_bgp/` and `_generated/proteus/`); the
  renderers still consume the former, migration to the custom schema is
  the next step.

## How it works

1. **Codegen (pyangbind):** `scripts/generate_bindings.py` runs
   [pyang](https://github.com/mbj4668/pyang) with our
   [pyangbind fork](https://github.com/robinchrist/pyangbind) (the
   `pyangbind/` git submodule) as plugin against
   `frr/yang/frr-bgp.yang` (a git submodule pinned to FRR master) plus
   `yang/augments/frr-proteus-bgp-evpn.yang` (this project's own EVPN
   augmentation), producing plain, fully type-hinted dataclasses under
   `src/frr_proteus/_generated/` (the fork's `pybind-dataclass` output
   format: nested `@dataclass` classes mirroring the YANG tree,
   `typing.Literal` for enums/identityrefs, `T | None` leaves -- fully
   understood by mypy/pyright and IDEs, no runtime dependency beyond
   the stdlib). Validation is on by default: YANG value restrictions
   (ranges, patterns, enum/identityref sets, ...) are enforced at
   runtime on assignment (`YangValidationError`), and a module-level
   `validate_tree(*roots)` checks the structural/referential rules that
   can only be judged on a finished tree (leafref integrity, mandatory
   leaves, list keys/`unique`, min-/max-elements, choice exclusivity)
   -- `examples/evpn_bgp.py` calls it before rendering. Generated with
   `--no-dataclass-defaults` (YANG defaults deliberately not applied;
   unset leaf == `None`), plus `--dataclass-serde` (RFC 7951 JSON via
   `to_ietf_json`/`from_ietf_json`), `--dataclass-xpaths` (schema-path
   ClassVars and a `data_path()` instance-path helper), and
   `--dataclass-origin-comments` (a provenance comment above each
   grouping/augment-contributed field -- most of the FRR tree). This
   is a build artifact, not checked into git -- regenerate it before
   first use.
2. **Jinja2 renderer:** `src/frr_proteus/render/templates/*.j2` walk the
   generated dataclasses close to directly and emit bgpd config
   text; `render/bgp.py` sets up the Jinja environment, and
   `render/helpers.py` holds the handful of functions (exposed to
   templates as globals) that don't fit cleanly in template syntax --
   enum branching on `remote-as-type`, stripping YANG's module-prefixed
   identityref strings. This layer is *not* generated -- YANG only
   describes valid config shape, not FRR's CLI syntax. Its logic is
   derived directly from reading `frr/bgpd/bgp_vty.c` and
   `frr/bgpd/bgp_evpn_vty.c`'s `DEFUN`/`DEFPY` command definitions.

## Setup

Codegen uses the forked pyangbind vendored as the `pyangbind/` submodule
(installed editable, never the PyPI release). The fork carries our fixes
directly -- the bits-position bug that used to be monkeypatched in-memory,
and Python 3.12+ support -- so any modern interpreter works for codegen now.

A single venv covers both codegen and the library -- pyangbind and pyang
are codegen-only tools, but they're imported solely by
`scripts/generate_bindings.py` (never by `src/frr_proteus`), so they can't
leak into the runtime dependency set.

```sh
git submodule update --init

python3 -m venv .venv
# `.[codegen]` pulls pyang; the pyangbind fork is a local path submodule,
# so it's a separate editable install.
.venv/bin/pip install -e ".[dev,codegen]" -e ./pyangbind

# one-time codegen (regenerate whenever the YANG models change):
.venv/bin/python scripts/generate_bindings.py

# then use the library:
PYTHONPATH=src .venv/bin/python examples/basic_bgp.py   # writes out/r1_bgpd.conf, out/r2_bgpd.conf
PYTHONPATH=src .venv/bin/python examples/evpn_bgp.py    # writes out/evpn_frr.conf
.venv/bin/pytest tests/
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
  `yang/augments/frr-proteus-bgp-evpn.yang` (or a couple of leaves in
  `yang/custom/proteus-bgp-evpn.yang`), not yet done.
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
- `yang/augments/` -- project-authored YANG that extends FRR's own
  modules from outside (via `augment`) rather than editing the vendored
  submodule; EVPN so far.
- `yang/custom/` -- the self-contained replacement models
  (`proteus-*.yang`). No imports from `frr/yang/` at all, no `augment`
  statements; one module per address family pulled together with plain
  `import` + `uses` so the full tree reads top-down in
  `proteus-bgp.yang`.
- `pyangbind/` -- git submodule, our pyangbind fork; carries the
  `pybind-dataclass` codegen backend (and fixes). Codegen-time only.
- `src/frr_proteus/_generated/` -- generated dataclass bindings
  (gitignored).
- `src/frr_proteus/render/` -- Jinja2 templates (`templates/*.j2`) plus
  the Python glue that wires them to the bindings (`bgp.py`,
  `helpers.py`).
- `scripts/generate_bindings.py` -- codegen entry point.
- `examples/` -- runnable scripts building config data and rendering it.
- `tests/` -- renderer tests against the generated bindings.
