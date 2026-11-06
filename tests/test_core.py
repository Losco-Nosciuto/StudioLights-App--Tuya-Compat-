"""Core tests that run without any physical bulb or GUI."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import tinytuya

from studiolights.config import LightStore, SceneStore
from studiolights.controller import (
    build_dps,
    classify_error,
    state_from_status,
)
from studiolights.defaults import DEMO_DEVICE_IDS, demo_scenes
from studiolights.models import (
    ERROR_AUTH,
    ERROR_OFFLINE,
    LightDevice,
    LightState,
    Scene,
    normalize_version,
)
from studiolights.util import kelvin_from_temp, kelvin_to_rgb, temp_preview_hex


class FakeBulb:
    """Minimal stand-in exposing the bits used by build_dps/state_from_status."""

    def __init__(self) -> None:
        self.dpset = {
            "switch": "20",
            "mode": "21",
            "brightness": "22",
            "colourtemp": "23",
            "colour": "24",
            "scene": "25",
            "scene_data": "25",
            "timer": "26",
            "music": "28",
            "value_min": 10,
            "value_max": 1000,
            "value_hexformat": "hsv16",
        }
        self.bulb_configured = True

    rgb_to_hexvalue = staticmethod(tinytuya.BulbDevice.rgb_to_hexvalue)

    def colour_rgb(self, state=None):
        return tinytuya.BulbDevice.hexvalue_to_rgb(state["colour"], "hsv16")


class ModelTests(unittest.TestCase):
    def test_version_normalization(self) -> None:
        self.assertEqual(normalize_version(3.4), "3.4")
        self.assertEqual(normalize_version("v3.5"), "3.5")
        self.assertEqual(normalize_version("9.9"), "3.3")

    def test_state_clamps_and_roundtrips(self) -> None:
        state = LightState(
            brightness=0,
            colortemp=180,
            rgb=(300, -5, 128),
            mode="colour",
        )
        self.assertEqual(state.brightness, 1)
        self.assertEqual(state.colortemp, 100)
        self.assertEqual(state.rgb, (255, 0, 128))
        again = LightState.from_dict(state.to_dict())
        self.assertEqual(again, state)

    def test_device_validation(self) -> None:
        device = LightDevice("Luce", "dev-1", "not-an-ip", "short", "3.3")
        errors = " ".join(device.validation_errors())
        self.assertIn("16", errors)
        self.assertIn("IP", errors)
        good = LightDevice("Luce", "dev-1", "192.168.1.9", "0123456789abcdef", "3.3")
        self.assertEqual(good.validation_errors(), [])
        self.assertEqual(good.display_ip, "192.168.1.9")

    def test_colour_helpers(self) -> None:
        self.assertEqual(kelvin_from_temp(0), 2700)
        self.assertEqual(kelvin_from_temp(100), 6500)
        self.assertEqual(len(kelvin_to_rgb(4000)), 3)
        self.assertTrue(temp_preview_hex(50, 80).startswith("#"))

    def test_scene_roundtrip(self) -> None:
        scene = Scene(
            name="Test",
            type="snapshot",
            lights={DEMO_DEVICE_IDS[0]: LightState(mode="colour", rgb=(1, 2, 3))},
        )
        copy = Scene.from_dict(scene.to_dict())
        self.assertEqual(copy.id, scene.id)
        self.assertEqual(copy.name, "Test")
        self.assertEqual(copy.lights[DEMO_DEVICE_IDS[0]].rgb, (1, 2, 3))
        self.assertFalse(copy.demo)


class PersistenceTests(unittest.TestCase):
    def test_bootstrap_from_wizard_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "devices.json").write_text(
                json.dumps(
                    [
                        {
                            "name": "Bulb A",
                            "id": "bfaaa",
                            "ip": "192.168.1.20",
                            "key": "0123456789abcdef",
                            "version": "3.4",
                        },
                        {
                            "name": "No key",
                            "id": "bfbbb",
                            "ip": "192.168.1.21",
                            "key": "",
                        },
                    ]
                ),
                encoding="utf-8",
            )
            store = LightStore(root)
            data = store.bootstrap()
            self.assertEqual(len(data.devices), 1)
            self.assertFalse(data.demo)
            self.assertEqual(data.devices[0].name, "Bulb A")
            self.assertTrue((root / "lights_config.json").exists())
            self.assertTrue((root / "devices_template.json").exists())

            loaded = store.load()
            assert loaded is not None
            self.assertEqual(loaded.devices[0].id, "bfaaa")
            self.assertEqual(loaded.states["bfaaa"].brightness, 80)

    def test_wizard_dict_and_save(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "devices.json").write_text(
                json.dumps(
                    {
                        "devices": [
                            {
                                "name": "Bulb B",
                                "id": "bfccc",
                                "ip": "",
                                "key": "fedcba9876543210",
                                "version": 3.5,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            store = LightStore(root)
            data = store.bootstrap()
            self.assertEqual(data.devices[0].version, "3.5")
            self.assertEqual(data.devices[0].ip, "")
            data.states["bfccc"] = LightState(mode="colour", rgb=(10, 20, 30), power=False)
            store.save(data.devices, data.states, demo=False)
            loaded = store.load()
            assert loaded is not None
            self.assertEqual(loaded.states["bfccc"].rgb, (10, 20, 30))
            self.assertFalse(loaded.states["bfccc"].power)

    def test_scene_store_seeds_and_persists(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = SceneStore(root)
            scenes = store.load()
            self.assertGreaterEqual(len(scenes), 6)
            self.assertEqual(len(demo_scenes()), len(scenes))
            scenes.append(Scene(name="Nuova", type="global"))
            store.save(scenes)
            reloaded = store.load()
            self.assertEqual(len(reloaded), len(scenes))
            self.assertEqual(reloaded[-1].name, "Nuova")


class ControllerPayloadTests(unittest.TestCase):
    def test_colour_payload_is_atomic(self) -> None:
        bulb = FakeBulb()
        payload = build_dps(
            bulb,
            LightState(
                power=True,
                mode="colour",
                brightness=80,
                colortemp=30,
                rgb=(0, 220, 255),
            ),
        )
        self.assertIs(payload["20"], True)
        self.assertEqual(payload["22"], 800)
        self.assertEqual(payload["21"], "colour")
        self.assertEqual(
            payload["24"], tinytuya.BulbDevice.rgb_to_hexvalue(0, 220, 255, "hsv16")
        )
        self.assertNotIn("23", payload)

    def test_white_payload_is_atomic(self) -> None:
        bulb = FakeBulb()
        payload = build_dps(
            bulb,
            LightState(power=True, mode="white", brightness=35, colortemp=10),
        )
        self.assertEqual(payload["21"], "white")
        self.assertEqual(payload["22"], 350)
        self.assertEqual(payload["23"], 100)

    def test_power_off_is_tiny(self) -> None:
        bulb = FakeBulb()
        payload = build_dps(bulb, LightState(power=False))
        self.assertEqual(payload, {"20": False})

    def test_state_from_status(self) -> None:
        bulb = FakeBulb()
        colour = tinytuya.BulbDevice.rgb_to_hexvalue(0, 220, 255, "hsv16")
        status = {
            "switch": True,
            "mode": "colour",
            "brightness": 600,
            "colourtemp": 400,
            "colour": colour,
        }
        state = state_from_status(bulb, status, LightState())
        self.assertTrue(state.power)
        self.assertEqual(state.mode, "colour")
        self.assertEqual(state.brightness, 60)
        self.assertEqual(state.colortemp, 40)
        self.assertLessEqual(abs(state.rgb[1] - 220), 3)
        self.assertLessEqual(abs(state.rgb[2] - 255), 3)

    def test_error_classification(self) -> None:
        self.assertEqual(
            classify_error("Network Error: Device Unreachable"), ERROR_OFFLINE
        )
        self.assertEqual(classify_error("Check device key or version"), ERROR_AUTH)

    def test_scan_matching(self) -> None:
        from studiolights.controller import LightController

        devices = [
            LightDevice("A", "ABC123", "192.168.1.5", "0123456789abcdef", "3.3"),
            LightDevice("B", "def456", "192.168.1.6", "0123456789abcdef", "3.3"),
        ]
        found = {
            "192.168.1.50": {"gwId": "abc123"},
            "192.168.1.60": {"gwId": "def456"},
        }
        matches = LightController.match_scan_ips(found, devices)
        self.assertEqual(matches["ABC123"], "192.168.1.50")
        self.assertEqual(matches["def456"], "192.168.1.60")


if __name__ == "__main__":
    unittest.main()
