"""Playwright browser lifecycle and session management module.

Manages startup, page creation, session ownership, and guaranteed cleanup
without retaining persistent credentials or leaking browser processes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Error as PlaywrightError,
    Page,
    Playwright,
    sync_playwright,
)

from browser.browser_exceptions import (
    BrowserCleanupError,
    BrowserNavigationError,
    BrowserStartupError,
)

logger = logging.getLogger("linkedin_automation.browser")


@dataclass
class BrowserConfig:
    """Configuration container for browser sessions."""

    browser_type: str = "chromium"
    channel: Optional[str] = "chrome"
    headless: bool = True
    slow_mo: int = 0
    timeout_ms: int = 30000
    user_data_dir: Optional[Path] = None


class BrowserManager:
    """Manages Playwright browser instance and context lifecycles safely."""

    def __init__(
        self,
        config: Optional[BrowserConfig] = None,
        existing_page: Optional[Page] = None,
        existing_context: Optional[BrowserContext] = None,
    ) -> None:
        """Initialize BrowserManager with explicit config or externally provided context/page.

        If external page/context is provided, this manager will NOT close them on exit.
        """
        self.config = config or BrowserConfig()
        self._external_page = existing_page
        self._external_context = existing_context

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = existing_context
        self._page: Optional[Page] = existing_page

        self.owns_playwright = existing_context is None and existing_page is None
        self.owns_browser = existing_context is None and existing_page is None
        self.owns_context = existing_context is None and existing_page is None
        self.is_active = False

    def start(self) -> Page:
        """Launch browser, establish context and page according to configuration."""
        if self._page is not None and not self._page.is_closed():
            self.is_active = True
            return self._page

        try:
            logger.debug(
                "Starting browser session (type=%s, headless=%s, persistent=%s)",
                self.config.browser_type,
                self.config.headless,
                bool(self.config.user_data_dir),
            )

            if self.owns_playwright and self._playwright is None:
                self._playwright = sync_playwright().start()

            browser_type_launcher = getattr(self._playwright, self.config.browser_type, None)
            if browser_type_launcher is None:
                raise BrowserStartupError(
                    f"Unsupported browser type: '{self.config.browser_type}'. "
                    f"Expected 'chromium', 'firefox', or 'webkit'."
                )

            # Persistent context vs ephemeral browser
            launch_kwargs: dict = {
                "headless": self.config.headless,
                "slow_mo": self.config.slow_mo,
                "timeout": self.config.timeout_ms,
            }
            if self.config.channel:
                launch_kwargs["channel"] = self.config.channel

            if self.config.user_data_dir is not None:
                user_dir = Path(self.config.user_data_dir).resolve()
                user_dir.mkdir(parents=True, exist_ok=True)
                self._context = browser_type_launcher.launch_persistent_context(
                    user_data_dir=str(user_dir),
                    **launch_kwargs,
                )
                self._page = (
                    self._context.pages[0] if self._context.pages else self._context.new_page()
                )
            else:
                self._browser = browser_type_launcher.launch(**launch_kwargs)
                self._context = self._browser.new_context()
                self._page = self._context.new_page()

            self._context.set_default_timeout(self.config.timeout_ms)
            self.is_active = True
            logger.info("Browser session initialized successfully.")
            return self._page

        except Exception as exc:
            logger.error("Failed to start browser session: %s", exc)
            self.close()
            raise BrowserStartupError(f"Browser startup failed: {exc}") from exc

    def navigate(self, url: str) -> None:
        """Navigate active page to URL with safe error handling."""
        if self._page is None or self._page.is_closed():
            raise BrowserNavigationError("Cannot navigate: active page is not open.")

        try:
            logger.debug("Navigating browser to: %s", url)
            self._page.goto(url, timeout=self.config.timeout_ms, wait_until="domcontentloaded")
        except PlaywrightError as exc:
            logger.error("Navigation error navigating to '%s': %s", url, exc)
            raise BrowserNavigationError(f"Failed to navigate to '{url}': {exc}") from exc

    def close(self) -> None:
        """Close browser resources cleanly in a guaranteed finally-safe sequence."""
        errors = []

        # Close owned page
        if self._page is not None and self.owns_context:
            try:
                if not self._page.is_closed():
                    self._page.close()
            except Exception as exc:
                errors.append(f"Error closing page: {exc}")
            finally:
                self._page = None

        # Close owned context (never deletes user_data_dir directory)
        if self._context is not None and self.owns_context:
            try:
                self._context.close()
            except Exception as exc:
                errors.append(f"Error closing context: {exc}")
            finally:
                self._context = None

        # Close owned browser instance
        if self._browser is not None and self.owns_browser:
            try:
                self._browser.close()
            except Exception as exc:
                errors.append(f"Error closing browser: {exc}")
            finally:
                self._browser = None

        # Stop playwright runner
        if self._playwright is not None and self.owns_playwright:
            try:
                self._playwright.stop()
            except Exception as exc:
                errors.append(f"Error stopping playwright: {exc}")
            finally:
                self._playwright = None

        self.is_active = False

        if errors:
            combined = "; ".join(errors)
            logger.warning("Browser cleanup completed with warnings: %s", combined)
            raise BrowserCleanupError(f"Browser cleanup error: {combined}")

        logger.debug("Browser resources released successfully.")

    def __enter__(self) -> Page:
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
