# scraper/storage/file_manager.py
"""File management for scraped data"""
import json
import re
from pathlib import Path
from typing import Any
from scraper.config import ScraperConfig


class FileManager:
    """Manages file storage for scraped data

    Organizes data into subdirectories:
    - html/: Raw HTML content
    - json/: Structured JSON data
    - images/: Downloaded images
    """

    def __init__(self, config: ScraperConfig):
        """Initialize FileManager with configuration

        Args:
            config: ScraperConfig instance
        """
        self.base_dir = config.base_dir
        self.html_dir = self.base_dir / "html"
        self.json_dir = self.base_dir / "json"
        self.images_dir = self.base_dir / "images"

    def setup_directories(self) -> None:
        """Create directory structure if it doesn't exist

        Creates:
        - base_dir/html/
        - base_dir/json/
        - base_dir/images/

        Safe to call multiple times (idempotent).
        """
        self.html_dir.mkdir(parents=True, exist_ok=True)
        self.json_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)

    def sanitize_filename(self, url: str, max_length: int = 200) -> str:
        """Convert URL to safe filesystem filename

        Args:
            url: URL to convert
            max_length: Maximum filename length (default: 200)

        Returns:
            Sanitized filename safe for all filesystems

        Example:
            >>> sanitize_filename("https://example.com/path?query=value")
            "example.com_path_query_value"
        """
        # Remove protocol (http://, https://)
        filename = re.sub(r'^https?://', '', url)

        # Replace special characters with underscores
        # Keep alphanumeric, dots, hyphens; replace everything else
        filename = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)

        # Collapse multiple underscores into one
        filename = re.sub(r'_+', '_', filename)

        # Strip leading/trailing underscores and dots
        filename = filename.strip('_.')

        # Truncate to max_length
        if len(filename) > max_length:
            filename = filename[:max_length].rstrip('_.')

        return filename

    def save_html(self, url: str, content: str) -> Path:
        """Save HTML content to file

        Args:
            url: Source URL (used for filename)
            content: HTML content to save

        Returns:
            Absolute path to saved file

        Creates html directory if needed.
        Overwrites existing file with same name.
        """
        # Ensure directory exists
        self.html_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename from URL
        filename = self.sanitize_filename(url) + ".html"
        filepath = self.html_dir / filename

        # Write content
        filepath.write_text(content)

        return filepath

    def save_json(self, url: str, data: Any) -> Path:
        """Save structured data as JSON

        Args:
            url: Source URL (used for filename)
            data: Data to serialize as JSON

        Returns:
            Absolute path to saved file

        Creates json directory if needed.
        JSON is pretty-printed with 2-space indentation.
        """
        # Ensure directory exists
        self.json_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename from URL
        filename = self.sanitize_filename(url) + ".json"
        filepath = self.json_dir / filename

        # Write JSON with pretty formatting
        filepath.write_text(json.dumps(data, indent=2))

        return filepath

    def save_image(self, url: str, image_data: bytes) -> Path:
        """Save image binary data with auto-detected extension

        Args:
            url: Source URL (used for filename)
            image_data: Binary image data

        Returns:
            Absolute path to saved file

        Detects image format from magic bytes:
        - PNG: .png
        - JPEG: .jpg
        - GIF: .gif
        - WebP: .webp
        - Unknown: .bin
        """
        # Ensure directory exists
        self.images_dir.mkdir(parents=True, exist_ok=True)

        # Detect file extension from magic bytes
        extension = self._detect_image_extension(image_data)

        # Generate filename from URL
        filename = self.sanitize_filename(url) + extension
        filepath = self.images_dir / filename

        # Write binary data
        filepath.write_bytes(image_data)

        return filepath

    def _detect_image_extension(self, data: bytes) -> str:
        """Detect image format from magic bytes

        Args:
            data: Binary image data

        Returns:
            File extension including dot (e.g., ".png", ".jpg")
        """
        if len(data) < 12:
            return ".bin"

        # PNG: starts with \x89PNG
        if data[:4] == b'\x89PNG':
            return ".png"

        # JPEG: starts with \xff\xd8\xff
        if data[:3] == b'\xff\xd8\xff':
            return ".jpg"

        # GIF: starts with GIF87a or GIF89a
        if data[:6] in (b'GIF87a', b'GIF89a'):
            return ".gif"

        # WebP: RIFF....WEBP
        if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            return ".webp"

        # Unknown format
        return ".bin"
