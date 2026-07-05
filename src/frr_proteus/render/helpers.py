"""Small bindings-to-Jinja glue functions for the BGP templates.

Kept deliberately thin: anything that's just "read this YANG field and
print it" belongs in the template. The proteus schema (yang/custom/)
made most of the old glue unnecessary -- no identityref prefixes to
strip, no afi-safi list to scan, no remote-as-type enum to branch on
(remote-as is one union leaf whose value is the CLI token). What's left
is the one thing Jinja can't express: deciding whether a generated
subtree contains any configuration at all.
"""

from __future__ import annotations

import dataclasses


def has_config(node: object) -> bool:
    """True if any leaf anywhere under this generated dataclass is set.

    Mirrors the bindings' semantics: an unset leaf is None, an empty
    list/leaf-list is unset, and a container "exists" only if some
    descendant leaf is set (YANG non-presence container existence).
    """
    for field in dataclasses.fields(node):  # type: ignore[arg-type]
        value = getattr(node, field.name)
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            if has_config(value):
                return True
        elif isinstance(value, list):
            if value:
                return True
        elif value is not None:
            return True
    return False


def route_target_texts(rt_set, *, include_wildcard: bool = True) -> list[str]:
    """Render a proteus-types route-target-set container (plus, where
    present, the EVPN VRF import 'wildcard' leaf-list) into FRR's CLI
    tokens: '<AS>:<NN>' / '<A.B.C.D>:<NN>' / '*:<NN>'.

    All three encoding lists carry global-admin/local-admin pairs, so
    one f-string covers them; the encoding distinction only matters
    for validation ranges and on the wire, not in the rendered text.
    The 'auto' sentinel is a separate leaf and rendered by the
    template, not here. ``include_wildcard=False`` drops the wildcard
    entries -- used by the frr-format compatibility translation of
    vlan-based-evi blocks into 'vni' blocks, whose RT lines cannot
    express a wildcard.
    """
    texts = [
        f"{rt.global_admin}:{rt.local_admin}"
        for rt in [*rt_set.as2, *rt_set.as4, *rt_set.ipv4]
    ]
    if include_wildcard:
        texts += [
            f"*:{local_admin}"
            for local_admin in getattr(rt_set, "wildcard", None) or []
        ]
    return texts


def rd_text(rd) -> str | None:
    """Render a proteus-types route-distinguisher container into FRR's
    CLI token: '<administrator>:<assigned-number>' for the structured
    types 0/1/2, the raw string verbatim, or None when unconfigured.

    The type-6 MAC case is included for completeness but blocked in the
    schema (must false() -- FRR cannot parse it), so it never reaches a
    validated tree.
    """
    for encoding in (rd.as2, rd.ipv4, rd.as4):
        if encoding.administrator is not None:
            return f"{encoding.administrator}:{encoding.assigned_number}"
    if rd.mac:
        return rd.mac
    if rd.raw:
        return rd.raw
    return None


def community_texts(cset) -> list[str]:
    """Render a proteus-types community-set (structured members,
    well-known names, raw fallbacks) into FRR's CLI tokens, in that
    order. Raw entries are emitted verbatim -- deliberately
    unvalidated (matching/scrubbing malformed communities is a real
    use case)."""
    return [
        *(f"{m.global_admin}:{m.local_admin}" for m in cset.member),
        *cset.well_known,
        *cset.raw,
    ]


def large_community_texts(cset) -> list[str]:
    """Render a proteus-types large-community-set into 'GA:LD1:LD2'
    tokens plus raw fallbacks."""
    return [
        *(
            f"{m.global_admin}:{m.local_data_1}:{m.local_data_2}"
            for m in cset.member
        ),
        *cset.raw,
    ]


def community_value_text(value) -> str | None:
    """Render a proteus-types community-value container (one community:
    standard, well-known, large, or raw) into its CLI token, or None
    when unconfigured."""
    if value.community.global_admin is not None:
        return f"{value.community.global_admin}:{value.community.local_admin}"
    if value.well_known:
        return value.well_known
    if value.large_community.global_admin is not None:
        lc = value.large_community
        return f"{lc.global_admin}:{lc.local_data_1}:{lc.local_data_2}"
    if value.raw:
        return value.raw
    return None


def extcommunity_texts(ec) -> list[str]:
    """Render an extcommunity-list standard entry's container into
    'rt <RT>' / 'soo <SoO>' tokens plus raw fallbacks (raw entries
    carry their own rt/soo keyword). Route targets and route origins
    are distinct RFC 4360 subtypes, hence the two sets."""
    return [
        *(f"rt {t}" for t in route_target_texts(ec.route_target)),
        *(f"soo {t}" for t in route_target_texts(ec.route_origin)),
        *ec.raw,
    ]


def extcommunity_nt_texts(nt) -> list[str]:
    """Render a set-extcommunity-nt container into FRR's tokens:
    '<node-id>:0' per Node Target (the :0 is the reserved field FRR's
    tokenizer requires) plus raw fallbacks."""
    return [*(f"{node_id}:0" for node_id in nt.node_id), *nt.raw]


def extcommunity_color_texts(colors) -> list[str]:
    """Render a set-extcommunity-color container into FRR's tokens:
    '[CO:]COLOR' per color (CO bits in binary, RFC 9256) plus raw
    fallbacks."""
    return [
        *(
            f"{c.co_flags}:{c.value}" if c.co_flags else str(c.value)
            for c in colors.color
        ),
        *colors.raw,
    ]


# Experimental-scheme fields on the instance-level l2vpn-evpn container
# (proteus-bgp-evpn-experimental.yang's augment) that produce NO output
# in the frr format. vxlan_underlay is absent on purpose: it translates
# to 'advertise-all-vni', so it counts as renderable config there;
# vlan_based_evi is listed but handled separately (translatable only
# when an EVI carries an origination-l2vni).
_FRR_UNRENDERABLE_EVPN_FIELDS = frozenset(
    {
        "auto_discover_vnis",
        "underlay_vrf",
        "origination_l3vni",
        "vlan_based_evi",
    }
)


def _has_config_except(node: object, exclude: frozenset[str]) -> bool:
    for field in dataclasses.fields(node):  # type: ignore[arg-type]
        if field.name in exclude:
            continue
        value = getattr(node, field.name)
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            if has_config(value):
                return True
        elif isinstance(value, list):
            if value:
                return True
        elif value is not None:
            return True
    return False


def evpn_af_needed(instance, format: str) -> bool:
    """Whether this instance needs an 'address-family l2vpn evpn' block
    in the given output format.

    Neighbor EVPN config always needs the block. Beyond that it depends
    on what the format would actually emit: the experimental format
    renders both typings, the frr format renders legacy fields plus the
    translatable subset of the experimental ones (EVIs that carry an
    origination-l2vni) -- an instance holding only untranslatable
    experimental config must not produce an empty AF block there.
    """
    evpn = instance.afi_safis.l2vpn_evpn
    if any(
        has_config(neighbor.afi_safis.l2vpn_evpn)
        for neighbor in instance.neighbor
    ):
        return True
    if format == "experimental":
        return has_config(evpn)
    if _has_config_except(evpn, _FRR_UNRENDERABLE_EVPN_FIELDS):
        return True
    return any(evi.origination_l2vni for evi in evpn.vlan_based_evi)
