# scraper/exceptions.py
"""Custom exceptions for the scraper"""


class ScraperException(Exception):
    """Base exception for all scraper errors"""
    pass


class NetworkException(ScraperException):
    """Network-related errors (timeout, connection failure)

    These errors trigger automatic retry with exponential backoff.
    """
    pass


class AntiBotDetection(ScraperException):
    """Anti-bot mechanism detected (Cloudflare, CAPTCHA)

    Triggers strategy enhancement (UA change, stronger anti-detection).
    """
    pass


class ContentNotFoundException(ScraperException):
    """Content not found (selector didn't match)

    Logged but not retried.
    """
    pass


class InvalidConfigException(ScraperException):
    """Configuration error

    Fails immediately without retry.
    """
    pass
