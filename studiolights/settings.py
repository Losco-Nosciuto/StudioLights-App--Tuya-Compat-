"""Application preferences and saved window session."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import project_root
from .models import utc_now_iso
from .util import atomic_write_json, backup_corrupt_file, read_json

LOGGER = logging.getLogger("studiolights.settings")

SETTINGS_FILE = "app_settings.json"
SCHEMA_VERSION = 1


def _clean_window_state(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return {
        str(key): value
        for key, value in raw.items()
        if isinstance(key, str) and isinstance(value, (str, int, float, bool))
    }


@dataclass
class AppSettings:
    """User preferences persisted in app_settings.json."""

    close_to_tray: bool = True
    window_state: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Any) -> AppSettings:
        if not isinstance(data, dict):
            return cls()
        close_to_tray = data.get("close_to_tray", True)
        return cls(
            close_to_tray=close_to_tray if isinstance(close_to_tray, bool) else True,
            window_state=_clean_window_state(data.get("window_state")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "close_to_tray": self.close_to_tray,
            "window_state": dict(self.window_state),
        }


class AppSettingsStore:
    """Owns app_settings.json. Missing or corrupt files fall back to defaults."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else project_root()
        self.path = self.root / SETTINGS_FILE

    def load(self) -> AppSettings:
        if not self.path.exists():
            return AppSettings()
        try:
            raw = read_json(self.path)
        except (OSError, json.JSONDecodeError) as exc:
            backup = backup_corrupt_file(self.path)
            LOGGER.error("%s non leggibile (%s). Backup: %s", SETTINGS_FILE, exc, backup)
            return AppSettings()
        if not isinstance(raw, dict):
            backup_corrupt_file(self.path)
            LOGGER.error("%s non è un oggetto JSON: preferenze ignorate.", SETTINGS_FILE)
            return AppSettings()
        return AppSettings.from_dict(raw)

    def save(self, settings: AppSettings) -> None:
        atomic_write_json(
            self.path,
            {
                "schema_version": SCHEMA_VERSION,
                "updated_at": utc_now_iso(),
                **settings.to_dict(),
            },
        )
