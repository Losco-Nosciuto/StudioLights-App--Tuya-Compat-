"""Domain models shared by the UI and the Tuya controller."""

from __future__ import annotations

import ipaddress
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .util import clamp_int, kelvin_from_temp, rgb_to_hex

SUPPORTED_VERSIONS = ("3.1", "3.2", "3.3", "3.4", "3.5")
DEFAULT_VERSION = "3.3"
VALID_MODES = ("white", "colour", "scene")


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def normalize_version(value: Any) -> str:
    text = str(value if value is not None else DEFAULT_VERSION).strip().lower().lstrip("v")
    if text.endswith(".0") and text[:-2] in SUPPORTED_VERSIONS:
        text = text[:-2]
    return text if text in SUPPORTED_VERSIONS else DEFAULT_VERSION


@dataclass
class LightDevice:
    """A single bulb as configured by the user / tinytuya wizard."""

    name: str
    device_id: str
    ip: str
    local_key: str
    version: str = DEFAULT_VERSION

    def __post_init__(self) -> None:
        self.name = str(self.name or "").strip()
        self.device_id = str(self.device_id or "").strip()
        self.ip = str(self.ip or "").strip()
        self.local_key = str(self.local_key or "").strip()
        self.version = normalize_version(self.version)

    @property
    def id(self) -> str:
        return self.device_id

    @property
    def display_ip(self) -> str:
        return self.ip or "IP mancante"

    @property
    def masked_key(self) -> str:
        if len(self.local_key) < 10:
            return "•" * 8
        return f"{self.local_key[:3]}…{self.local_key[-3:]}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "id": self.device_id,
            "ip": self.ip,
            "key": self.local_key,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LightDevice:
        return cls(
            name=data.get("name") or data.get("friendly_name") or data.get("id") or "Luce",
            device_id=data.get("id") or data.get("devId") or data.get("gwId") or "",
            ip=data.get("ip") or data.get("address") or "",
            local_key=data.get("key") or data.get("local_key") or data.get("localKey") or "",
            version=data.get("version") or data.get("ver") or DEFAULT_VERSION,
        )

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not self.name:
            errors.append("Il nome è obbligatorio.")
        if not self.device_id:
            errors.append("Il Device ID è obbligatorio.")
        elif any(character.isspace() for character in self.device_id):
            errors.append("Il Device ID non può contenere spazi.")
        if len(self.local_key) != 16:
            errors.append("La Local Key deve essere lunga esattamente 16 caratteri.")
        if self.version not in SUPPORTED_VERSIONS:
            errors.append("Versione protocollo non supportata.")
        if self.ip:
            try:
                parsed = ipaddress.ip_address(self.ip)
                if parsed.version != 4:
                    errors.append("L'app usa indirizzi IPv4 (es. 192.168.1.50).")
            except ValueError:
                errors.append("Indirizzo IP non valido.")
        return errors

    def validation_warnings(self) -> list[str]:
        warnings: list[str] = []
        if not self.ip:
            warnings.append("IP assente: usa «Scansiona LAN» o inseriscilo manualmente.")
        return warnings

    def copy(self, **changes: Any) -> LightDevice:
        data = self.to_dict()
        if "device_id" in changes:
            changes["id"] = changes.pop("device_id")
        data.update(changes)
        return LightDevice.from_dict(data)


