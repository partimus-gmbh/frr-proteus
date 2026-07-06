from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, TypeAlias

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from frr_proteus.render import render_bgp_instance

# Import statically for type checkers so the deeply-nested binding classes keep
# their real types; at runtime use importorskip so the suite skips cleanly when
# bindings haven't been generated. Both paths bind `bindings` to the same module.
if TYPE_CHECKING:
    from frr_proteus._generated import proteus as bindings
else:
    bindings = pytest.importorskip("frr_proteus._generated.proteus")

# This binding doubles as an annotation *and* is instantiated below
# (`Instance(...)`, `Instance.Neighbor(...)`). `TypeAlias` marks it as an alias
# while keeping a normal assignment, so the value stays callable. A PEP 695
# `type X = ...` can't be used here: a TypeAliasType is neither callable nor
# attribute-accessible.
Instance: TypeAlias = bindings.ProteusBgp.Bgp.Instance


def _new_instance(asn: int | None = 65001, vrf: str = "default") -> Instance:
    instance = Instance(vrf=vrf)
    if asn is not None:
        instance.autonomous_system = asn
    return instance


def _add_neighbor(instance: Instance, addr: str) -> Instance.Neighbor:
    neighbor = Instance.Neighbor(address=addr)
    instance.neighbor.append(neighbor)
    return neighbor


def test_router_bgp_header_and_trailing_bang():
    text = render_bgp_instance(_new_instance())
    assert text.startswith("router bgp 65001\n")
    assert text.endswith("!\n")


def test_autonomous_system_required():
    with pytest.raises(ValueError, match="autonomous-system"):
        render_bgp_instance(_new_instance(asn=None))


def test_router_id_omitted_when_unset():
    assert "router-id" not in render_bgp_instance(_new_instance())


def test_router_id_rendered_when_set():
    instance = _new_instance()
    instance.router_id = "10.0.0.1"
    assert " bgp router-id 10.0.0.1\n" in render_bgp_instance(instance)


@pytest.mark.parametrize(
    "remote_as,expected",
    [
        ("external", "neighbor 192.0.2.1 remote-as external"),
        ("internal", "neighbor 192.0.2.1 remote-as internal"),
        (65099, "neighbor 192.0.2.1 remote-as 65099"),
    ],
)
def test_neighbor_remote_as(remote_as, expected):
    instance = _new_instance()
    _add_neighbor(instance, "192.0.2.1").remote_as = remote_as
    assert expected in render_bgp_instance(instance)


def test_neighbor_without_remote_as_not_rendered():
    # e.g. a peer-group member inheriting remote-as: the session-level
    # remote-as line must simply be absent, not broken.
    instance = _new_instance()
    _add_neighbor(instance, "192.0.2.1")
    assert "remote-as" not in render_bgp_instance(instance)


def test_network_statement_under_address_family():
    instance = _new_instance()
    instance.afi_safis.ipv4_unicast.network.append(
        Instance.AfiSafis.Ipv4Unicast.Network(prefix="192.0.2.0/24")
    )

    text = render_bgp_instance(instance)
    assert " address-family ipv4 unicast\n" in text
    assert "  network 192.0.2.0/24\n" in text
    assert " exit-address-family\n" in text
    # bgpd's vty_frame(" !\n address-family ...") only flushes once the
    # block has content -- so a non-empty AF block is preceded by " !".
    assert " !\n address-family ipv4 unicast\n" in text


def test_ipv6_network_statement():
    instance = _new_instance()
    instance.afi_safis.ipv6_unicast.network.append(
        Instance.AfiSafis.Ipv6Unicast.Network(prefix="2001:db8::/48")
    )

    text = render_bgp_instance(instance)
    assert " !\n address-family ipv6 unicast\n" in text
    assert "  network 2001:db8::/48\n" in text


def test_address_family_omitted_when_no_networks():
    assert "address-family" not in render_bgp_instance(_new_instance())


def test_vrf_clause():
    text = render_bgp_instance(_new_instance(vrf="RED"))
    assert text.startswith("router bgp 65001 vrf RED\n")


def test_default_vrf_has_no_vrf_clause():
    text = render_bgp_instance(_new_instance(vrf="default"))
    assert text.startswith("router bgp 65001\n")


# --- instance-level knobs (bgp_config_write in bgpd/bgp_vty.c) ---


def test_no_bgp_default_ipv4_unicast_only_negative_form():
    instance = _new_instance()
    instance.default.ipv4_unicast = False
    assert " no bgp default ipv4-unicast\n" in render_bgp_instance(instance)
    # True is FRR's default and is never written back.
    instance.default.ipv4_unicast = True
    assert "bgp default ipv4-unicast" not in render_bgp_instance(instance)


