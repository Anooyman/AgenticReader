# scraper/storage/metadata.py
"""Metadata tracking for scraping operations"""
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from scraper.config import ScraperConfig


@dataclass
class ScrapeMetadata:
    """Metadata for a single scrape operation

    Attributes:
        url: URL that was scraped
        timestamp: When the scrape occurred
        status: Status of the scrape (success, error, etc.)
        html_path: Path to saved HTML file
        json_path: Path to saved JSON file
        image_paths: List of paths to saved images (optional)
        error: Error message if scrape failed (optional)
    """
    url: str
    timestamp: datetime
    status: str
    html_path: Path
    json_path: Path
    image_paths: Optional[List[Path]] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to dictionary for JSON serialization

        Returns:
            Dictionary with string representations of paths
            and ISO format timestamp
        """
        return {
            "url": self.url,
            "timestamp": self.timestamp.isoformat(),
            "status": self.status,
            "html_path": str(self.html_path),
            "json_path": str(self.json_path),
            "image_paths": [str(p) for p in self.image_paths] if self.image_paths else None,
            "error": self.error
        }


class MetadataTracker:
    """Tracks scraping operations in JSONL log file

    Appends metadata for each scrape operation to scrape_log.jsonl
    in the base directory. Each line is a JSON object representing
    one scrape operation.
    """

    def __init__(self, config: ScraperConfig):
        """Initialize MetadataTracker with configuration

        Args:
            config: ScraperConfig instance
        """
        self.base_dir = config.base_dir
        self.metadata_file = self.base_dir / "scrape_log.jsonl"

    def log_metadata(self, metadata: ScrapeMetadata) -> None:
        """Append metadata to JSONL log file

        Args:
            metadata: ScrapeMetadata instance to log

        Creates base directory and log file if they don't exist.
        Each metadata entry is written as a single JSON line.
        """
        # Ensure directory exists
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # Convert metadata to dict and write as JSON line
        with self.metadata_file.open('a') as f:
            json_line = json.dumps(metadata.to_dict())
            f.write(json_line + '\n')
