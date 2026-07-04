# frr-proteus

YANG-to-text-config generator for FRR. Structured Python config data (built
via pyangbind classes generated from FRR's own YANG models, extended with
project-authored YANG where FRR's own is incomplete) in, FRR daemon
config text out. See README.md for the full pitch and setup steps.

## Why this project exists

FRR's `bgpd` has no northbound backend: no `bgpd/bgp_nb.c`, no `cli_show`
callbacks (verified: `grep -rn cli_show frr/bgpd/` is empty). Other FRR
daemons that *are* northbound-converted (staticd, ripd, ...) can load
structured/YANG config directly and their `cli_show` callbacks double as
the YANG->text mapping. bgpd has neither, so this project fills that gap:
codegen gets you a typed, validated Python object model matching the YANG
schema, but the actual rendering to CLI text is hand-written, sourced from
reading `bgp_vty.c`/`bgp_evpn_vty.c`'s `vty_out()`/`DEFUN`/`DEFPY` calls
directly.

**Output fidelity target: functionally correct and loadable, not
byte-identical to FRR's own `show running-config`.** `!` lines are just
comments in FRR config and can be freely omitted -- don't spend effort
replicating `vty_frame`/`vty_endframe` separator placement. Also: FRR's
per-daemon config files (bgpd.conf, zebra.conf, ...) are deprecated; the
integrated `frr.conf` (all daemons' config in one file) is the forward
path. Renderers should ultimately compose into that shape rather than
assuming one file per daemon -- `examples/evpn_bgp.py` already writes one
combined file for multiple `router bgp` blocks; keep doing that rather
than reverting to per-instance files.

**Do not assume the renderer can be derived from the YANG model alone.**
Every new field the renderer supports needs its exact CLI text confirmed
against `bgp_vty.c`/`bgp_evpn_vty.c` (or the relevant daemon's `_vty.c`),
not guessed from the YANG leaf name or from topotest `.conf` fixtures
(those are hand-written *input* files using accepted shorthand, e.g.
`address-family ipv4` instead of the canonical `show running-config`
output `address-family ipv4 unicast` -- both parse fine, but don't infer
CLI syntax purely from a fixture without checking the DEFUN/DEFPY too).

**Rendering is Jinja2-first, not Python string-building.** Templates
under `render/templates/*.j2` walk pyangbind objects close to directly;
`render/helpers.py` holds only the handful of functions a template
genuinely can't express (enum branching, identityref prefix stripping).
The user was explicit about this after rejecting an earlier all-Python
renderer as "completely unreadable" -- keep new protocol renderers to the
same shape (one `.j2` template, thin Python glue module, thin
`render_*_instance()` wrapper in a `.py` of the same name).

## Layout

- `frr/` -- git submodule pinned to FRR master. Source of truth for FRR's
  own YANG models (`frr/yang/*.yang`) and CLI rendering logic
  (`frr/bgpd/bgp_vty.c`, `frr/bgpd/bgp_evpn_vty.c`, `frr/lib/vty.c`).
  Never parse or generate FRR C code -- only read it as a reference for
  what text to emit.
- `yang/` -- project-authored YANG. Augments FRR's own modules *from
  outside* (via `augment` statements targeting FRR's schema paths, with
  explicit `frr-bgp:`-prefixed node names since the target nodes live in
  another module) rather than editing the vendored `frr/` submodule.
  `frr-proteus-bgp-evpn.yang` fills in FRR's `l2vpn-evpn` afi-safi
  container, which upstream ships as a genuinely empty placeholder (every
  *other* afi-safi -- ipv4-unicast, l3vpn-ipv4-unicast, ... -- gets real
  content augmented onto it in `frr-bgp.yang`; l2vpn-evpn never does).
  pyangbind silently omits a container from codegen entirely if it ends
  up with zero fields, which is why `l2vpn_evpn` doesn't show up as an
  attribute on the *global* afi-safi entry pre-augmentation, even though
  it does show up on the *neighbor's* afi-safi entry (FRR's own
  `frr-bgp.yang` already augments the neighbor side with
  `route-reflector-client`/`route-map`/`allowas-in`/etc, generically,
  same as every other afi-safi -- only the instance side was empty).
  Don't rediscover this by grepping the generated bindings again; it's
  documented here and in the yang file's own description.
- `pyangbind/` -- git submodule pinned to our pyangbind fork
  (github.com/robinchrist/pyangbind). Fixes go into the fork directly
  now (e.g. the bits-position TypeError that generate_bindings.py used
  to monkeypatch in-memory; 3.12+ support was already fixed on upstream
  master vs. the 0.8.7 PyPI release). Install it editable (`pip install
  -e ./pyangbind`), never from PyPI. Long-term goal: rewrite its pybind
  plugin to emit dataclass-style, fully type-hinted bindings.
- `scripts/generate_bindings.py` -- pyangbind codegen, runs on any
  Python >=3.9 with the fork installed (the old python3.11-only
  restriction applied to the unpatched PyPI release). Compiles
  `frr/yang/frr-bgp.yang` + `yang/frr-proteus-bgp-evpn.yang` together
  into one bindings module. Gotcha: it locates the pyang plugin dir via
  `pyangbind.plugin.pybind.__file__`, not `pyangbind.__path__` -- with
  the editable install, a process cwd'd at the repo root sees the
  submodule checkout dir (which holds the package one level down) as a
  same-named namespace package, and `__path__` then points at the wrong
  level.
- `src/frr_proteus/_generated/` -- pyangbind output. Gitignored (~8MB
  generated file, not diffable, trivially reproducible). Must be
  generated before running examples or tests.
- `src/frr_proteus/render/` -- templates under `templates/*.j2` (one per
  protocol/AF, e.g. `bgp.conf.j2`, `bgp_evpn_af.j2`) walk pyangbind
  objects close to directly, with minimal template logic. `helpers.py`
  holds the small amount of Python glue templates can't express cleanly
  and is exposed to templates as Jinja globals. `bgp.py` wires up the
  Jinja `Environment` and exposes `render_bgp_instance()`.
  **Whitespace gotcha:** with `trim_blocks=True`, *any* line ending in a
  `{% %}` tag has its trailing newline eaten -- including a content line
  that just happens to end with an inline `{% endif %}` (not only
  tag-only lines). Hit this twice already (the `router bgp <asn> vrf
  <vrf>` header line, then the EVPN `advertise ipv4 unicast [gateway-ip]
  [route-map ...]` line). Fix is the same both times: hoist the optional
  suffix into a `{% set %}` above the line so the content line ends in
  `{{ var }}` instead of `{% endif %}`.
- `examples/basic_bgp.py` -- two-router eBGP config (step 1 smoke test).
- `examples/evpn_bgp.py` -- one EVPN VTEP: default instance
  (advertise-all-vni + per-VNI RD/RT) plus two VRF instances (auto RT,
  type-5 advertisement). Writes one combined `out/evpn_frr.conf`, not
  per-instance files -- see the frr.conf note above.
- `tests/test_render_bgp.py`, `tests/test_render_bgp_evpn.py` -- renderer
  unit tests. Use `pytest.importorskip` on the generated bindings module
  so tests skip cleanly (not fail) if bindings haven't been generated.

## Current scope

**Step 1 (done):** `router bgp <asn>`, optional `vrf <name>`, `bgp
router-id`, neighbors with `remote-as` (as-specified/internal/external),
`network` statements under `address-family ipv4|ipv6 unicast` /
`exit-address-family`.

**Step 2 (in progress, EVPN):** default-instance `advertise-all-vni`,
`advertise-default-gw`, `advertise-svi-ip`, `enable-resolve-overlay-index`,
`flooding`, per-VNI `vni <N>`/`rd`/`route-target`/`flooding`; per-VRF `rd`,
`route-target <both|import|export> <RT|*:NN|auto>`, `advertise
ipv4|ipv6 unicast [gateway-ip] [route-map ...]`; per-neighbor `activate`,
`route-reflector-client`, `route-map <name> in|out`, `allowas-in <N>`.
Verified against most of `frr/tests/topotests/bgp_evpn_*`, `evpn_pim_*`,
`bgp_evpn_mh` by manual comparison (not by loading into a running bgpd).

## Known model gaps

- Per-neighbor EVPN `maximum-prefix` and `addpath-tx-all-paths` are not
  modeled. FRR's own `frr-bgp.yang` augment of the neighbor's
  `l2vpn-evpn` container (around line 866, search
  `augment ".../neighbor/afi-safis/afi-safi/l2vpn-evpn"`) includes
  `as-path-options`/`attr-unchanged`/`route-reflector`/`route-server`/
  `soft-reconfiguration`/`filter-config` but *not*
  `structure-neighbor-prefix-limit` or `structure-neighbor-group-add-paths`
  (both groupings already exist in `frr-bgp-common-structure.yang`,
  reused for other afi-safis -- just not wired up for l2vpn-evpn). Adding
  them needs one more augment in `frr-proteus-bgp-evpn.yang` targeting the
  neighbor path, same pattern as the existing instance-side augment.
- Per-VNI `advertise-default-gw`/`advertise-svi-ip` overrides
  (`bgp_evpn_advertise_default_gw_vni_cmd`/`bgp_evpn_advertise_svi_ip_vni_cmd`)
  and `autort rfc8365-compatible` are not modeled -- not exercised by the
  topotests read so far, add if a topotest needs them.
- The stock `frr-bgp.yang` also has no modeling for `redistribute`
  route-map application details or several other neighbor/global knobs
  beyond what's listed above -- check the YANG file before assuming a
  field exists; it's an incomplete model even outside EVPN.
- Zebra-side Ethernet Segment (EVPN multihoming) config -- `evpn mh
  es-id` etc. -- is genuinely out of scope, not just unimplemented. It's
  zebra's surface (interface/ES config), not bgpd's; this project is
  BGP-only. Don't try to model it here.

## Commands

```sh
# one-time codegen (any Python >=3.9; uses the forked pyangbind submodule)
python3 -m venv .venv-codegen && .venv-codegen/bin/pip install pyang -e ./pyangbind
.venv-codegen/bin/python scripts/generate_bindings.py

# everyday dev, any Python >=3.9
pip install -e ".[dev]"
PYTHONPATH=src python3 examples/basic_bgp.py
PYTHONPATH=src python3 examples/evpn_bgp.py
pytest tests/
```