def test_bgp_default_other_families_positive_form():
    instance = _new_instance()
    instance.default.ipv6_unicast = True
    assert " bgp default ipv6-unicast\n" in render_bgp_instance(instance)


def test_deterministic_med_three_valued():
    instance = _new_instance()
    assert "deterministic-med" not in render_bgp_instance(instance)
    instance.deterministic_med = True
    assert " bgp deterministic-med\n" in render_bgp_instance(instance)
    instance.deterministic_med = False
    assert " no bgp deterministic-med\n" in render_bgp_instance(instance)


def test_graceful_restart_modes():
    instance = _new_instance()
    instance.graceful_restart.mode = "disable"
    assert " bgp graceful-restart-disable\n" in render_bgp_instance(instance)
    instance.graceful_restart.mode = "restarter"
    assert " bgp graceful-restart\n" in render_bgp_instance(instance)


def test_bestpath_multipath_relax_and_as_set():
    instance = _new_instance()
    instance.bestpath.as_path_multipath_relax.enabled = True
    text = render_bgp_instance(instance)
    assert " bgp bestpath as-path multipath-relax\n" in text
    instance.bestpath.as_path_multipath_relax.as_set = True
    text = render_bgp_instance(instance)
    assert " bgp bestpath as-path multipath-relax as-set\n" in text


# --- peer-groups and session-level neighbor lines
#     (bgp_config_write_peer_global in bgpd/bgp_vty.c) ---


def _new_peer_group(instance: Instance, name: str) -> Instance.PeerGroup:
    group = Instance.PeerGroup(name=name)
    instance.peer_group.append(group)
    return group


def test_peer_group_declaration_before_neighbors():
    instance = _new_instance()
    _new_peer_group(instance, "SPINES")
    _add_neighbor(instance, "192.0.2.1").peer_group = "SPINES"
    text = render_bgp_instance(instance)
    declaration = text.index(" neighbor SPINES peer-group\n")
    membership = text.index(" neighbor 192.0.2.1 peer-group SPINES\n")
    assert declaration < membership


def test_session_lines_in_peer_global_order():
    instance = _new_instance()
    group = _new_peer_group(instance, "PEERS")
    group.description = "ix peers"
    group.bfd.enabled = True
    group.password = "s3cret"
    group.ebgp_multihop = 3
    group.update_source = "192.0.2.99"
    text = render_bgp_instance(instance)
    lines = [
        " neighbor PEERS peer-group\n",
        " neighbor PEERS description ix peers\n",
        " neighbor PEERS bfd\n",
        " neighbor PEERS password s3cret\n",
        " neighbor PEERS ebgp-multihop 3\n",
        " neighbor PEERS update-source 192.0.2.99\n",
    ]
    positions = [text.index(line) for line in lines]
    assert positions == sorted(positions)


def test_ebgp_multihop_255_renders_bare():
    instance = _new_instance()
    neighbor = _add_neighbor(instance, "192.0.2.1")
    neighbor.remote_as = "external"
    neighbor.ebgp_multihop = 255
    assert " neighbor 192.0.2.1 ebgp-multihop\n" in render_bgp_instance(
        instance
    )


def test_ttl_security_and_timers():
    instance = _new_instance()
    neighbor = _add_neighbor(instance, "192.0.2.1")
    neighbor.remote_as = "external"
    neighbor.ttl_security_hops = 1
    neighbor.timers.keepalive = 10
    neighbor.timers.holdtime = 30
    text = render_bgp_instance(instance)
    assert " neighbor 192.0.2.1 ttl-security hops 1\n" in text
    assert " neighbor 192.0.2.1 timers 10 30\n" in text


def test_interface_peer_v6only_with_peer_group_on_one_line():
    instance = _new_instance()
    _new_peer_group(instance, "UNDERLAY")
    neighbor = _add_neighbor(instance, "swp1")
    neighbor.interface_peer = True
    neighbor.v6only = True
    neighbor.peer_group = "UNDERLAY"
    neighbor.remote_as = 65002
    text = render_bgp_instance(instance)
    # peer-group rides on the interface line; remote-as gets its own.
    assert " neighbor swp1 interface v6only peer-group UNDERLAY\n" in text
    assert " neighbor swp1 remote-as 65002\n" in text
    assert " neighbor swp1 peer-group UNDERLAY\n" not in text


def test_interface_peer_without_group():
    instance = _new_instance()
    neighbor = _add_neighbor(instance, "swp1")
    neighbor.interface_peer = True
    neighbor.remote_as = "external"
    text = render_bgp_instance(instance)
    assert " neighbor swp1 interface\n" in text
    assert " neighbor swp1 remote-as external\n" in text


# --- per-AF neighbor lines (bgp_config_write_peer_af) ---


