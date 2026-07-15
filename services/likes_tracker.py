"""
Persistent per-requester like tracking for the !musicrats leaderboard.

Every !like on a requested song credits the requester. Data lives in a
small JSON file so the leaderboard accumulates across streams.
"""

import json
import logging
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


class LikesTracker:
    """Tracks total likes earned by each requester, per song."""

    def __init__(self, path: str = "logs/musicrats.json"):
        self.path = Path(path)
        # {username_lower: {"display": str, "songs": {song_label: like_count}}}
        self.data: dict = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
            logger.info(f"Loaded music rats data for {len(self.data)} requesters")
        except Exception as e:
            logger.error(f"Failed to load music rats data: {e}")
            self.data = {}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save music rats data: {e}")

    def add_like(self, requester: str, song_label: str) -> None:
        """Credit one like to a requester for a song."""
        key = requester.lower()
        entry = self.data.setdefault(key, {"display": requester, "songs": {}})
        entry["display"] = requester  # keep the latest capitalization
        entry["songs"][song_label] = entry["songs"].get(song_label, 0) + 1
        self._save()

    def total_likes(self, requester: str) -> int:
        entry = self.data.get(requester.lower())
        return sum(entry["songs"].values()) if entry else 0

    def top(self, n: int = 5) -> List[Tuple[str, int]]:
        """Top requesters as (display_name, total_likes), most liked first."""
        ranked = sorted(
            ((e["display"], sum(e["songs"].values())) for e in self.data.values()),
            key=lambda item: item[1],
            reverse=True,
        )
        return [r for r in ranked if r[1] > 0][:n]

    def best_song(self) -> Optional[Tuple[str, str, int]]:
        """The single most-liked song as (song_label, display_name, likes)."""
        best = None
        for entry in self.data.values():
            for label, likes in entry["songs"].items():
                if best is None or likes > best[2]:
                    best = (label, entry["display"], likes)
        return best
