"""Core scraping functionality"""
from scraper.core.browser import BrowserManager
from scraper.core.extractor import ContentExtractor
from scraper.core.anti_detection import AntiDetectionEngine
from scraper.core.downloader import ResourceDownloader
from scraper.core.retry import RetryStrategy
from scraper.core.fallback import FallbackHandler

__all__ = [
    "BrowserManager",
    "ContentExtractor",
    "AntiDetectionEngine",
    "ResourceDownloader",
    "RetryStrategy",
    "FallbackHandler",
]