def test_af_activate_three_valued():
    instance = _new_instance()
    neighbor = _add_neighbor(instance, "192.0.2.1")
    neighbor.remote_as = "external"
    assert "activate" not in render_bgp_instance(instance)
    neighbor.afi_safis.ipv4_unicast.activate = True
    assert "  neighbor 192.0.2.1 activate\n" in render_bgp_instance(instance)
    neighbor.afi_safis.ipv4_unicast.activate = False
    assert "  no neighbor 192.0.2.1 activate\n" in render_bgp_instance(
        instance
    )


def test_af_lines_render_for_peer_groups_too():
    instance = _new_instance()
    group = _new_peer_group(instance, "PEERS")
    af = group.afi_safis.ipv4_unicast
    af.activate = True
    af.soft_reconfiguration_inbound = True
    af.filters.route_map_in = None  # leafref left unset on purpose
    text = render_bgp_instance(instance)
    assert " !\n address-family ipv4 unicast\n" in text
    assert "  neighbor PEERS activate\n" in text
    assert "  neighbor PEERS soft-reconfiguration inbound\n" in text


def test_af_policy_lines_in_peer_af_order():
    instance = _new_instance()
    neighbor = _add_neighbor(instance, "192.0.2.1")
    neighbor.remote_as = "internal"
    af = neighbor.afi_safis.ipv4_unicast
    af.activate = True
    af.route_reflector_client = True
    af.next_hop_self.enabled = True
    af.remove_private_as = "all-replace-as"
    af.soft_reconfiguration_inbound = True
    af.maximum_prefix.count = 1000
    af.maximum_prefix.restart_interval = 30
    af.allowas_in.enabled = True
    af.allowas_in.count = 2
    af.weight = 100
    af.filters.route_map_in = None
    text = render_bgp_instance(instance)
    lines = [
        "  neighbor 192.0.2.1 activate\n",
        "  neighbor 192.0.2.1 route-reflector-client\n",
        "  neighbor 192.0.2.1 next-hop-self\n",
        "  neighbor 192.0.2.1 remove-private-AS all replace-AS\n",
        "  neighbor 192.0.2.1 soft-reconfiguration inbound\n",
        "  neighbor 192.0.2.1 maximum-prefix 1000 restart 30\n",
        "  neighbor 192.0.2.1 allowas-in 2\n",
        "  neighbor 192.0.2.1 weight 100\n",
    ]
    positions = [text.index(line) for line in lines]
    assert positions == sorted(positions)


def test_send_community_negations():
    instance = _new_instance()
    neighbor = _add_neighbor(instance, "192.0.2.1")
    neighbor.remote_as = "external"
    af = neighbor.afi_safis.ipv4_unicast
    af.send_community.large = False
    text = render_bgp_instance(instance)
    assert "  no neighbor 192.0.2.1 send-community large\n" in text
    af.send_community.standard = False
    af.send_community.extended = False
    text = render_bgp_instance(instance)
    assert "  no neighbor 192.0.2.1 send-community all\n" in text
    assert "send-community large\n  " not in text


def test_enforce_first_as_three_valued():
    instance = _new_instance()
    neighbor = _add_neighbor(instance, "192.0.2.1")
    neighbor.remote_as = "external"
    assert "enforce-first-as" not in render_bgp_instance(instance)
    neighbor.enforce_first_as = False
    assert " no neighbor 192.0.2.1 enforce-first-as\n" in render_bgp_instance(
        instance
    )
    neighbor.enforce_first_as = True
    assert " neighbor 192.0.2.1 enforce-first-as\n" in render_bgp_instance(
        instance
    )


def test_attribute_unchanged_combined_line():
    instance = _new_instance()
    neighbor = _add_neighbor(instance, "192.0.2.1")
    neighbor.remote_as = "external"
    af = neighbor.afi_safis.ipv4_unicast
    af.attribute_unchanged.next_hop = True
    text = render_bgp_instance(instance)
    assert "  neighbor 192.0.2.1 attribute-unchanged next-hop\n" in text
    af.attribute_unchanged.as_path = True
    af.attribute_unchanged.med = True
    text = render_bgp_instance(instance)
    assert (
        "  neighbor 192.0.2.1 attribute-unchanged as-path next-hop med\n"
        in text
    )


# --- session-level vocabulary added with the parity pass
#     (bgp_config_write_peer_global in bgpd/bgp_vty.c) ---


def test_local_as_with_options():
    instance = _new_instance()
    neighbor = _add_neighbor(instance, "192.0.2.1")
    neighbor.remote_as = "external"
    neighbor.local_as.as_ = 65100
    text = render_bgp_instance(instance)
    assert " neighbor 192.0.2.1 local-as 65100\n" in text
    neighbor.local_as.no_prepend = True
    neighbor.local_as.replace_as = True
    neighbor.local_as.dual_as = True
    text = render_bgp_instance(instance)
    assert (
        " neighbor 192.0.2.1 local-as 65100 no-prepend replace-as dual-as\n"
        in text
    )


