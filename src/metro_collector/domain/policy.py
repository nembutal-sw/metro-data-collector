from __future__ import annotations

from dataclasses import dataclass

from metro_collector.domain.enums import SourceAccessStatus


@dataclass(frozen=True, slots=True)
class CollectionPolicyInput:
    official_public_source: bool
    robots_disallowed: bool = False
    terms_explicitly_prohibit_collection: bool = False
    requires_access_control_bypass: bool = False
    terms_unspecified: bool = False


def decide_access_status(policy: CollectionPolicyInput) -> SourceAccessStatus:
    """Apply the project policy: unspecified conditions default to enabled."""
    if not policy.official_public_source:
        return SourceAccessStatus.PENDING_REVIEW
    if policy.robots_disallowed:
        return SourceAccessStatus.DISABLED_ROBOTS
    if policy.terms_explicitly_prohibit_collection:
        return SourceAccessStatus.DISABLED_TERMS
    if policy.requires_access_control_bypass:
        return SourceAccessStatus.DISABLED_TECHNICAL
    return SourceAccessStatus.ENABLED
