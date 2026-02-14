# scraper/config/scraper_config.py
"""Configuration dataclass for the web scraper"""
from dataclasses import dataclass, field
from pathlib import Path
from scraper.exceptions import InvalidConfigException


@dataclass
class ScraperConfig:
    """Configuration for web scraping operations

    Attributes:
        base_dir: Base directory for storing scraped data
        timeout: Page load timeout in milliseconds
        headless: Run browser in headless mode
        user_agent: User agent string for requests
        max_retries: Maximum number of retry attempts
        retry_delay: Delay between retries in seconds
    """
    base_dir: Path = field(default_factory=lambda: Path("scraper_data"))
    timeout: int = 30000
    headless: bool = True
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    max_retries: int = 3
    retry_delay: float = 2.0

    def __post_init__(self):
        """Validate configuration values"""
        # Validate timeout
        if self.timeout <= 0:
            raise InvalidConfigException("timeout must be positive")

        # Validate max_retries
        if self.max_retries < 0:
            raise InvalidConfigException("max_retries must be non-negative")

        # Validate retry_delay
        if self.retry_delay <= 0:
            raise InvalidConfigException("retry_delay must be positive")

        # Validate user_agent
        if not self.user_agent or not self.user_agent.strip():
            raise InvalidConfigException("user_agent must be non-empty")

        # Convert base_dir to Path if it's a string
        if isinstance(self.base_dir, str):
            self.base_dir = Path(self.base_dir)