def test_shutdown_plain_message_and_rtt():
    instance = _new_instance()
    neighbor = _add_neighbor(instance, "192.0.2.1")
    neighbor.remote_as = "external"
    neighbor.shutdown.enabled = True
    assert " neighbor 192.0.2.1 shutdown\n" in render_bgp_instance(instance)
    neighbor.shutdown.message = "maintenance window"
    assert (
        " neighbor 192.0.2.1 shutdown message maintenance window\n"
        in render_bgp_instance(instance)
    )
    neighbor.shutdown.rtt.threshold = 300
    text = render_bgp_instance(instance)
    assert " neighbor 192.0.2.1 shutdown rtt 300\n" in text
    neighbor.shutdown.rtt.count = 5
    text = render_bgp_instance(instance)
    assert " neighbor 192.0.2.1 shutdown rtt 300 count 5\n" in text


def test_session_scalar_flags_and_values():
    instance = _new_instance()
    neighbor = _add_neighbor(instance, "192.0.2.1")
    neighbor.remote_as = "external"
    neighbor.solo = True
    neighbor.port = 1179
    neighbor.tcp_mss = 1360
    neighbor.aigp = True
    neighbor.graceful_shutdown = True
    neighbor.oad = True
    neighbor.disable_connected_check = True
    neighbor.ip_transparent = True
    neighbor.timers.delayopen = 20
    text = render_bgp_instance(instance)
    assert " neighbor 192.0.2.1 solo\n" in text
    assert " neighbor 192.0.2.1 port 1179\n" in text
    assert " neighbor 192.0.2.1 tcp-mss 1360\n" in text
    assert " neighbor 192.0.2.1 aigp\n" in text
    assert " neighbor 192.0.2.1 graceful-shutdown\n" in text
    assert " neighbor 192.0.2.1 oad\n" in text
    assert " neighbor 192.0.2.1 disable-connected-check\n" in text
    assert " neighbor 192.0.2.1 ip-transparent\n" in text
    assert " neighbor 192.0.2.1 timers delayopen 20\n" in text


def test_local_role_with_strict_mode():
    instance = _new_instance()
    neighbor = _add_neighbor(instance, "192.0.2.1")
    neighbor.remote_as = "external"
    neighbor.local_role.role = "rs-client"
    text = render_bgp_instance(instance)
    assert " neighbor 192.0.2.1 local-role rs-client\n" in text
    neighbor.local_role.strict_mode = True
    text = render_bgp_instance(instance)
    assert " neighbor 192.0.2.1 local-role rs-client strict-mode\n" in text


def test_capabilities_three_valued_and_negations():
    instance = _new_instance()
    neighbor = _add_neighbor(instance, "192.0.2.1")
    neighbor.remote_as = "external"
    assert "capability" not in render_bgp_instance(instance)
    neighbor.capabilities.dynamic = True
    neighbor.capabilities.extended_nexthop = False
    neighbor.capabilities.software_version = True
    neighbor.capabilities.software_version_latest_encoding = False
    neighbor.capabilities.link_local = False
    neighbor.capabilities.fqdn = False
    neighbor.capabilities.dont_capability_negotiate = True
    neighbor.capabilities.override_capability = True
    neighbor.capabilities.strict_capability_match = True
    text = render_bgp_instance(instance)
    assert " neighbor 192.0.2.1 capability dynamic\n" in text
    assert " no neighbor 192.0.2.1 capability extended-nexthop\n" in text
    assert " neighbor 192.0.2.1 capability software-version\n" in text
    assert (
        " no neighbor 192.0.2.1 capability software-version latest-encoding\n"
        in text
    )
    assert " no neighbor 192.0.2.1 capability link-local\n" in text
    assert " no neighbor 192.0.2.1 capability fqdn\n" in text
    assert " neighbor 192.0.2.1 dont-capability-negotiate\n" in text
    assert " neighbor 192.0.2.1 override-capability\n" in text
    assert " neighbor 192.0.2.1 strict-capability-match\n" in text


def test_path_attribute_lists_space_joined():
    instance = _new_instance()
    neighbor = _add_neighbor(instance, "192.0.2.1")
    neighbor.remote_as = "external"
    neighbor.path_attribute_discard = [17, 28]
    neighbor.path_attribute_treat_as_withdraw = [21]
    text = render_bgp_instance(instance)
    assert " neighbor 192.0.2.1 path-attribute discard 17 28\n" in text
    assert " neighbor 192.0.2.1 path-attribute treat-as-withdraw 21\n" in text


