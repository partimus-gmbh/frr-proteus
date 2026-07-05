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


def evpn_configured(instance) -> bool:
    """Whether this instance needs an 'address-family l2vpn evpn' block:
    any instance-level EVPN config, or any neighbor with EVPN AF
    config."""
    if has_config(instance.afi_safis.l2vpn_evpn):
        return True
    return any(
        has_config(neighbor.afi_safis.l2vpn_evpn)
        for neighbor in instance.neighbor
    )
