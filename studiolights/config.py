"""Persistence for lights_config.json, scenes.json and devices.json import."""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .defaults import demo_devices, demo_scenes, demo_states, devices_template
from .models import (
    AppData,
    LightDevice,
    LightState,
    Scene,
    normalize_version,
    utc_now_iso,
)
from .util import atomic_write_json, backup_corrupt_file, read_json

LOGGER = logging.getLogger("studiolights.config")

LIGHTS_FILE = "lights_config.json"
SCENES_FILE = "scenes.json"
DEVICES_FILE = "devices.json"
TEMPLATE_FILE = "devices_template.json"
SCHEMA_VERSION = 1


class ConfigError(RuntimeError):
    """User-actionable configuration error."""


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


class LightStore:
    """Owns lights_config.json. Missing files fall back to devices.json / demo data."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else project_root()
        self.path = self.root / LIGHTS_FILE

    # ------------------------------------------------------------------ load
    def load(self) -> AppData | None:
        if not self.path.exists():
            return None
        try:
            raw = read_json(self.path)
        except (OSError, json.JSONDecodeError) as exc:
            backup = backup_corrupt_file(self.path)
            LOGGER.error("lights_config.json non leggibile (%s). Backup: %s", exc, backup)
            return None

        if not isinstance(raw, dict):
            backup_corrupt_file(self.path)
            LOGGER.error("lights_config.json non è un oggetto JSON: file ignorato.")
            return None

        devices: list[LightDevice] = []
        states: dict[str, LightState] = {}
        seen: set[str] = set()
        for entry in raw.get("devices") or []:
            if not isinstance(entry, dict):
                continue
            device = LightDevice.from_dict(entry)
            if not device.id or device.id in seen:
                continue
            seen.add(device.id)
            devices.append(device)
            states[device.id] = LightState.from_dict(entry.get("state"))

        return AppData(
            devices=devices,
            states=states,
            demo=bool(raw.get("demo", False)),
        )

    # ------------------------------------------------------------------ save
    def save(
        self,
        devices: Iterable[LightDevice],
        states: dict[str, LightState],
        demo: bool = False,
    ) -> None:
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "demo": bool(demo),
            "updated_at": utc_now_iso(),
            "devices": [
                {**device.to_dict(), "state": states.get(device.id, LightState()).to_dict()}
                for device in devices
            ],
        }
        atomic_write_json(self.path, payload)

    # -------------------------------------------------------------- bootstrap
    def bootstrap(self) -> AppData:
        """Load existing config, else import devices.json, else demo data."""
        self.ensure_template()
        existing = self.load()
        if existing is not None:
            return existing

        imported, warnings = self.import_devices_json()
        if imported:
            data = AppData(
                devices=imported,
                states={device.id: LightState() for device in imported},
                demo=False,
            )
            self.save(data.devices, data.states, data.demo)
            for warning in warnings:
                LOGGER.warning(warning)
            return data

        data = AppData(devices=demo_devices(), states=demo_states(), demo=True)
        self.save(data.devices, data.states, data.demo)
        LOGGER.info("Configurazione demo creata: %d luci finte.", len(data.devices))
        return data

    # --------------------------------------------------------------- import
    def import_devices_json(self) -> tuple[list[LightDevice], list[str]]:
        path = self.root / DEVICES_FILE
        if not path.exists():
            return [], ["devices.json non trovato: import saltato."]
        try:
            raw = read_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"devices.json non è un JSON valido: {exc}") from exc

        if isinstance(raw, list):
            entries = raw
        elif isinstance(raw, dict):
            if isinstance(raw.get("devices"), list):
                entries = raw["devices"]
            else:
                # Some wizard versions emit { "device_id": {...}, ... }
                entries = [
                    {**value, "id": value.get("id") or key}
                    for key, value in raw.items()
                    if isinstance(value, dict)
                ]
        else:
            raise ConfigError("Struttura devices.json non riconosciuta.")

        devices: list[LightDevice] = []
        warnings: list[str] = []
        seen: set[str] = set()
        skipped_no_key = 0
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            device = LightDevice.from_dict(entry)
            if not device.id or not device.local_key:
                skipped_no_key += 1
                continue
            device.version = normalize_version(device.version)
            if device.id in seen:
                continue
            seen.add(device.id)
            if not device.ip:
                warnings.append(f"{device.name}: IP assente, usa «Scansiona LAN».")
            devices.append(device)

        if skipped_no_key:
            warnings.append(f"{skipped_no_key} dispositivi ignorati (Device ID o Local Key mancanti).")
        if not devices:
            warnings.append("devices.json non contiene lampadine importabili.")
        return devices, warnings

    # -------------------------------------------------------------- template
    def ensure_template(self) -> Path:
        path = self.root / TEMPLATE_FILE
        if not path.exists():
            atomic_write_json(path, devices_template())
        return path


class SceneStore:
    """Owns scenes.json, with automatic seed and corruption recovery."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else project_root()
        self.path = self.root / SCENES_FILE

    def load(self) -> list[Scene]:
        if not self.path.exists():
            scenes = demo_scenes()
            self.save(scenes)
            return scenes
        try:
            raw = read_json(self.path)
        except (OSError, json.JSONDecodeError) as exc:
            backup = backup_corrupt_file(self.path)
            LOGGER.error("scenes.json non leggibile (%s). Backup: %s", exc, backup)
            scenes = demo_scenes()
            self.save(scenes)
            return scenes

        if isinstance(raw, list):
            entries = raw
        elif isinstance(raw, dict):
            entries = raw.get("scenes") or []
        else:
            entries = []

        scenes: list[Scene] = []
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            scene = Scene.from_dict(entry)
            if scene.id in seen or not scene.name:
                continue
            seen.add(scene.id)
            scenes.append(scene)
        return scenes

    def save(self, scenes: Iterable[Scene]) -> None:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "updated_at": utc_now_iso(),
            "scenes": [scene.to_dict() for scene in scenes],
        }
        atomic_write_json(self.path, payload)
