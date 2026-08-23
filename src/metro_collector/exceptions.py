class MetroCollectorError(Exception):
    """Base error for expected application failures."""


class CollectorConfigurationError(MetroCollectorError):
    """A collector cannot run because required configuration is missing."""


class SourceAccessError(MetroCollectorError):
    """A source cannot be accessed under the configured collection policy."""


class SourceFormatError(MetroCollectorError):
    """Downloaded source data does not match its expected format."""


class QualityGateError(MetroCollectorError):
    """A staged timetable did not pass activation quality gates."""


class ApiQuotaExceeded(MetroCollectorError):
    """A configured external API request budget has been exhausted."""


class ApiRateLimitBlocked(MetroCollectorError):
    """An external API is temporarily blocked after a rate-limit response."""
