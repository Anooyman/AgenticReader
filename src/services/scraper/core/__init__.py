"""Core scraping functionality"""
from scraper.core.browser import BrowserManager
from scraper.core.extractor import ContentExtractor
from scraper.core.anti_detection import AntiDetectionEngine
from scraper.core.downloader import ResourceDownloader

__all__ = [
    "BrowserManager",
    "ContentExtractor",
    "AntiDetectionEngine",
    "ResourceDownloader",
]
