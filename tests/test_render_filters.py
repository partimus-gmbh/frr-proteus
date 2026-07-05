from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, TypeAlias

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from frr_proteus.render import render_filters

if TYPE_CHECKING:
    from frr_proteus._generated import proteus as bindings
else:
    bindings = pytest.importorskip("frr_proteus._generated.proteus")

ProteusFilter: TypeAlias = bindings.ProteusFilter
PrefixList4: TypeAlias = bindings.ProteusFilter.PrefixLists.Ipv4.PrefixList
PrefixList6: TypeAlias = bindings.ProteusFilter.PrefixLists.Ipv6.PrefixList
AccessList4: TypeAlias = bindings.ProteusFilter.AccessLists.Ipv4.AccessList
AccessList6: TypeAlias = bindings.ProteusFilter.AccessLists.Ipv6.AccessList
AccessListMac: TypeAlias = bindings.ProteusFilter.AccessLists.Mac.AccessList


def test_empty_root_renders_nothing():
    assert render_filters(ProteusFilter()) == ""


def test_ipv4_prefix_list_lines():
    root = ProteusFilter()
    pl = PrefixList4(name="LOOPBACKS", description="host routes")
    pl.entry.append(
        PrefixList4.Entry(
            sequence=5, action="permit", prefix="10.0.0.0/8", ge=32, le=32
        )
    )
    pl.entry.append(PrefixList4.Entry(sequence=10, action="deny", any=True))
    root.prefix_lists.ipv4.prefix_list.append(pl)
    text = render_filters(root)
    assert "ip prefix-list LOOPBACKS description host routes\n" in text
    # seq always emitted; ge before le.
    assert "ip prefix-list LOOPBACKS seq 5 permit 10.0.0.0/8 ge 32 le 32\n" in text
    assert "ip prefix-list LOOPBACKS seq 10 deny any\n" in text


def test_ge_zero_is_rendered():
    # ge/le of 0 are valid values and must not be dropped as falsy.
    root = ProteusFilter()
    pl = PrefixList4(name="ZERO")
    pl.entry.append(
        PrefixList4.Entry(sequence=5, action="permit", prefix="0.0.0.0/0", ge=0)
    )
    root.prefix_lists.ipv4.prefix_list.append(pl)
    assert "seq 5 permit 0.0.0.0/0 ge 0\n" in render_filters(root)


def test_ipv6_prefix_list_keyword():
    root = ProteusFilter()
    pl = PrefixList6(name="V6")
    pl.entry.append(
        PrefixList6.Entry(sequence=5, action="permit", prefix="2001:db8::/32")
    )
    root.prefix_lists.ipv6.prefix_list.append(pl)
    assert "ipv6 prefix-list V6 seq 5 permit 2001:db8::/32\n" in render_filters(root)


def test_ipv4_access_list_is_unprefixed():
    # access_list_show() in lib/filter_cli.c writes IPv4 entries with no
    # leading 'ip' keyword.
    root = ProteusFilter()
    acl = AccessList4(name="ALL", remark="everything")
    acl.entry.append(AccessList4.Entry(sequence=5, action="permit", any=True))
    root.access_lists.ipv4.access_list.append(acl)
    text = render_filters(root)
    assert "access-list ALL remark everything\n" in text
    assert "access-list ALL seq 5 permit any\n" in text
    assert "ip access-list" not in text


def test_ipv6_access_list_exact_match():
    root = ProteusFilter()
    acl = AccessList6(name="V6ONLY")
    acl.entry.append(
        AccessList6.Entry(
            sequence=5, action="permit", prefix="2001:db8::/32", exact_match=True
        )
    )
    root.access_lists.ipv6.access_list.append(acl)
    assert (
        "ipv6 access-list V6ONLY seq 5 permit 2001:db8::/32 exact-match\n"
        in render_filters(root)
    )


def test_mac_access_list():
    root = ProteusFilter()
    acl = AccessListMac(name="MACS")
    acl.entry.append(
        AccessListMac.Entry(sequence=5, action="permit", mac="00:11:22:33:44:55")
    )
    acl.entry.append(AccessListMac.Entry(sequence=10, action="deny", any=True))
    root.access_lists.mac.access_list.append(acl)
    text = render_filters(root)
    assert "mac access-list MACS seq 5 permit 00:11:22:33:44:55\n" in text
    assert "mac access-list MACS seq 10 deny any\n" in text