@dataclass
class LightState:
    """Desired / last known state of a bulb. Values are UI-friendly percentages."""

    power: bool = True
    mode: str = "white"
    brightness: int = 80
    colortemp: int = 50
    rgb: tuple[int, int, int] = (255, 200, 150)
    hw_scene: int | None = None
    hw_data: str | None = None

    def __post_init__(self) -> None:
        self.power = bool(self.power)
        self.mode = self.mode if self.mode in VALID_MODES else "white"
        self.brightness = clamp_int(self.brightness, 1, 100, 80)
        self.colortemp = clamp_int(self.colortemp, 0, 100, 50)
        try:
            red, green, blue = self.rgb
            self.rgb = (
                clamp_int(red, 0, 255, 255),
                clamp_int(green, 0, 255, 255),
                clamp_int(blue, 0, 255, 255),
            )
        except (TypeError, ValueError):
            self.rgb = (255, 255, 255)
        if self.hw_scene is not None:
            self.hw_scene = clamp_int(self.hw_scene, 1, 255, 1)
            if self.mode == "white":
                self.mode = "scene"
        self.hw_data = str(self.hw_data).strip() if self.hw_data else None

    @property
    def is_colour(self) -> bool:
        return self.mode == "colour" and self.hw_scene is None

    @property
    def is_hardware_scene(self) -> bool:
        return self.hw_scene is not None

    @property
    def kelvin(self) -> int:
        return kelvin_from_temp(self.colortemp)

    @property
    def accent_hex(self) -> str:
        if self.is_hardware_scene:
            return "#b06cff"
        if not self.power:
            return "#3a4656"
        if self.is_colour:
            red, green, blue = self.rgb
            factor = 0.45 + 0.55 * (self.brightness / 100.0)
            return rgb_to_hex(tuple(round(c * factor) for c in (red, green, blue)))  # type: ignore[arg-type]
        from .util import temp_preview_hex

        return temp_preview_hex(self.colortemp, self.brightness)

    def summary(self) -> str:
        if not self.power:
            return "Spenta"
        if self.hw_scene is not None:
            return f"Scena HW {self.hw_scene}"
        if self.is_colour:
            red, green, blue = self.rgb
            return f"RGB {red},{green},{blue} · {self.brightness}%"
        return f"Bianco {self.brightness}% · {self.kelvin}K"

    def to_dict(self) -> dict[str, Any]:
        return {
            "power": self.power,
            "mode": self.mode,
            "brightness": self.brightness,
            "colortemp": self.colortemp,
            "rgb": list(self.rgb),
            "hw_scene": self.hw_scene,
            "hw_data": self.hw_data,
        }

    @classmethod
    def from_dict(cls, data: Any, fallback: LightState | None = None) -> LightState:
        base = fallback or cls()
        if not isinstance(data, dict):
            return base.copy()
        return cls(
            power=data.get("power", base.power),
            mode=data.get("mode", base.mode),
            brightness=data.get("brightness", base.brightness),
            colortemp=data.get("colortemp", base.colortemp),
            rgb=data.get("rgb", base.rgb),
            hw_scene=data.get("hw_scene", base.hw_scene),
            hw_data=data.get("hw_data", base.hw_data),
        )

    def copy(self, **changes: Any) -> LightState:
        data = self.to_dict()
        data.update(changes)
        return LightState.from_dict(data)


SCENE_GLOBAL = "global"
SCENE_SNAPSHOT = "snapshot"
SCENE_TYPES = (SCENE_GLOBAL, SCENE_SNAPSHOT)


