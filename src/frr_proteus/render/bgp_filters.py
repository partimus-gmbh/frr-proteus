"""Render proteus-bgp-filter objects: as-path access-lists, community/
large-community/extcommunity lists, community aliases.

Text sources: config_write_as_list in bgpd/bgp_filter.c,
community_list_config_write in bgpd/bgp_vty.c,
bgp_community_alias_write in bgpd/bgp_community_alias.c. Named lists
only -- the legacy numbered form is excluded from the schema.
"""

from __future__ import annotations

from frr_proteus.render import helpers
from frr_proteus.render._comments import render_with_comments
from frr_proteus.render._env import env

_template = env.get_template("bgp_filters.conf.j2")

# (list field, standard-values container field, texts helper) per
# community-list flavor, for the type-vs-value backstop check below.
_COMMUNITY_LISTS = [
    ("community_list", "communities", helpers.community_texts),
    (
        "large_community_list",
        "large_communities",
        helpers.large_community_texts,
    ),
    ("extcommunity_list", "extcommunities", helpers.extcommunity_texts),
]


def render_bgp_filters(root) -> str:
    """Render all filter lists and community aliases of a generated
    ProteusBgpFilter root. Returns "" when nothing is configured.

    Backstop check (the YANG 'must's cover this in validate_tree, but
    a caller may render without validating): every entry of a
    standard list must carry literal values, every entry of an
    expanded list a regex.
    """
    for list_field, values_field, texts in _COMMUNITY_LISTS:
        for clist in getattr(root, list_field):
            for entry in clist.entry:
                if clist.type == "expanded":
                    value_set = entry.regex
                else:
                    value_set = texts(getattr(entry, values_field))
                if not value_set:
                    raise ValueError(
                        f"{list_field.replace('_', '-')} {clist.name!r} entry "
                        f"{entry.sequence}: a {clist.type} list entry needs "
                        + (
                            "a regex"
                            if clist.type == "expanded"
                            else "literal values"
                        )
                    )
    for alias in root.community_alias:
        if helpers.community_value_text(alias.community) is None:
            raise ValueError(
                f"community alias {alias.name!r} has no community value"
            )
    return render_with_comments(_template, bgp_filters=root)
