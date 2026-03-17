"""Custom exception classes for rclone-bisync-manager.

This module defines structured exception types for better error handling and debugging.
All exceptions inherit from BaseRcloneBisyncException as the root exception class.
"""


class BaseRcloneBisyncException(Exception):
    """Base exception class for all rclone-bisync-manager exceptions.

    Attributes:
        message: Human-readable error message
        details: Additional error details (optional)
        context: Additional context information (optional)
    """

    def __init__(self, message: str, details: str = None, context: dict = None):
        self.message = message
        self.details = details
        self.context = context or {}
        super().__init__(self.message)

    def to_dict(self) -> dict:
        """Convert exception to dictionary for JSON serialization."""
        result = {
            "error_type": self.__class__.__name__,
            "message": self.message
        }
        if self.details:
            result["details"] = self.details
        if self.context:
            result["context"] = self.context
        return result


class ConfigError(BaseRcloneBisyncException):
    """Configuration-related errors.

    Raised when configuration is invalid, missing, or cannot be loaded.
    """

    def __init__(self, message: str, details: str = None, context: dict = None):
        super().__init__(message, details, context)


class DaemonError(BaseRcloneBisyncException):
    """Daemon operation errors.

    Raised when daemon operations fail (start, stop, reload, etc.).
    """

    def __init__(self, message: str, details: str = None, context: dict = None):
        super().__init__(message, details, context)


class SyncError(BaseRcloneBisyncException):
    """Synchronization operation errors.

    Raised when sync operations fail (bisync, resync).
    """

    def __init__(self, message: str, details: str = None, context: dict = None):
        super().__init__(message, details, context)


class LockError(BaseRcloneBisyncException):
    """Lock file operation errors.

    Raised when lock file operations fail (create, acquire, release).
    """

    def __init__(self, message: str, details: str = None, context: dict = None):
        super().__init__(message, details, context)


class SocketError(BaseRcloneBisyncException):
    """Socket communication errors.

    Raised when socket operations fail (status server, add-sync socket).
    """

    def __init__(self, message: str, details: str = None, context: dict = None):
        super().__init__(message, details, context)


class ResourceError(BaseRcloneBisyncException):
    """Resource-related errors (file, directory, etc.)."""

    def __init__(self, message: str, details: str = None, context: dict = None):
        super().__init__(message, details, context)


class ValidationError(BaseRcloneBisyncException):
    """Validation errors (e.g., invalid values, constraints)."""

    def __init__(self, message: str, details: str = None, context: dict = None):
        super().__init__(message, details, context)


class NotImplementedError(BaseRcloneBisyncException):
    """Feature not implemented errors."""

    def __init__(self, message: str, details: str = None, context: dict = None):
        super().__init__(message, details, context)
