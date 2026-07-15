"""RFC 7952 metadata annotations on the generated bindings: the
annotate()/yang_annotations() API, value validation against the annotation's
YANG type, and the RFC 7952 section 5.2 JSON encoding (metadata objects
under '@' / '@member', always module-qualified annotation names,
null-padded arrays for leaf-list entries)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

if TYPE_CHECKING:
    from frr_proteus._generated import proteus as bindings
else:
    bindings = pytest.importorskip("frr_proteus._generated.proteus")

ProteusBgp = bindings.ProteusBgp
annotate = bindings.annotate
yang_annotations = bindings.annotations


def _instance() -> bindings.ProteusBgp.Instance:
    instance = ProteusBgp.Instance(vrf="default")
    instance.autonomous_system.plain = 65001
    return instance


def test_node_annotation_roundtrip_via_api():
    neighbor = ProteusBgp.Instance.Neighbor(address="192.0.2.1")
    assert yang_annotations(neighbor) == {}
    annotate(neighbor, comment="uplink")
    assert yang_annotations(neighbor) == {"comment": "uplink"}
    annotate(neighbor, comment=None)  # None removes
    assert yang_annotations(neighbor) == {}


def test_leaf_member_and_leaf_list_entry_addressing():
    instance = _instance()
    neighbor = ProteusBgp.Instance.Neighbor(address="192.0.2.1")
    annotate(neighbor, "description", comment="leaf comment")
    assert yang_annotations(neighbor, "description") == {"comment": "leaf comment"}
    assert yang_annotations(neighbor) == {}  # distinct from the node's own

    instance.confederation.peers.plain = [65010, 65020]
    annotate(instance.confederation.peers, "plain", 1, comment="second peer")
    assert yang_annotations(instance.confederation.peers, "plain", 1) == {
        "comment": "second peer"
    }
    assert yang_annotations(instance.confederation.peers, "plain", 0) == {}


def test_unknown_annotation_and_bad_addressing_rejected():
    neighbor = ProteusBgp.Instance.Neighbor(address="192.0.2.1")
    with pytest.raises(ValueError, match="no annotation named 'bogus'"):
        annotate(neighbor, bogus="x")
    with pytest.raises(ValueError, match="no member"):
        annotate(neighbor, "no_such_field", comment="x")
    # container/list members are annotated on the child object itself
    instance = _instance()
    with pytest.raises(ValueError, match="annotate the child object itself"):
        annotate(instance, "timers", comment="x")
    with pytest.raises(ValueError, match="annotate the child object itself"):
        annotate(instance, "neighbor", comment="x")
    # leaf-list entries need an index, leaves must not carry one
    with pytest.raises(ValueError, match="entry index"):
        annotate(instance.confederation.peers, "plain", comment="x")
    with pytest.raises(ValueError, match="leaf"):
        annotate(neighbor, "description", 0, comment="x")


def test_annotation_value_validated_against_yang_type():
    neighbor = ProteusBgp.Instance.Neighbor(address="192.0.2.1")
    with pytest.raises(bindings.YangValidationError):
        annotate(neighbor, comment=42)


def test_rfc7952_json_encoding():
    root = ProteusBgp()
    instance = _instance()
    root.instance.append(instance)
    neighbor = ProteusBgp.Instance.Neighbor(address="192.0.2.1")
    neighbor.description = "foo"
    instance.neighbor.append(neighbor)

    annotate(neighbor, comment="node comment")
    annotate(neighbor, "description", comment="leaf comment")
    instance.confederation.peers.plain = [65010, 65020]
    annotate(instance.confederation.peers, "plain", 1, comment="second peer")

    encoded = bindings.to_ietf_json(root)
    neighbor_json = encoded["proteus-bgp:instance"][0]["neighbor"][0]
    # list entry: metadata object member "@", names always qualified
    assert neighbor_json["@"] == {
        "proteus-configuration-metadata:comment": "node comment"
    }
    # leaf: sibling "@member" object
    assert neighbor_json["@description"] == {
        "proteus-configuration-metadata:comment": "leaf comment"
    }
    # leaf-list: aligned null-padded array, trailing nulls omitted
    peers_json = encoded["proteus-bgp:instance"][0]["confederation"]["peers"]
    assert peers_json["@plain"] == [
        None,
        {"proteus-configuration-metadata:comment": "second peer"},
    ]

    decoded = bindings.from_ietf_json(ProteusBgp, encoded)
    decoded_neighbor = decoded.instance[0].neighbor[0]
    assert yang_annotations(decoded_neighbor) == {"comment": "node comment"}
    assert yang_annotations(decoded_neighbor, "description") == {"comment": "leaf comment"}
    assert yang_annotations(decoded.instance[0].confederation.peers, "plain", 1) == {
        "comment": "second peer"
    }


def test_metadata_on_unset_member_is_dropped_from_json():
    root = ProteusBgp()
    instance = _instance()
    root.instance.append(instance)
    neighbor = ProteusBgp.Instance.Neighbor(address="192.0.2.1")
    instance.neighbor.append(neighbor)
    annotate(neighbor, "description", comment="dangling")  # leaf stays unset
    neighbor_json = bindings.to_ietf_json(root)["proteus-bgp:instance"][0][
        "neighbor"
    ][0]
    assert "@description" not in neighbor_json


def test_unknown_metadata_member_rejected_on_decode():
    data = {
        "proteus-bgp:instance": [
            {
                "vrf": "default",
                "@": {"example-mod:last-modified": "2026-07-06"},
            }
        ]
    }
    with pytest.raises(ValueError, match="unknown metadata annotation"):
        bindings.from_ietf_json(ProteusBgp, data)


def test_annotations_do_not_affect_equality_or_repr_fields():
    a = ProteusBgp.Instance.Neighbor(address="192.0.2.1")
    b = ProteusBgp.Instance.Neighbor(address="192.0.2.1")
    annotate(a, comment="only on a")
    assert a == b
