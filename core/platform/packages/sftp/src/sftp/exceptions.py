"""Centralized SFTP and SSH exceptions."""

from __future__ import annotations


class SftpError(Exception):
    """Base exception for all SFTP infrastructure operations."""


class SftpConnectionError(SftpError):
    """Raised when establishing an SSH or SFTP socket connection fails."""


class SftpAuthenticationError(SftpError):
    """Raised when SSH/SFTP authentication (password or key) fails."""


class SftpHostValidationError(SftpError):
    """Raised when an SFTP destination host fails SSRF or DNS validation."""


class SftpOperationError(SftpError):
    """Raised when remote file manipulation (read, write, delete, list) fails."""
