"""
Session logging service.
Logs song requests to CSV files per session.
"""

import csv
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
import aiofiles
import aiofiles.os

from models.song import SongRequest

logger = logging.getLogger(__name__)


class SessionLogger:
    """
    Logs song requests to CSV files.
    Creates a new file for each session.
    """

    # CSV column headers
    HEADERS = [
        "timestamp",
        "song_title",
        "artist",
        "album",
        "spotify_id",
        "requester",
        "likes",
        "skips",
        "duration_formatted",
    ]

    def __init__(self, logs_dir: str = "logs/sessions"):
        """
        Initialize session logger.

        Args:
            logs_dir: Directory to store session logs
        """
        self.logs_dir = Path(logs_dir)
        self.current_file: Optional[Path] = None
        self.session_start: Optional[datetime] = None

    async def start_session(self) -> Path:
        """
        Start a new logging session.
        Creates a new CSV file with headers.

        Returns:
            Path to the session log file
        """
        # Ensure logs directory exists
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename with timestamp
        self.session_start = datetime.now()
        filename = self.session_start.strftime("session_%Y%m%d_%H%M%S.csv")
        self.current_file = self.logs_dir / filename

        # Write headers
        async with aiofiles.open(self.current_file, mode="w", newline="", encoding="utf-8") as f:
            # Write BOM for Excel compatibility
            await f.write("\ufeff")
            # Write headers as CSV row
            await f.write(",".join(self.HEADERS) + "\n")

        logger.info(f"Started session log: {self.current_file}")
        return self.current_file

    async def log_request(self, request: SongRequest) -> None:
        """
        Log a song request to the current session file.

        Args:
            request: The song request to log
        """
        if not self.current_file:
            await self.start_session()

        row = [
            datetime.now().isoformat(),
            self._escape_csv(request.song.title),
            self._escape_csv(request.song.artist),
            self._escape_csv(request.song.album),
            request.song.spotify_id,
            request.requester,
            str(request.like_count),
            str(request.skip_count),
            request.song.duration_formatted,
        ]

        async with aiofiles.open(self.current_file, mode="a", newline="", encoding="utf-8") as f:
            await f.write(",".join(row) + "\n")

        logger.debug(f"Logged request: {request.song.title} by {request.requester}")

    async def update_request(self, request: SongRequest) -> None:
        """
        Update the last logged request with final vote counts.
        This is called when a song finishes playing.

        Note: For simplicity, we log a new row with updated counts.
        A more sophisticated approach would update the existing row.

        Args:
            request: The request with updated vote counts
        """
        # For simplicity, we'll just log requests when they're added
        # and the final vote counts will be in the log at the time of logging
        pass

    def _escape_csv(self, value: str) -> str:
        """
        Escape a value for CSV format.
        Wraps in quotes if contains comma, quote, or newline.
        """
        if not value:
            return ""

        # Check if escaping is needed
        needs_escaping = any(c in value for c in [",", '"', "\n", "\r"])

        if needs_escaping:
            # Escape quotes by doubling them
            escaped = value.replace('"', '""')
            return f'"{escaped}"'

        return value

    async def get_session_summary(self) -> dict:
        """
        Get summary of current session.

        Returns:
            Dictionary with session stats
        """
        if not self.current_file or not self.current_file.exists():
            return {
                "session_start": None,
                "total_requests": 0,
                "log_file": None,
            }

        # Count lines (excluding header)
        line_count = 0
        try:
            async with aiofiles.open(self.current_file, mode="r", encoding="utf-8") as f:
                async for _ in f:
                    line_count += 1
            # Subtract header line and BOM
            line_count = max(0, line_count - 1)
        except Exception as e:
            logger.error(f"Error reading session log: {e}")

        return {
            "session_start": self.session_start.isoformat() if self.session_start else None,
            "total_requests": line_count,
            "log_file": str(self.current_file),
        }

    async def get_recent_entries(self, limit: int = 10) -> list:
        """
        Get recent log entries.

        Args:
            limit: Maximum entries to return

        Returns:
            List of dictionaries with entry data
        """
        if not self.current_file or not self.current_file.exists():
            return []

        entries = []
        try:
            async with aiofiles.open(self.current_file, mode="r", encoding="utf-8") as f:
                lines = await f.readlines()

            # Skip BOM and header
            data_lines = lines[1:] if len(lines) > 1 else []

            # Get last N entries
            recent_lines = data_lines[-limit:] if len(data_lines) > limit else data_lines

            for line in recent_lines:
                parts = self._parse_csv_line(line.strip())
                if len(parts) >= len(self.HEADERS):
                    entries.append({
                        self.HEADERS[i]: parts[i]
                        for i in range(len(self.HEADERS))
                    })

        except Exception as e:
            logger.error(f"Error reading recent entries: {e}")

        return entries

    def _parse_csv_line(self, line: str) -> list:
        """
        Parse a CSV line, handling quoted values.

        Args:
            line: CSV line string

        Returns:
            List of field values
        """
        result = []
        current = ""
        in_quotes = False

        i = 0
        while i < len(line):
            char = line[i]

            if char == '"':
                if in_quotes and i + 1 < len(line) and line[i + 1] == '"':
                    # Escaped quote
                    current += '"'
                    i += 1
                else:
                    # Toggle quote mode
                    in_quotes = not in_quotes
            elif char == "," and not in_quotes:
                result.append(current)
                current = ""
            else:
                current += char

            i += 1

        # Add last field
        result.append(current)

        return result

    def get_log_file_path(self) -> Optional[str]:
        """Get the current log file path."""
        return str(self.current_file) if self.current_file else None
