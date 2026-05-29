"""Project-specific exceptions."""


class SecretaryError(Exception):
    """Base exception for the secretary application."""


class ConnectorError(SecretaryError):
    """Raised when a data connector fails."""


class ConnectorNotConfiguredError(ConnectorError):
    """Raised when a connector is missing required configuration."""


class IngestError(SecretaryError):
    """Raised when memory ingestion fails."""


class ProfileError(SecretaryError):
    """Raised when profile generation fails."""


class AgentError(SecretaryError):
    """Raised when agent chat or skill operations fail."""