def test_per_neighbor_graceful_restart_modes():
    instance = _new_instance()
    neighbor = _add_neighbor(instance, "192.0.2.1")
    neighbor.remote_as = "external"
    neighbor.graceful_restart_mode = "helper"
    assert " neighbor 192.0.2.1 graceful-restart-helper\n" in (
        render_bgp_instance(instance)
    )
    neighbor.graceful_restart_mode = "restarter"
    assert " neighbor 192.0.2.1 graceful-restart\n" in render_bgp_instance(
        instance
    )
    neighbor.graceful_restart_mode = "disable"
    assert " neighbor 192.0.2.1 graceful-restart-disable\n" in (
        render_bgp_instance(instance)
    )


def test_misc_session_flags():
    instance = _new_instance()
    neighbor = _add_neighbor(instance, "192.0.2.1")
    neighbor.remote_as = "external"
    neighbor.rpki_strict = True
    neighbor.sender_as_path_loop_detection = True
    neighbor.send_nexthop_characteristics = True
    neighbor.disable_link_bw_encoding_ieee = True
    neighbor.extended_link_bandwidth = True
    neighbor.extended_optional_parameters = True
    text = render_bgp_instance(instance)
    assert " neighbor 192.0.2.1 rpki strict\n" in text
    assert " neighbor 192.0.2.1 sender-as-path-loop-detection\n" in text
    assert " neighbor 192.0.2.1 send-nexthop-characteristics\n" in text
    assert " neighbor 192.0.2.1 disable-link-bw-encoding-ieee\n" in text
    assert " neighbor 192.0.2.1 extended-link-bandwidth\n" in text
    assert " neighbor 192.0.2.1 extended-optional-parameters\n" in text


# --- per-AF vocabulary added with the parity pass
#     (bgp_config_write_peer_af / bgp_config_write_peer_damp) ---


def test_addpath_variants():
    instance = _new_instance()
    neighbor = _add_neighbor(instance, "192.0.2.1")
    neighbor.remote_as = "external"
    af = neighbor.afi_safis.ipv4_unicast
    af.addpath.tx = "all-paths"
    assert "  neighbor 192.0.2.1 addpath-tx-all-paths\n" in (
        render_bgp_instance(instance)
    )
    af.addpath.tx = "best-per-as"
    assert "  neighbor 192.0.2.1 addpath-tx-bestpath-per-AS\n" in (
        render_bgp_instance(instance)
    )
    af.addpath.tx = "best-selected"
    af.addpath.tx_best_selected = 3
    assert "  neighbor 192.0.2.1 addpath-tx-best-selected 3\n" in (
        render_bgp_instance(instance)
    )
    af.addpath.disable_rx = True
    af.addpath.rx_paths_limit = 10
    text = render_bgp_instance(instance)
    assert "  neighbor 192.0.2.1 disable-addpath-rx\n" in text
    assert "  neighbor 192.0.2.1 addpath-rx-paths-limit 10\n" in text


def test_orf_and_route_server_client_and_nexthop_local():
    instance = _new_instance()
    neighbor = _add_neighbor(instance, "192.0.2.1")
    neighbor.remote_as = "external"
    af = neighbor.afi_safis.ipv4_unicast
    af.orf_prefix_list = "both"
    af.route_server_client = True
    af.nexthop_local_unchanged = True
    text = render_bgp_instance(instance)
    assert "  neighbor 192.0.2.1 capability orf prefix-list both\n" in text
    assert "  neighbor 192.0.2.1 route-server-client\n" in text
    assert "  neighbor 192.0.2.1 nexthop-local unchanged\n" in text


def test_accept_own_and_soo():
    instance = _new_instance()
    neighbor = _add_neighbor(instance, "192.0.2.1")
    neighbor.remote_as = "external"
    af = neighbor.afi_safis.ipv4_unicast
    af.accept_own = True
    af.soo.as2.global_admin = 65001
    af.soo.as2.local_admin = 42
    text = render_bgp_instance(instance)
    assert "  neighbor 192.0.2.1 accept-own\n" in text
    assert "  neighbor 192.0.2.1 soo 65001:42\n" in text


def test_neighbor_dampening_forms():
    instance = _new_instance()
    neighbor = _add_neighbor(instance, "192.0.2.1")
    neighbor.remote_as = "external"
    af = neighbor.afi_safis.ipv4_unicast
    af.dampening.enabled = True
    assert "  neighbor 192.0.2.1 dampening\n" in render_bgp_instance(instance)
    af.dampening.half_life = 20
    assert "  neighbor 192.0.2.1 dampening 20\n" in render_bgp_instance(
        instance
    )
    af.dampening.reuse_threshold = 700
    af.dampening.suppress_threshold = 1500
    af.dampening.max_suppress_time = 60
    assert (
        "  neighbor 192.0.2.1 dampening 20 700 1500 60\n"
        in render_bgp_instance(instance)
    )


# --- instance-level knobs added with the parity pass ---


