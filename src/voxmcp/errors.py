"""Typed errors shared by the daemon, MCP adapter, and CLI."""


class VoxError(Exception):
    """Base class for user-actionable Vox failures."""


class ConfigurationError(VoxError):
    """The local configuration is invalid or unsafe."""


class PrivacyError(VoxError):
    """An audio action was rejected by the privacy policy."""


class BusyError(VoxError):
    """Another client currently owns the audio engine."""


class ServiceUnavailableError(VoxError):
    """A required local speech service is unavailable."""


class ProtocolError(VoxError):
    """A local daemon protocol message is invalid."""

