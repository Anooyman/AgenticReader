"""Browser management for Playwright automation"""
from typing import Optional, List
from playwright.async_api import async_playwright, Browser, BrowserContext
from scraper.config.scraper_config import ScraperConfig
from scraper.core.anti_detection import AntiDetectionEngine


class BrowserManager:
    """Manages Playwright browser instances and context pool

    Attributes:
        max_contexts: Maximum number of concurrent contexts
        browser: Current browser instance
        context_pool: Pool of available contexts
    """

    def __init__(self, max_contexts: int = 3):
        """Initialize BrowserManager

        Args:
            max_contexts: Maximum number of concurrent browser contexts
        """
        self.max_contexts = max_contexts
        self.browser: Optional[Browser] = None
        self.context_pool: List[BrowserContext] = []

    async def launch_browser(self, config: ScraperConfig) -> Browser:
        """Launch browser instance with configuration

        Args:
            config: Scraper configuration

        Returns:
            Browser instance
        """
        if self.browser is not None:
            return self.browser

        playwright = await async_playwright().start()

        launch_options = {
            "headless": config.headless,
        }

        if hasattr(config, 'proxy') and config.proxy:
            launch_options["proxy"] = {"server": config.proxy}

        self.browser = await playwright.chromium.launch(**launch_options)
        self._playwright = playwright

        return self.browser

    async def get_context(self, config: ScraperConfig, use_anti_detection: bool = True) -> BrowserContext:
        """Get browser context from pool or create new one

        Args:
            config: Scraper configuration
            use_anti_detection: Apply anti-detection measures

        Returns:
            Browser context
        """
        # Reuse from pool if available
        if self.context_pool:
            return self.context_pool.pop()

        # Create new context
        if self.browser is None:
            await self.launch_browser(config)

        context_options = {}

        # Apply anti-detection if enabled
        if use_anti_detection:
            anti_detection = AntiDetectionEngine()

            # Use random viewport
            viewport = anti_detection._get_random_viewport()
            context_options["viewport"] = viewport

            # Add realistic headers
            headers = anti_detection.add_realistic_headers()
            context_options["extra_http_headers"] = headers

        if hasattr(config, 'locale') and config.locale:
            context_options["locale"] = config.locale

        if hasattr(config, 'timezone') and config.timezone:
            context_options["timezone_id"] = config.timezone

        if hasattr(config, 'user_agent') and config.user_agent:
            context_options["user_agent"] = config.user_agent

        # Allow config viewport to override if specified
        if hasattr(config, 'viewport') and config.viewport:
            context_options["viewport"] = config.viewport

        context = await self.browser.new_context(**context_options)

        # Set default timeout
        context.set_default_timeout(config.timeout)

        return context

    async def release_context(self, context: BrowserContext) -> None:
        """Return context to pool

        Args:
            context: Context to release
        """
        # Don't exceed max pool size
        if len(self.context_pool) < self.max_contexts:
            self.context_pool.append(context)
        else:
            await context.close()

    async def close_all(self) -> None:
        """Close all contexts and browser"""
        # Close all contexts
        for context in self.context_pool:
            await context.close()
        self.context_pool.clear()

        # Close browser
        if self.browser:
            await self.browser.close()
            self.browser = None

        # Stop playwright
        if hasattr(self, '_playwright'):
            await self._playwright.stop()