def test_view_instance_header():
    instance = _new_instance(vrf="LOOKINGGLASS")
    instance.instance_type = "view"
    text = render_bgp_instance(instance)
    assert text.startswith("router bgp 65001 view LOOKINGGLASS\n")


def test_negative_only_instance_knobs():
    instance = _new_instance()
    instance.fast_external_failover = False
    instance.reject_as_sets = False
    instance.client_to_client_reflection = False
    text = render_bgp_instance(instance)
    assert " no bgp fast-external-failover\n" in text
    assert " no bgp reject-as-sets\n" in text
    assert " no bgp client-to-client reflection\n" in text


def test_three_valued_instance_knobs():
    instance = _new_instance()
    text = render_bgp_instance(instance)
    for token in (
        "log-neighbor-changes",
        "ebgp-requires-policy",
        "suppress-duplicates",
        "network import-check",
    ):
        assert token not in text
    instance.log_neighbor_changes = True
    instance.ebgp_requires_policy = False
    instance.enforce_first_as = False
    instance.suppress_duplicates = True
    instance.hard_administrative_reset = False
    instance.network_import_check = True
    text = render_bgp_instance(instance)
    assert " bgp log-neighbor-changes\n" in text
    assert " no bgp ebgp-requires-policy\n" in text
    assert " no bgp enforce-first-as\n" in text
    assert " bgp suppress-duplicates\n" in text
    assert " no bgp hard-administrative-reset\n" in text
    assert " bgp network import-check\n" in text


def test_cluster_id_confederation_and_listen():
    instance = _new_instance()
    instance.cluster_id = "10.0.0.1"
    instance.confederation.identifier = 64999
    instance.confederation.peers = [65010, 65011]
    instance.listen_limit = 100
    group = _new_peer_group(instance, "DYN")
    group.listen_range = ["192.0.2.0/24", "2001:db8::/48"]
    text = render_bgp_instance(instance)
    assert " bgp cluster-id 10.0.0.1\n" in text
    assert " bgp confederation identifier 64999\n" in text
    assert " bgp confederation peers 65010 65011\n" in text
    assert " bgp listen limit 100\n" in text
    assert " bgp listen range 192.0.2.0/24 peer-group DYN\n" in text
    assert " bgp listen range 2001:db8::/48 peer-group DYN\n" in text


def test_update_delay_and_max_med_and_quanta():
    instance = _new_instance()
    instance.update_delay.delay = 120
    instance.max_med.on_startup.period = 90
    instance.max_med.administrative.enabled = True
    instance.write_quanta = 32
    instance.read_quanta = 5
    instance.coalesce_time = 1100
    text = render_bgp_instance(instance)
    assert " update-delay 120\n" in text
    assert " bgp max-med on-startup 90\n" in text
    assert " bgp max-med administrative\n" in text
    assert " write-quanta 32\n" in text
    assert " read-quanta 5\n" in text
    assert " coalesce-time 1100\n" in text
    instance.update_delay.establish_wait = 60
    instance.max_med.on_startup.med = 65500
    instance.max_med.administrative.med = 4000000000
    text = render_bgp_instance(instance)
    assert " update-delay 120 60\n" in text
    assert " bgp max-med on-startup 90 65500\n" in text
    assert " bgp max-med administrative 4000000000\n" in text


def test_graceful_restart_detail_knobs_and_tcp_keepalive():
    instance = _new_instance()
    instance.graceful_restart.stalepath_time = 400
    instance.graceful_restart.restart_time = 200
    instance.graceful_restart.notification = False
    instance.graceful_restart.select_defer_time = 90
    instance.graceful_restart.preserve_fw_state = True
    instance.graceful_restart.rib_stale_time = 500
    instance.long_lived_graceful_restart_stale_time = 3600
    instance.tcp_keepalive.idle = 10
    instance.tcp_keepalive.interval = 5
    instance.tcp_keepalive.probes = 3
    text = render_bgp_instance(instance)
    assert " bgp graceful-restart stalepath-time 400\n" in text
    assert " bgp graceful-restart restart-time 200\n" in text
    assert " no bgp graceful-restart notification\n" in text
    assert " bgp graceful-restart select-defer-time 90\n" in text
    assert " bgp graceful-restart preserve-fw-state\n" in text
    assert " bgp graceful-restart rib-stale-time 500\n" in text
    assert " bgp long-lived-graceful-restart stale-time 3600\n" in text
    assert " bgp tcp-keepalive 10 5 3\n" in text


