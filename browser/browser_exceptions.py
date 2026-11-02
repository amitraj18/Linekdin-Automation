"""Exceptions for the browser lifecycle management module."""

from __future__ import annotations


class BrowserManagerError(Exception):
    """Base exception for all browser management operations."""


class BrowserStartupError(BrowserManagerError):
    """Raised when starting the browser or creating a browser context fails."""


class BrowserNavigationError(BrowserManagerError):
    """Raised when navigation to a target page fails."""


class BrowserCleanupError(BrowserManagerError):
    """Raised when cleaning up browser resources fails."""

