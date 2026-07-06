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
AsPathList: TypeAlias = bindings.ProteusBgpFilter.AsPathAccessList
CommunityList: TypeAlias = bindings.ProteusBgpFilter.CommunityList
LargeCommunityList: TypeAlias = (
    bindings.ProteusBgpFilter.LargeCommunityList
)
ExtcommunityList: TypeAlias = bindings.ProteusBgpFilter.ExtcommunityList
Alias: TypeAlias = bindings.ProteusBgpFilter.CommunityAlias


def test_empty_root_renders_nothing():
    assert render_bgp_filters(ProteusBgpFilter()) == ""


def test_as_path_access_list():
    root = ProteusBgpFilter()
    asp = AsPathList(name="NO-PRIVATE")
    asp.entry.append(AsPathList.Entry(sequence=5, action="deny", regex="_6451[2-9]_"))
    root.as_path_access_list.append(asp)
    assert (
        render_bgp_filters(root)
        == "bgp as-path access-list NO-PRIVATE seq 5 deny _6451[2-9]_\n"
    )


def test_standard_community_list_joins_values():
    root = ProteusBgpFilter()
    cl = CommunityList(name="CUSTOMERS", type="standard")
    entry = CommunityList.Entry(sequence=5, action="permit")
    Member = CommunityList.Entry.Communities.Member
    entry.communities.member.append(Member(global_admin=65001, local_admin=100))
    entry.communities.member.append(Member(global_admin=65001, local_admin=200))
    entry.communities.well_known.append("no-export")
    entry.communities.raw.append("4294967296:1")  # deliberately invalid
    cl.entry.append(entry)
    root.community_list.append(cl)
    assert (
        "bgp community-list standard CUSTOMERS seq 5 permit "
        "65001:100 65001:200 no-export 4294967296:1\n" in render_bgp_filters(root)
    )


def test_expanded_community_list_regex():
    root = ProteusBgpFilter()
    cl = CommunityList(name="RE", type="expanded")
    cl.entry.append(CommunityList.Entry(sequence=5, action="permit", regex="_65...:"))
    root.community_list.append(cl)
    assert (
        "bgp community-list expanded RE seq 5 permit _65...:\n"
        in render_bgp_filters(root)
    )


def test_large_and_ext_community_lists():
    root = ProteusBgpFilter()
    lcl = LargeCommunityList(name="LARGE", type="standard")
    lentry = LargeCommunityList.Entry(sequence=5, action="permit")
    lentry.large_communities.member.append(
        LargeCommunityList.Entry.LargeCommunities.Member(
            global_admin=65001, local_data_1=1, local_data_2=1
        )
    )
    lcl.entry.append(lentry)
    root.large_community_list.append(lcl)

    ecl = ExtcommunityList(name="RTS", type="standard")
    eentry = ExtcommunityList.Entry(sequence=5, action="permit")
    ec = eentry.extcommunities
    # Route target and route origin are DIFFERENT extended communities
    # (RFC 4360 subtypes 0x02 vs 0x03) -- distinct sets in the model.
    ec.route_target.as2.append(
        ExtcommunityList.Entry.Extcommunities.RouteTarget.As2(
            global_admin=65001, local_admin=10
        )
    )
    ec.route_origin.ipv4.append(
        ExtcommunityList.Entry.Extcommunities.RouteOrigin.Ipv4(
            global_admin="192.0.2.1", local_admin=7
        )
    )
    ecl.entry.append(eentry)
    root.extcommunity_list.append(ecl)

    text = render_bgp_filters(root)
    assert "bgp large-community-list standard LARGE seq 5 permit 65001:1:1\n" in text
    assert (
        "bgp extcommunity-list standard RTS seq 5 permit "
        "rt 65001:10 soo 192.0.2.1:7\n" in text
    )


def test_community_alias_line():
    # 'bgp community alias COMMUNITY ALIAS' -- community first
    # (bgp_community_alias_write in bgpd/bgp_community_alias.c).
    root = ProteusBgpFilter()
    alias = Alias(name="cust-gold")
    alias.community.community.global_admin = 65001
    alias.community.community.local_admin = 100
    root.community_alias.append(alias)
    large = Alias(name="site-a")
    large.community.large_community.global_admin = 65001
    large.community.large_community.local_data_1 = 7
    large.community.large_community.local_data_2 = 9
    root.community_alias.append(large)
    text = render_bgp_filters(root)
    assert "bgp community alias 65001:100 cust-gold\n" in text
    assert "bgp community alias 65001:7:9 site-a\n" in text


def test_alias_without_value_raises():
    root = ProteusBgpFilter()
    root.community_alias.append(Alias(name="empty"))
    with pytest.raises(ValueError, match="community value"):
        render_bgp_filters(root)


def test_type_value_mismatch_raises():
    root = ProteusBgpFilter()
    cl = CommunityList(name="BROKEN", type="expanded")
    entry = CommunityList.Entry(sequence=5, action="permit")
    entry.communities.member.append(
        CommunityList.Entry.Communities.Member(global_admin=65001, local_admin=100)
    )
    cl.entry.append(entry)
    root.community_list.append(cl)
    with pytest.raises(ValueError, match="regex"):
        render_bgp_filters(root)