def test_bestpath_extras_and_labeled_unicast_null():
    instance = _new_instance()
    instance.bestpath.as_path_ignore = True
    instance.bestpath.as_path_confed = True
    instance.bestpath.use_imported_attributes = True
    instance.bestpath.aigp = True
    instance.bestpath.med.confed = True
    instance.bestpath.med.missing_as_worst = True
    instance.bestpath.peer_type_multipath_relax = True
    instance.bestpath.bandwidth = "skip-missing"
    instance.route_reflector_allow_outbound_policy = True
    instance.labeled_unicast_explicit_null = "both"
    text = render_bgp_instance(instance)
    assert " bgp bestpath as-path ignore\n" in text
    assert " bgp bestpath as-path confed\n" in text
    assert " bgp bestpath use-imported-attributes\n" in text
    assert " bgp bestpath aigp\n" in text
    assert " bgp bestpath med confed missing-as-worst\n" in text
    assert " bgp bestpath peer-type multipath-relax\n" in text
    assert " bgp bestpath bandwidth skip-missing\n" in text
    assert " bgp route-reflector allow-outbound-policy\n" in text
    assert " bgp labeled-unicast explicit-null\n" in text
    instance.labeled_unicast_explicit_null = "ipv4"
    assert " bgp labeled-unicast ipv4-explicit-null\n" in (
        render_bgp_instance(instance)
    )


def test_instance_timers_and_defaults_block():
    instance = _new_instance()
    instance.timers.keepalive = 20
    instance.timers.holdtime = 60
    instance.timers.minimum_holdtime = 15
    instance.timers.conditional_advertisement = 30
    instance.timers.default_originate = 10
    instance.default.local_preference = 200
    instance.default.show_hostname = True
    instance.default.dynamic_capability = False
    instance.default.subgroup_pkt_queue_max = 60
    text = render_bgp_instance(instance)
    assert " timers bgp 20 60\n" in text
    assert " bgp minimum-holdtime 15\n" in text
    assert " bgp conditional-advertisement timer 30\n" in text
    assert " bgp default-originate timer 10\n" in text
    assert " bgp default local-preference 200\n" in text
    assert " bgp default show-hostname\n" in text
    assert " no bgp default dynamic-capability\n" in text
    assert " bgp default subgroup-pkt-queue-max 60\n" in text


def test_instance_shutdown_knobs_after_neighbors():
    instance = _new_instance()
    neighbor = _add_neighbor(instance, "192.0.2.1")
    neighbor.remote_as = "external"
    instance.default.shutdown = True
    instance.shutdown = True
    instance.allow_martian_nexthop = True
    instance.fast_convergence = True
    instance.suppress_fib_pending.enabled = True
    text = render_bgp_instance(instance)
    assert " bgp suppress-fib-pending\n" in text
    # 'bgp default shutdown' must come after all peer configuration
    # (bgp_config_write, issue #2286).
    assert text.index(" neighbor 192.0.2.1 remote-as external\n") < text.index(
        " bgp default shutdown\n"
    )
    assert " bgp shutdown\n" in text
    assert " bgp allow-martian-nexthop\n" in text
    assert " bgp fast-convergence\n" in text
    instance.suppress_fib_pending.advertisement_delay = 2000
    assert " bgp suppress-fib-pending 2000\n" in render_bgp_instance(instance)


# --- instance per-AF groupings (bgp_config_write_family et al.) ---


def test_network_options_and_backdoor():
    instance = _new_instance()
    instance.afi_safis.ipv4_unicast.network.append(
        Instance.AfiSafis.Ipv4Unicast.Network(
            prefix="192.0.2.0/24",
            label_index=10,
            backdoor=True,
        )
    )
    text = render_bgp_instance(instance)
    assert "  network 192.0.2.0/24 label-index 10 backdoor\n" in text


def test_aggregate_address_full_options():
    instance = _new_instance()
    instance.afi_safis.ipv4_unicast.aggregate_address.append(
        Instance.AfiSafis.Ipv4Unicast.AggregateAddress(
            prefix="10.0.0.0/8",
            as_set=True,
            summary_only=True,
            origin="igp",
            matching_med_only=True,
        )
    )
    text = render_bgp_instance(instance)
    assert (
        "  aggregate-address 10.0.0.0/8 as-set summary-only origin igp"
        " matching-MED-only\n" in text
    )


def test_redistribute_with_instance_metric():
    instance = _new_instance()
    af = instance.afi_safis.ipv4_unicast
    af.redistribute.append(
        Instance.AfiSafis.Ipv4Unicast.Redistribute(
            protocol="connected", instance=0
        )
    )
    af.redistribute.append(
        Instance.AfiSafis.Ipv4Unicast.Redistribute(
            protocol="ospf", instance=2, metric=100
        )
    )
    text = render_bgp_instance(instance)
    assert "  redistribute connected\n" in text
    assert "  redistribute ospf 2 metric 100\n" in text


