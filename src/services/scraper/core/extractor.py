"""Content extraction from web pages"""
from playwright.async_api import Page
from typing import Dict, Any, Optional
import json


class ContentExtractor:
    """Extract different types of content from web pages"""

    async def extract_html(self, page: Page) -> str:
        """Extract complete HTML from page

        Args:
            page: Playwright page object

        Returns:
            Complete HTML content as string
        """
        return await page.content()

    async def extract_text(self, page: Page) -> str:
        """Extract visible text content without HTML tags

        Args:
            page: Playwright page object

        Returns:
            Plain text content
        """
        # Use innerText which excludes script/style and returns visible text
        text = await page.evaluate("() => document.body.innerText")
        return text

    async def extract_screenshot(self, page: Page, full_page: bool = True) -> bytes:
        """Take screenshot of page

        Args:
            page: Playwright page object
            full_page: Capture full scrollable page (default: True)

        Returns:
            Screenshot as PNG bytes
        """
        screenshot = await page.screenshot(full_page=full_page, type="png")
        return screenshot

    async def extract_json(self, page: Page) -> Optional[Dict[str, Any]]:
        """Extract JSON data from the page

        Attempts to extract JSON from:
        1. Script tags with type="application/json"
        2. Body content if it's valid JSON
        3. Pre tags containing JSON

        Args:
            page: Playwright page instance

        Returns:
            Parsed JSON data as dictionary, or None if no JSON found
        """
        # Try script tags first
        script_json = await page.evaluate("""
        () => {
            const scripts = document.querySelectorAll('script[type="application/json"]');
            if (scripts.length > 0) {
                return scripts[0].textContent;
            }
            return null;
        }
        """)

        if script_json:
            try:
                return json.loads(script_json)
            except json.JSONDecodeError:
                pass

        # Try pre tags
        pre_content = await page.evaluate("""
        () => {
            const pre = document.querySelector('pre');
            return pre ? pre.textContent : null;
        }
        """)

        if pre_content:
            try:
                return json.loads(pre_content)
            except json.JSONDecodeError:
                pass

        # Try body content
        body_text = await page.evaluate("() => document.body.textContent")
        try:
            return json.loads(body_text.strip())
        except json.JSONDecodeError:
            return None

    async def extract_dynamic_content(
        self, page: Page, wait_for: str, timeout: int = 30000
    ) -> str:
        """Extract content after waiting for dynamic elements to load

        Waits for a specific CSS selector to appear before extracting content.
        Useful for SPAs and pages with dynamic content loading.

        Args:
            page: Playwright page instance
            wait_for: CSS selector to wait for
            timeout: Maximum wait time in milliseconds (default: 30000)

        Returns:
            Extracted text content after element appears
        """
        # Wait for the selector to appear
        await page.wait_for_selector(wait_for, timeout=timeout)

        # Extract text content
        return await self.extract_text(page)
