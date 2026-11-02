"""Unit tests for Playwright BrowserManager lifecycle, navigation, and cleanup."""

from pathlib import Path
import pytest
from unittest.mock import MagicMock

from browser.browser_exceptions import (
    BrowserCleanupError,
    BrowserNavigationError,
    BrowserStartupError,
)
from browser.browser_manager import BrowserConfig, BrowserManager


def test_browser_manager_lifecycle():
    """BrowserManager launches headless browser, creates a page, and cleans up completely."""
    config = BrowserConfig(headless=True, browser_type="chromium")
    bm = BrowserManager(config=config)

    page = bm.start()
    assert page is not None
    assert bm.is_active is True
    assert not page.is_closed()

    # Navigate to a safe blank page
    bm.navigate("about:blank")
    assert "about:blank" in page.url

    # Close and verify resources released
    bm.close()
    assert bm.is_active is False
    assert bm._page is None
    assert bm._context is None
    assert bm._browser is None
    assert bm._playwright is None


def test_browser_manager_context_manager():
    """BrowserManager works safely as a context manager with automatic cleanup."""
    config = BrowserConfig(headless=True)
    with BrowserManager(config=config) as page:
        assert page is not None
        assert not page.is_closed()
        page.goto("about:blank")

    # Outside with block, resources must be closed
    assert page.is_closed()


def test_browser_navigation_error_on_invalid_target():
    """Navigation error raises BrowserNavigationError."""
    config = BrowserConfig(headless=True, timeout_ms=1000)
    with BrowserManager(config=config) as page:
        bm = BrowserManager(config=config, existing_page=page)
        with pytest.raises(BrowserNavigationError, match="Failed to navigate"):
            bm.navigate("http://invalid.domain.that.does.not.exist.local")


def test_browser_manager_startup_error():
    """Invalid browser type raises BrowserStartupError."""
    config = BrowserConfig(browser_type="unsupported_engine")
    bm = BrowserManager(config=config)
    with pytest.raises(BrowserStartupError, match="Unsupported browser type"):
        bm.start()
    assert bm.is_active is False


def test_browser_persistent_context_preserves_user_data_dir(tmp_path: Path):
    """Persistent context leaves user_data_dir directory intact upon cleanup."""
    profile_dir = tmp_path / "test_profile"
    config = BrowserConfig(headless=True, user_data_dir=profile_dir)

    with BrowserManager(config=config) as page:
        page.goto("about:blank")

    # Directory must remain intact (not deleted)
    assert profile_dir.exists()
    assert profile_dir.is_dir()


def test_browser_manager_does_not_close_external_page():
    """Externally provided Page/Context is not closed by BrowserManager."""
    mock_external_page = MagicMock()
    mock_external_page.is_closed.return_value = False

    bm = BrowserManager(existing_page=mock_external_page)
    bm.start()
    bm.close()

    # External page close() should NOT have been called
    mock_external_page.close.assert_not_called()

