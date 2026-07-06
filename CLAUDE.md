# frr-proteus

YANG-to-text-config generator for FRR. Structured Python config data
(fully type-hinted dataclasses generated from FRR's own YANG models via
our pyangbind fork's `pybind-dataclass` backend, extended with
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
under `render/templates/*.j2` walk the generated dataclasses close to
directly;
`render/helpers.py` holds only the handful of functions a template
genuinely can't express (currently just subtree-emptiness checks).
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
- `yang/custom/` -- **the schema new work targets**: a self-contained,
  readable rewrite replacing FRR's YANG as frr-proteus's input model
  (`proteus-bgp.yang`, `proteus-bgp-evpn.yang`, `proteus-route-map.yang`,
  `proteus-types.yang`, plus the referenced-object modules
  `proteus-filter.yang` (prefix-lists + zebra-style access-lists,
  nested per-family ipv4/ipv6/mac containers; cisco-style ACLs
  excluded), `proteus-bgp-filter.yang` (as-path access-lists,
  community/large-community/extcommunity lists -- NAMED lists only,
  the legacy numbered 1-99/100-500 form is excluded -- and
  `bgp community alias` aliases; lives outside proteus-bgp so
  proteus-route-map can leafref it without an import cycle),
  `proteus-bfd.yang` (BFD profiles, intervals in MILLISECONDS
  matching the CLI where FRR's own YANG stores µs; authentication
  excluded pending a key-chain model), `proteus-interface.yang`
  (minimal name+description, mainly a leafref target)). Covers the
  full config surface bgpd's own
  config-write path emits (bgp_config_write* in bgp_vty.c/bgp_route.c/
  bgp_damp.c/bgp_bfd.c, bgp_config_write_evpn_info in bgp_evpn_vty.c,
  route-map match/set vocabulary from lib/routemap_cli.c +
  bgpd/bgp_routemap.c) -- exclusions (SRv6, vpn_policy leaking detail,
  encap/flowspec/link-state AFs, RPKI/BMP/VNC) are listed in
  proteus-bgp.yang's module description and marked with comments at
  the spot where they'd go. Object references (route-maps,
  prefix-lists, access-lists, as-path/community lists, community
  aliases, interfaces, BFD profiles) are YANG `leafref`s checked by
  validate_tree; family-dependent references live in per-family
  groupings (`neighbor-af-filters-ipv4/-ipv6/-evpn`,
  `af-distance-ipv4/-ipv6`) so e.g. an ipv4-unicast prefix-list-in
  can only name an IPv4 prefix-list (the EVPN variant keeps plain
  strings -- no family-correct target). References to objects still
  not modeled (VRFs, key-chains) stay plain strings with a
  `// TODO(leafref)` comment -- keep that convention: when leaving
  out a constraint because the referenced object type isn't modeled
  yet, say so in a comment right there. Gotcha: leafref as a UNION
  member is NOT supported by the codegen backend (pyang only sets
  i_leafref for direct leafref types; a union member would be typed
  as plain str and validate nothing) -- that's why the neighbor
  `address` key, `update-source`, and similar ip-or-ifname unions
  stay strings; never put a leafref inside a union.
  Hard rules, per explicit user direction (gold standard:
  `/home/robin/work/srlinux-yang-models/all/v26.3.1/srl_nokia/models/`):
  (1) MUST NOT reference FRR's YANG at all. Standard value types come
  from RFC 6991: pristine copies of `ietf-inet-types.yang` /
  `ietf-yang-types.yang` (from pyang's bundled modules) are vendored
  under `yang/vendor/ietf/` -- ALL vendored external YANG goes under
  `yang/vendor/<origin>/`, never mixed into yang/custom; the custom
  search path is [yang/custom, yang/vendor/ietf] (generate_bindings).
  Do NOT redefine types RFC 6991 provides (user was explicit) --
  `proteus-types.yang` keeps only what it can't express. Pick types by
  SEMANTICS: the `-no-zone` address variants (FRR config text never
  carries %zone), `inet:ipv4-/ipv6-prefix`, `yang:mac-address`,
  `yang:hex-string` length-restricted for octet strings (evpn-esi =
  length 29), and `yang:dotted-quad` for 32-bit identifiers in dotted
  notation (router-id, cluster-id, originator-id) which are NOT
  addresses. Codegen note: RFC 6991 patterns contain XSD `\p{...}`
  escapes; the pyangbind fork translates them to ASCII classes (fixed
  in pybind_dataclass.py -- previously the whole base pattern was
  silently dropped and derived types like ipv4-address-no-zone
  validated almost nothing).
  (1b) Values with standard internal structure are STRUCTURED, never
  pattern-checked strings (user was explicit): route distinguishers
  (RFC 4364 administrator/assigned-number per type, grouping
  pt:route-distinguisher), communities (pt:community-set /
  pt:community-value: uint16 pairs + well-known enum -- the 14 tokens
  FRR's community_gettoken accepts; `internet` was REMOVED upstream),
  large communities (pt:large-community-set, RFC 8092 GA/LD1/LD2),
  route targets AND route origins. Route Target (RFC 4360 subtype
  0x02) and Route Origin / site-of-origin (subtype 0x03) are DIFFERENT
  extended communities -- separate pt groupings, never reuse
  route-target for an soo node (user called the old mac-vrf-soo `uses
  pt:route-target` "factually incorrect"). Every structured set
  carries a `raw` string fallback rendered verbatim -- deliberately
  matching/scrubbing malformed values is a legitimate use. Formats
  FRR can't parse yet are still modeled but BLOCKED with `must
  "false()"` + explanatory error-message (e.g. the type-6 MAC RD) so
  unblocking is a one-line delete; do NOT simply omit standard
  encodings. Gotcha: an all-empty container counts as unconfigured
  (mandatory choice inside is skipped), so "this container is
  required" needs a `must` on the PARENT (see the EVPN type-5 network
  rd), and a must on the container itself won't fire when it's empty.
  (2) No `augment` unless it REALLY earns its keep --
  FRR's augment-everything style is what made their model unreadable;
  sibling modules contribute content via plain `import` + `uses`
  groupings (`proteus-bgp-evpn.yang` defines zero data nodes, only
  groupings that `proteus-bgp.yang` uses), so the whole tree reads
  top-down in `proteus-bgp.yang`. (3) Address families are nested
  containers (`afi-safis/ipv4-unicast`, `afi-safis/l2vpn-evpn`, ...),
  NOT the OpenConfig/Nokia identityref-keyed `afi-safi` list whose
  entries all carry every family's container plus `must` guards --
  the user explicitly prefers the nested shape. Structure departs
  from FRR where FRR's is baroque (no control-plane-protocol wrapper:
  root is `/bgp/instance`, keyed by `vrf` since FRR allows one BGP
  instance per VRF; neighbor `remote-as` is one union leaf
  `as-number | internal | external` mirroring the single CLI token,
  not FRR's remote-as-type + remote-as pair). Descriptions cite the
  bgp_vty.c/bgp_evpn_vty.c DEFUN/DEFPY behind every leaf -- keep
  doing that; don't add leaves whose CLI text isn't verified there.
  Codegen emits these as the `_generated/proteus/` package (root class
  `ProteusBgp`); the renderers, tests and examples all consume this
  package now. `_generated/frr_bgp/` (from the FRR schema) is still
  generated for reference but has no renderer.
  `proteus-bgp-evpn-experimental.yang` models the user's experimental
  EVPN config scheme (vxlan-underlay, auto-discover-vnis, underlay-vrf
  leafrefs, origination-l3vni/-l2vni, vlan-based-evi blocks, global
  `evpn` block). Its nodes are ADDITIONAL, always compiled into the
  same package, and coexist with the legacy EVPN nodes on one object;
  opting in happens at the renderer via the output format, not the
  schema. It is the one permitted `augment` in yang/custom: its
  underlay leafrefs point into proteus-bgp's instance list, fixing the
  import direction, so proteus-bgp can't `uses` a grouping from it
  (cycle) -- documented in the module description. Its CLI text
  follows the scheme's spec example, NOT bgpd source (nothing to
  verify against). Underlay references must point at an instance
  *marked vxlan-underlay*: stated as YANG `must` and enforced by
  validate_tree, which evaluates must/when now -- pass the
  experimental module root alongside the BGP root so the global
  block's references are covered (the old
  `frr_proteus.validate.validate_underlay_refs()` Python check is
  retired).
  Gotcha:
  `validate_tree()` resolves leafrefs by absolute schema path, so it
  must be passed the *module root* objects -- `validate_tree(
  ProteusBgp_instance, ProteusRouteMap_instance)` -- not the `bgp` /
  `route_maps` containers below them; with a container as root every
  leafref "fails" because recorded value paths lose the top component.
- `yang/augments/` -- the older, now renderer-less approach, kept as
  reference: project-authored `augment`s of FRR's
  own modules *from outside* (targeting FRR's schema paths with
  explicit `frr-bgp:`-prefixed node names) rather than editing the
  vendored `frr/` submodule. `frr-proteus-bgp-evpn.yang` fills in
  FRR's `l2vpn-evpn` afi-safi container, which upstream ships as a
  genuinely empty placeholder (every *other* afi-safi gets real
  content augmented onto it in `frr-bgp.yang`; l2vpn-evpn never does;
  the *neighbor*-side l2vpn-evpn container is augmented generically by
  FRR itself with `route-reflector-client`/`route-map`/`allowas-in`/etc,
  so only the instance side needed filling in).
- `pyangbind/` -- git submodule pinned to our pyangbind fork
  (github.com/robinchrist/pyangbind). Fixes go into the fork directly
  now (e.g. the bits-position TypeError that generate_bindings.py used
  to monkeypatch in-memory; 3.12+ support was already fixed on upstream
  master vs. the 0.8.7 PyPI release). Install it editable (`pip install
  -e ./pyangbind`), never from PyPI. It is a codegen-time tool, not a
  runtime dependency of frr-proteus -- but a *single* venv is fine (no
  separate codegen venv): pyangbind and pyang are imported only by
  `scripts/generate_bindings.py`, never by `src/frr_proteus`, so they
  can't leak into the runtime dep set regardless. Carries our
  `pybind-dataclass` pyang output plugin
  (`pyangbind/plugin/pybind_dataclass.py`) -- the backend this project
  actually uses; the classic dynamic `pybind` backend is kept working
  but unused here.
- `scripts/generate_bindings.py` -- pyangbind codegen, runs on any
  Python >=3.12 (the project's minimum) with the fork installed (the old
  python3.11-only restriction applied to the unpatched PyPI release).
  Compiles
  `frr/yang/frr-bgp.yang` + `yang/frr-proteus-bgp-evpn.yang` together
  into the `frr_bgp/` bindings package (`--dataclass-split-dir` mode:
  shared runtime/reusable types once in `_runtime.py`/`_types.py`, one
  file per data-defining YANG module, `__init__.py` re-exports all --
  imports look exactly like the old single-file module; note the BGP
  tree lives in `frr_routing.py` because `frr-bgp.yang` only *augments*
  `frr-routing`, defining no top-level data nodes of its own).
  `scripts/generate_dataclass_bindings.py` is the generic driver for
  pointing the same backend at any other model tree (tested on Nokia SR
  Linux); `-o file.py` for single-file, `-d dir/` for a package.
  Gotcha: it locates the pyang plugin dir via
  `pyangbind.plugin.pybind.__file__`, not `pyangbind.__path__` -- with
  the editable install, a process cwd'd at the repo root sees the
  submodule checkout dir (which holds the package one level down) as a
  same-named namespace package, and `__path__` then points at the wrong
  level.
- `src/frr_proteus/_generated/` -- generated bindings (the `frr_bgp/`
  package). Gitignored
  (~1.3MB, trivially reproducible). Must be generated before running
  examples or tests. Shape: plain stdlib dataclasses, nested to mirror
  the YANG tree (`FrrRouting.Routing.ControlPlaneProtocols.
  ControlPlaneProtocol.Bgp...`), zero runtime deps, understood
  end-to-end by mypy/pyright (the package ships `py.typed`). Semantics
  to keep in mind: an unset leaf is always `None` -- YANG defaults are
  *not* applied, so templates can rely on "falsy means not explicitly
  configured"; enums and identityrefs are `typing.Literal` strings
  (identityref values accepted both bare and module-prefixed, e.g.
  "l2vpn-evpn" or "frr-routing:l2vpn-evpn" -- helpers strip the prefix).
  identityrefs and *named-typedef* enums are hoisted to module-level
  reusable PEP 695 aliases (`type AfiSafiType = typing.Literal[...]`,
  `type Direction = ...`) named from the base identity / typedef and
  referenced by name -- importable, e.g. `from frr_proteus._generated.
  frr_bgp import AfiSafiType` (this is why the bindings now require Python
  >=3.12); inline anonymous enums stay inlined. YANG lists are plain
  `list[Entry]` (key leaves are ordinary fields,
  e.g. `neighbor.remote_address`; keyed-ness/uniqueness not enforced);
  config-false subtrees are omitted. The backend generates validation
  and YANG defaults by default (opt-outs: `--no-dataclass-validation`,
  `--no-dataclass-defaults`; pyang is optparse-based so there are no
  automatic argparse-style --no-* complements -- the negatives are
  declared explicitly, and negating flags are spelled with a leading
  `--no`). Validation: YANG value restrictions (ranges incl. built-in
  int bounds, patterns, lengths, enum/identityref sets, unions, bits)
  are enforced on *assignment* (including constructor kwargs), raising
  `YangValidationError`; `None` is always accepted; leaf-list elements
  are checked on list assignment but not on `.append()`; structural
  rules (mandatory, list keys, when/must) are deferred to
  validate_tree, not checked on assignment. This project
  generates with `--no-dataclass-defaults`: applying YANG defaults
  would break the falsy-means-unconfigured contract the renderers rely
  on. Structural/referential rules are covered by the module-level
  `validate_tree(*roots)` whole-tree pass (call it once the tree is
  built -- creation order stays free): leafref referential integrity,
  mandatory leaves, list keys present + unique, `unique` groups,
  leaf-list value uniqueness, min-/max-elements, choice exclusivity /
  mandatory choices, it re-checks every value (so it also catches
  what `.append()` bypassed), and it evaluates `must`/`when` with an
  XPath 1.0 subset engine embedded in the generated runtime (location
  paths, predicates, current(), comparisons, and/or, core functions,
  exact-match derived-from-or-self; when-contexts per RFC 7950
  7.21.5; expressions outside the subset are skipped, never
  misjudged; opt-out: `--no-dataclass-must-when`). Absolute must/when
  paths resolve across all roots passed to validate_tree, so pass
  every module root the expressions reach into. All
  violations are aggregated into one `YangValidationError` with
  instance paths. This project also generates with
  `--dataclass-origin-comments` (a `# from file:line, via uses/augment
  ...` comment above each grouping/augment-contributed node -- most of
  the FRR tree), `--dataclass-serde` (`to_ietf_json`/`from_ietf_json`,
  RFC 7951 JSON as plain dicts) and `--dataclass-xpaths`
  (`_yang_schema_path` ClassVars + `data_path(root, node)` instance
  paths). Everything is driven by per-class `_yang_fields` ClassVar
  metadata tables; instances stay plain dataclasses. A feature-free
  variant backend `pybind-dataclass-dumb` is kept in the fork.
- `src/frr_proteus/render/` -- templates under `templates/*.j2` (one per
  protocol/AF, e.g. `bgp.conf.j2`, `bgp_evpn_af.j2`) walk the generated
  *proteus* dataclasses (`/bgp/instance` entries) close to directly, with
  minimal template logic. `helpers.py` holds the small amount of Python
  glue templates can't express cleanly (has_config/evpn_configured
  subtree-emptiness checks -- the old identityref/enum helpers died with
  the FRR-schema migration) and is exposed to templates as Jinja globals.
  `bgp.py` wires up the Jinja `Environment` and exposes
  `render_bgp_instance(instance, format=...)` (takes one instance list
  entry; the vrf clause comes from its `vrf` key) plus
  `render_evpn_global(evpn, format=...)` for the experimental global
  `evpn` block. The referenced-object renderers follow the same shape,
  sharing one Jinja `Environment` from `_env.py`: `filters.py` /
  `filters.conf.j2` (`render_filters`, prefix- and access-lists; IPv4
  access-lists are UNPREFIXED `access-list ...` per lib/filter_cli.c),
  `bgp_filters.py` (`render_bgp_filters`, as-path/community lists +
  aliases, with a type-vs-value backstop check), `bfd.py`
  (`render_bfd`), `interfaces.py` (`render_interfaces`), and
  `route_map.py` / `route_map.conf.j2` (`render_route_maps` -- every
  line replicates a vty_out in lib/routemap_cli.c's dispatchers;
  bgp_routemap.c only holds the DEFPY parsers, route-maps ARE
  northbound-converted). All are re-exported from `render/__init__`.
  The `neighbor X ...` line vocabulary lives in
  `bgp_neighbor_macros.j2`, shared verbatim between peer-groups and
  real neighbors and (for the per-AF macro) between all address
  families, mirroring how FRR installs the same commands everywhere:
  `session_lines` covers description/bfd [profile]/password/
  `neighbor X interface IFNAME`/passive/ebgp-multihop (255 renders the
  bare form)/ttl-security/enforce-first-as/update-source/
  advertisement-interval/timers [connect] in
  bgp_config_write_peer_global's order; `af_lines` covers [no]
  activate/route-reflector-client/next-hop-self [force]/
  remove-private-AS variants/as-override/send-community negations/
  default-originate/soft-reconfiguration inbound/maximum-prefix[-out]/
  allowas-in/weight/the filter references (distribute-list/prefix-list/
  route-map/unsuppress-map/advertise-map/filter-list from
  bgp_config_write_filter)/attribute-unchanged in
  bgp_config_write_peer_af's order. `bgp.conf.j2` itself renders the
  header lines whose shape differs (peer-group declarations before
  neighbors matching bgp_config_write's loop order; `neighbor IFNAME
  interface [v6only] [peer-group PG|remote-as R]` for unnumbered
  interface peers; separate peer-group-membership/remote-as lines
  otherwise) plus the instance-level knobs ([no] bgp default
  <family>, [no] deterministic-med, graceful-restart[-disable],
  bestpath as-path multipath-relax [as-set], bestpath
  compare-routerid). Three-valued leaves (activate,
  default.ipv4-unicast, deterministic-med, enforce-first-as,
  send-community) render nothing when unset and the explicit
  positive/negative form otherwise. `has_config` is registered as a
  Jinja *test* there for `selectattr(..., 'has_config')`.
  route-map `set metric` is a STRUCTURED container, not a
  sign-carrying value (per the structured-values rule; a
  string-pattern union member was explicitly rejected by the user):
  `operation` (set/add/subtract, unset renders like set) is the
  CLI's bare/`+`/`-` prefix, the operand is a real uint32 `value` or
  the rtt/igp/aigp `variable` leaf; `must`s enforce value XOR
  variable and that only rtt is add/subtractable
  (route_value_compile in bgpd/bgp_routemap.c). Two output formats: `"frr"` (default) renders legacy
  syntax and *translates* the experimental typing where stock FRR has
  an equivalent (vxlan-underlay -> `advertise-all-vni` (direct
  equivalent per the user), vlan-based-evi with origination-l2vni ->
  `vni` block; wildcard/auto RTs, underlay refs and the global block
  are dropped); `"experimental"` renders the new scheme's syntax and
  removes legacy EVPN command syntax (neighbor lines and route-targets
  are shared and render in both). Only the l2vpn evpn AF differs
  between formats -- template selection via
  `{% include evpn_af_template %}`; per-neighbor lines live in shared
  `bgp_evpn_neighbors.j2`, RT/EVI rendering in `evpn_macros.j2`.
  **Whitespace gotcha:** with `trim_blocks=True`, *any* line ending in a
  `{% %}` tag has its trailing newline eaten -- including a content line
  that just happens to end with an inline `{% endif %}` (not only
  tag-only lines). Hit this twice already (the `router bgp <asn> vrf
  <vrf>` header line, then the EVPN `advertise ipv4 unicast [gateway-ip]
  [route-map ...]` line). Fix is the same both times: hoist the optional
  suffix into a `{% set %}` above the line so the content line ends in
  `{{ var }}` instead of `{% endif %}`.
- `examples/basic_bgp.py` -- two-router eBGP config (step 1 smoke test);
  r1 additionally exercises the object modules (prefix-list feeding a
  route-map via route-map-in, BFD profile on the neighbor), composing
  one frr.conf-shaped file per router (`out/r1_frr.conf`,
  `out/r2_frr.conf`): objects first, then the router bgp block.
- `examples/evpn_bgp.py` -- one EVPN VTEP: default instance
  (advertise-all-vni + per-VNI RD/RT) plus two VRF instances (auto RT,
  type-5 advertisement) and a route-map on the EVPN neighbor. Writes one
  combined `out/evpn_frr.conf`, not per-instance files -- see the
  frr.conf note above.
- `examples/evpn_dual_speed_host.py` -- anonymized reproduction of a
  real Proxmox-style EVPN compute host: dual-speed (100G/25G)
  unnumbered eBGP underlay whose per-loopback large communities steer
  link-speed preference (four route-maps generated from one loopback
  table: call + on-match next, set metric +100, set weight,
  match/set large-community), eBGP multihop overlay peer-group with
  password/update-source, L2 VNIs + three tenant-VRF instances. The
  original's `as-notation dot` is not modeled (plain 4-byte ASNs
  instead); its zebra/vtysh lines (frr defaults/hostname/log/`vrf ...
  vni`/interface `ipv6 nd ra-interval`) ride along as a literal
  PREAMBLE constant, explicitly marked out-of-scope.
- `examples/internet_peering.py` -- medium-sized internet edge: IXP
  route-server peer-group (maximum-prefix restart, no
  enforce-first-as), transit neighbor (password, ttl-security,
  maximum-prefix threshold warning-only, remove-private-AS all), iBGP
  core session (next-hop-self, update-source), bogon/own-prefix
  filtering and community tagging via shared route-maps, private-ASN
  as-path leak guard.
- `examples/evpn_fabric.py` -- the multi-device showcase: a whole
  leaf-spine pod (2 spines + 3 leaves, 2 tenants) generated from one
  topology table, both ends of every link/session derived from the
  same rule. All-eBGP: unnumbered underlay peer-group (remote-as
  external on the group, BFD profile, loopbacks-only export
  route-map), eBGP multihop EVPN overlay (spines set
  attribute-unchanged next-hop), leaves carry L2 VNIs + per-tenant
  VRF instances with type-5. One `out/fabric/<name>_frr.conf` per
  device.
- `tests/test_render_*.py` -- renderer unit tests (bgp, bgp_evpn,
  evpn_experimental, filters, bgp_filters, bfd, interfaces, route_map);
  `tests/test_validate_object_refs.py` pins the cross-module leafref
  checks (incl. family precision of the split filters/distance
  groupings). All use `pytest.importorskip` on the generated bindings
  module so tests skip cleanly (not fail) if bindings haven't been
  generated.

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
# one venv for everything (Python >=3.12). The codegen extra pulls pyang;
# the pyangbind fork is a local path submodule so it's a separate editable install.
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,codegen]" -e ./pyangbind

# one-time codegen (uses the forked pyangbind submodule)
.venv/bin/python scripts/generate_bindings.py

# everyday dev
PYTHONPATH=src .venv/bin/python examples/basic_bgp.py
PYTHONPATH=src .venv/bin/python examples/evpn_bgp.py
PYTHONPATH=src .venv/bin/python examples/evpn_dual_speed_host.py
PYTHONPATH=src .venv/bin/python examples/internet_peering.py
PYTHONPATH=src .venv/bin/python examples/evpn_fabric.py
.venv/bin/pytest tests/
```
