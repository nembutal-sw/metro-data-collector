from metro_collector.domain.enums import SourceAccessStatus
from metro_collector.domain.policy import CollectionPolicyInput, decide_access_status


def test_unspecified_terms_on_official_public_page_default_to_enabled() -> None:
    result = decide_access_status(
        CollectionPolicyInput(official_public_source=True, terms_unspecified=True)
    )
    assert result is SourceAccessStatus.ENABLED


def test_explicit_robots_block_wins_over_unspecified_terms() -> None:
    result = decide_access_status(
        CollectionPolicyInput(
            official_public_source=True,
            terms_unspecified=True,
            robots_disallowed=True,
        )
    )
    assert result is SourceAccessStatus.DISABLED_ROBOTS


def test_access_control_bypass_is_disabled() -> None:
    result = decide_access_status(
        CollectionPolicyInput(
            official_public_source=True,
            requires_access_control_bypass=True,
        )
    )
    assert result is SourceAccessStatus.DISABLED_TECHNICAL