def test_maximum_paths_table_map_and_af_dampening():
    instance = _new_instance()
    af = instance.afi_safis.ipv4_unicast
    af.maximum_paths.ebgp = 8
    af.maximum_paths.ibgp = 4
    af.maximum_paths.ibgp_equal_cluster_length = True
    af.dampening.enabled = True
    af.dampening.half_life = 15
    text = render_bgp_instance(instance)
    assert "  maximum-paths 8\n" in text
    assert "  maximum-paths ibgp 4 equal-cluster-length\n" in text
    assert "  bgp dampening 15\n" in text


def test_distance_admin_and_prefix_overrides():
    instance = _new_instance()
    af = instance.afi_safis.ipv4_unicast
    af.distance.ebgp = 20
    af.distance.ibgp = 200
    af.distance.local = 210
    af.distance.prefix.append(
        Instance.AfiSafis.Ipv4Unicast.Distance.Prefix(
            prefix="192.0.2.0/24", distance=90
        )
    )
    text = render_bgp_instance(instance)
    assert "  distance bgp 20 200 210\n" in text
    assert "  distance 90 192.0.2.0/24\n" in text


def test_vpn_leaking_and_nexthop_prefer_global():
    instance = _new_instance()
    af4 = instance.afi_safis.ipv4_unicast
    af4.export_vpn = True
    af4.import_vpn = True
    af4.import_vrf = ["BLUE", "GREEN"]
    af6 = instance.afi_safis.ipv6_unicast
    af6.nexthop_prefer_global = True
    text = render_bgp_instance(instance)
    assert "  export vpn\n" in text
    assert "  import vpn\n" in text
    assert "  import vrf BLUE\n" in text
    assert "  import vrf GREEN\n" in text
    assert "  nexthop prefer-global\n" in text
    af6.nexthop_prefer_global = False
    assert "  no nexthop prefer-global\n" in render_bgp_instance(instance)


def test_all_eight_af_headers():
    instance = _new_instance()
    headers = {
        "ipv4_multicast": "address-family ipv4 multicast",
        "ipv4_labeled_unicast": "address-family ipv4 labeled-unicast",
        "ipv4_vpn": "address-family ipv4 vpn",
        "ipv6_multicast": "address-family ipv6 multicast",
        "ipv6_labeled_unicast": "address-family ipv6 labeled-unicast",
        "ipv6_vpn": "address-family ipv6 vpn",
    }
    for field in ("ipv4_multicast", "ipv4_labeled_unicast",
                  "ipv6_multicast", "ipv6_labeled_unicast"):
        getattr(instance.afi_safis, field).maximum_paths.ebgp = 2
    instance.afi_safis.ipv4_vpn.maximum_paths.ebgp = 2
    instance.afi_safis.ipv6_vpn.maximum_paths.ebgp = 2
    text = render_bgp_instance(instance)
    for header in headers.values():
        assert f" !\n {header}\n" in text
    # every block closes
    assert text.count(" exit-address-family\n") == 6


def test_neighbor_af_config_reaches_all_families():
    instance = _new_instance()
    neighbor = _add_neighbor(instance, "192.0.2.1")
    neighbor.remote_as = "external"
    neighbor.afi_safis.ipv4_vpn.activate = True
    text = render_bgp_instance(instance)
    assert " !\n address-family ipv4 vpn\n" in text
    assert "  neighbor 192.0.2.1 activate\n" in text


# --- /bgp/process renderer ---


def test_render_bgp_process():
    from frr_proteus.render import render_bgp_process

    process = bindings.ProteusBgp.Bgp.Process()
    assert render_bgp_process(process) == ""
    process.route_map_delay_timer = 30
    process.update_delay.delay = 300
    process.update_delay.establish_wait = 90
    process.suppress_fib_pending.enabled = True
    process.graceful_restart.mode = "restarter"
    process.graceful_restart.preserve_fw_state = True
    process.graceful_shutdown = True
    process.no_rib = True
    process.send_extra_data_zebra = True
    process.ipv6_auto_ra = False
    process.session_dscp = 48
    process.input_queue_limit = 10000
    process.output_queue_limit = 20000
    text = render_bgp_process(process)
    assert "bgp route-map delay-timer 30\n" in text
    assert "bgp update-delay 300 90\n" in text
    assert "bgp suppress-fib-pending\n" in text
    assert "bgp graceful-restart\n" in text
    assert "bgp graceful-restart preserve-fw-state\n" in text
    assert "bgp graceful-shutdown\n" in text
    assert "bgp no-rib\n" in text
    assert "bgp send-extra-data zebra\n" in text
    assert "no bgp ipv6-auto-ra\n" in text
    assert "bgp session-dscp 48\n" in text
    assert "bgp input-queue-limit 10000\n" in text
    assert "bgp output-queue-limit 20000\n" in text
    # top-level lines: no leading space anywhere
    assert not any(line.startswith(" ") for line in text.splitlines())
