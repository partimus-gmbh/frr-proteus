# frr-proteus

YANG-to-text-config generator for FRR. Structured Python config data (built
via pyangbind classes generated from FRR's own YANG models) in, FRR daemon
config text out. See README.md for the full pitch and setup steps.

## Why this project exists

FRR's `bgpd` has no northbound backend: no `bgpd/bgp_nb.c`, no `cli_show`
callbacks (verified: `grep -rn cli_show frr/bgpd/` is empty). Other FRR
daemons that *are* northbound-converted (staticd, ripd, ...) can load
structured/YANG config directly and their `cli_show` callbacks double as
the YANG->text mapping. bgpd has neither, so this project fills that gap:
codegen gets you a typed, validated Python object model matching the YANG
schema, but the actual rendering to CLI text is hand-written, sourced from
reading `frr/bgpd/bgp_vty.c`'s `vty_out()` calls directly.

**Do not assume the renderer can be derived from the YANG model alone.**
Every new field the renderer supports needs its exact CLI text confirmed
against `bgp_vty.c` (or the relevant daemon's `_vty.c`), not guessed from
the YANG leaf name or from topotest `.conf` fixtures (those are hand-written
*input* files using accepted shorthand, e.g. `address-family ipv4` instead
of the canonical `show running-config` output `address-family ipv4
unicast` -- both are valid to feed to bgpd, but this project always emits
the canonical/full form: match `bgp_config_write*()`, not test fixtures).

## Layout

- `frr/` -- git submodule pinned to FRR master. Source of truth for YANG
  models (`frr/yang/*.yang`) and CLI rendering logic
  (`frr/bgpd/bgp_vty.c`, `frr/bgpd/bgp_route.c` for network/aggregate
  writers). Never parse or generate FRR C code -- only read it as a
  reference for what text to emit.
- `scripts/generate_bindings.py` -- pyangbind codegen. Requires a Python
  3.11 interpreter (see script docstring: pyangbind's pyang plugin breaks
  on 3.12+, and hits a real upstream bug on bits-typedefs that this script
  monkeypatches *in memory* -- it never edits the installed pyangbind
  package on disk, so re-running always starts from a clean pip install).
- `src/frr_proteus/_generated/` -- pyangbind output. Gitignored (7-8MB
  generated file, not diffable, trivially reproducible). Must be generated
  before running examples or tests.
- `src/frr_proteus/render/` -- rendering is Jinja2-first: templates under
  `templates/*.j2` (one per protocol, e.g. `bgp.conf.j2`) walk pyangbind
  objects close to directly, with minimal template logic. `helpers.py`
  holds the small amount of Python glue templates can't express cleanly
  (enum branching, identityref prefix stripping) and is exposed to
  templates as Jinja globals. `bgp.py` (etc.) just wires up the Jinja
  `Environment` and exposes a thin `render_*_instance(obj, **ctx)`
  function -- keep new protocol renderers to that same shape rather than
  building output with Python string concatenation. (The user was
  explicit about this: an earlier all-Python string-building renderer got
  replaced after they called it "completely unreadable.")
- `examples/basic_bgp.py` -- builds a small two-router eBGP config and
  renders it; the standing smoke test for "does this look like real bgpd
  config".
- `tests/test_render_bgp.py` -- renderer unit tests. Uses
  `pytest.importorskip` on the generated bindings module so tests skip
  cleanly (not fail) if bindings haven't been generated yet.

## Current scope (step 1, done)

`router bgp <asn>`, optional `vrf <name>`, `bgp router-id`, neighbors with
`remote-as` (as-specified/internal/external), `network` statements under
`address-family ipv4|ipv6 unicast` / `exit-address-family`.

## Known model gaps

- **EVPN is entirely unmodeled in FRR's YANG.** Confirmed: no `evpn`
  anywhere under `frr/yang/`. Step 2 (not started) is writing an EVPN YANG
  model by reading `bgpd`'s EVPN C code (vty + data structures), separate
  from and on top of the vendored `frr-bgp.yang`. Do not expect to find
  it already there.
- The stock `frr-bgp.yang` also has no modeling for `redistribute`
  route-map application details or several other neighbor/global knobs
  beyond what step 1 covers -- check the YANG file before assuming a field
  exists; it's an incomplete model, not just missing EVPN.

## Commands

```sh
# one-time codegen (needs python3.11 specifically)
python3.11 -m venv .venv-codegen && .venv-codegen/bin/pip install pyang pyangbind
.venv-codegen/bin/python scripts/generate_bindings.py

# everyday dev, any Python >=3.9
pip install -e ".[dev]"
PYTHONPATH=src python3 examples/basic_bgp.py
pytest tests/
```