@dataclass
class Scene:
    """A global scene (one state) or a multi-light snapshot (state per device)."""

    name: str
    type: str = SCENE_GLOBAL
    id: str = field(default_factory=lambda: f"scn_{uuid.uuid4().hex[:10]}")
    state: LightState | None = None
    lights: dict[str, LightState] = field(default_factory=dict)
    demo: bool = False
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        self.name = str(self.name or "").strip()
        self.type = self.type if self.type in SCENE_TYPES else SCENE_GLOBAL
        self.id = str(self.id or f"scn_{uuid.uuid4().hex[:10]}")
        if self.state is not None and not isinstance(self.state, LightState):
            self.state = LightState.from_dict(self.state)
        cleaned: dict[str, LightState] = {}
        for key, value in (self.lights or {}).items():
            cleaned[str(key)] = value if isinstance(value, LightState) else LightState.from_dict(value)
        self.lights = cleaned
        if self.type == SCENE_GLOBAL and self.state is None:
            self.state = LightState()
        if self.type == SCENE_SNAPSHOT and not self.lights:
            # A snapshot with no lights is still valid data-wise, but the UI blocks it.
            self.state = self.state or LightState()

    @property
    def is_global(self) -> bool:
        return self.type == SCENE_GLOBAL

    @property
    def is_snapshot(self) -> bool:
        return self.type == SCENE_SNAPSHOT

    @property
    def type_label(self) -> str:
        return "GLOBALE" if self.is_global else "SNAPSHOT"

    @property
    def accent_hex(self) -> str:
        if self.is_global and self.state:
            return self.state.accent_hex
        if self.lights:
            first = next(iter(self.lights.values()))
            return first.accent_hex
        return "#4a5a6e"

    def summary(self, known_names: dict[str, str] | None = None) -> str:
        if self.is_global and self.state:
            return self.state.summary()
        count = len(self.lights)
        if known_names is not None:
            available = sum(1 for device_id in self.lights if device_id in known_names)
            return f"{count} luci · {available} disponibili"
        return f"{count} luci · snapshot"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "demo": self.demo,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.state is not None:
            payload["state"] = self.state.to_dict()
        if self.lights:
            payload["lights"] = {device_id: state.to_dict() for device_id, state in self.lights.items()}
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Scene:
        scene_type = data.get("type", SCENE_GLOBAL)
        state = LightState.from_dict(data.get("state")) if data.get("state") is not None else None
        lights_raw = data.get("lights") or {}
        lights = {
            str(device_id): LightState.from_dict(state_data)
            for device_id, state_data in lights_raw.items()
            if isinstance(state_data, dict)
        }
        return cls(
            id=data.get("id") or f"scn_{uuid.uuid4().hex[:10]}",
            name=data.get("name") or "Scena senza nome",
            type=scene_type if scene_type in SCENE_TYPES else SCENE_GLOBAL,
            state=state,
            lights=lights,
            demo=bool(data.get("demo", False)),
            created_at=data.get("created_at") or utc_now_iso(),
            updated_at=data.get("updated_at") or utc_now_iso(),
        )

    def copy(self) -> Scene:
        return Scene.from_dict(json.loads(json.dumps(self.to_dict())))


ERROR_OFFLINE = "offline"
ERROR_AUTH = "auth"
ERROR_PROTOCOL = "protocol"
ERROR_UNSUPPORTED = "unsupported"
ERROR_CONFIG = "config"
ERROR_UNKNOWN = "error"


@dataclass
class LightResult:
    device_id: str
    name: str
    ok: bool
    latency_ms: int = 0
    error: str = ""
    kind: str = ""
    state: LightState | None = None

    @property
    def is_offline(self) -> bool:
        return not self.ok and self.kind in (ERROR_OFFLINE, ERROR_AUTH)


@dataclass
class OperationReport:
    action: str
    results: list[LightResult] = field(default_factory=list)
    elapsed_ms: int = 0

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def successes(self) -> list[LightResult]:
        return [result for result in self.results if result.ok]

    @property
    def failures(self) -> list[LightResult]:
        return [result for result in self.results if not result.ok]

    @property
    def success_count(self) -> int:
        return len(self.successes)

    @property
    def failure_count(self) -> int:
        return len(self.failures)

    @property
    def offline_names(self) -> list[str]:
        return [result.name for result in self.results if result.is_offline]

    @property
    def all_ok(self) -> bool:
        return bool(self.results) and self.failure_count == 0

    def failure_hint(self, limit: int = 2) -> str:
        hints = []
        for result in self.failures[:limit]:
            label = result.error or "errore sconosciuto"
            hints.append(f"{result.name}: {label}")
        if self.failure_count > limit:
            hints.append(f"+{self.failure_count - limit}")
        return ", ".join(hints)


@dataclass
class AppData:
    devices: list[LightDevice] = field(default_factory=list)
    states: dict[str, LightState] = field(default_factory=dict)
    demo: bool = False
