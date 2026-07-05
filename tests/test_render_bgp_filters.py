from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, TypeAlias

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from frr_proteus.render import render_bgp_filters

if TYPE_CHECKING:
    from frr_proteus._generated import proteus as bindings
else:
    bindings = pytest.importorskip("frr_proteus._generated.proteus")

ProteusBgpFilter: TypeAlias = bindings.ProteusBgpFilter
AsPathList: TypeAlias = bindings.ProteusBgpFilter.BgpFilters.AsPathAccessList
CommunityList: TypeAlias = bindings.ProteusBgpFilter.BgpFilters.CommunityList
LargeCommunityList: TypeAlias = (
    bindings.ProteusBgpFilter.BgpFilters.LargeCommunityList
)
ExtcommunityList: TypeAlias = bindings.ProteusBgpFilter.BgpFilters.ExtcommunityList
Alias: TypeAlias = bindings.ProteusBgpFilter.CommunityAliases.Alias


def test_empty_root_renders_nothing():
    assert render_bgp_filters(ProteusBgpFilter()) == ""


def test_as_path_access_list():
    root = ProteusBgpFilter()
    asp = AsPathList(name="NO-PRIVATE")
    asp.entry.append(AsPathList.Entry(sequence=5, action="deny", regex="_6451[2-9]_"))
    root.bgp_filters.as_path_access_list.append(asp)
    assert (
        render_bgp_filters(root)
        == "bgp as-path access-list NO-PRIVATE seq 5 deny _6451[2-9]_\n"
    )


def test_standard_community_list_joins_values():
    root = ProteusBgpFilter()
    cl = CommunityList(name="CUSTOMERS", type="standard")
    cl.entry.append(
        CommunityList.Entry(
            sequence=5, action="permit", community=["65001:100", "65001:200"]
        )
    )
    root.bgp_filters.community_list.append(cl)
    assert (
        "bgp community-list standard CUSTOMERS seq 5 permit 65001:100 65001:200\n"
        in render_bgp_filters(root)
    )


def test_expanded_community_list_regex():
    root = ProteusBgpFilter()
    cl = CommunityList(name="RE", type="expanded")
    cl.entry.append(CommunityList.Entry(sequence=5, action="permit", regex="_65...:"))
    root.bgp_filters.community_list.append(cl)
    assert (
        "bgp community-list expanded RE seq 5 permit _65...:\n"
        in render_bgp_filters(root)
    )


def test_large_and_ext_community_lists():
    root = ProteusBgpFilter()
    lcl = LargeCommunityList(name="LARGE", type="standard")
    lcl.entry.append(
        LargeCommunityList.Entry(
            sequence=5, action="permit", large_community=["65001:1:1"]
        )
    )
    root.bgp_filters.large_community_list.append(lcl)
    ecl = ExtcommunityList(name="RTS", type="standard")
    ecl.entry.append(
        ExtcommunityList.Entry(
            sequence=5, action="permit", extcommunity=["rt 65001:10"]
        )
    )
    root.bgp_filters.extcommunity_list.append(ecl)
    text = render_bgp_filters(root)
    assert "bgp large-community-list standard LARGE seq 5 permit 65001:1:1\n" in text
    assert "bgp extcommunity-list standard RTS seq 5 permit rt 65001:10\n" in text


def test_community_alias_line():
    # 'bgp community alias COMMUNITY ALIAS' -- community first
    # (bgp_community_alias_write in bgpd/bgp_community_alias.c).
    root = ProteusBgpFilter()
    root.community_aliases.alias.append(
        Alias(name="cust-gold", community="65001:100")
    )
    assert render_bgp_filters(root) == "bgp community alias 65001:100 cust-gold\n"


def test_type_value_mismatch_raises():
    root = ProteusBgpFilter()
    cl = CommunityList(name="BROKEN", type="expanded")
    cl.entry.append(
        CommunityList.Entry(sequence=5, action="permit", community=["65001:100"])
    )
    root.bgp_filters.community_list.append(cl)
    with pytest.raises(ValueError, match="regex"):
        render_bgp_filters(root)
