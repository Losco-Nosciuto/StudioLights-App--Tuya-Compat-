"""Screen Sync tests that do not require a real monitor or Tuya hardware."""

from __future__ import annotations

import time
import unittest
from concurrent.futures import Future
from pathlib import Path

from PIL import Image, ImageDraw

from studiolights.models import LightDevice, LightResult
from studiolights.screen_sync import (
    ScreenAnalyzer,
    ScreenSyncConfig,
    ScreenSyncRunner,
    ScreenSyncStore,
    list_monitors,
)


class ScreenConfigTests(unittest.TestCase):
    def test_clamps_and_roundtrip(self) -> None:
        config = ScreenSyncConfig(
            zones=9,
            sample_grid=9,
            smoothing=9,
            saturation=9,
            brightness_min=90,
            brightness_max=10,
            fps=99,
            zone_map={"a": 9, "b": -4},
        )
        self.assertEqual(config.zones, 7)
        self.assertEqual(config.sample_grid, 3)
        self.assertEqual(config.sample_points, 9)
        self.assertEqual(config.smoothing, 3.0)
        self.assertEqual(config.saturation, 2.0)
        self.assertEqual(config.fps, 30)
        self.assertGreaterEqual(config.brightness_max, config.brightness_min)
        self.assertEqual(config.zone_map["a"], 6)
        self.assertEqual(config.zone_map["b"], -1)
        again = ScreenSyncConfig.from_dict(config.to_dict())
        self.assertEqual(again.to_dict(), config.to_dict())

    def test_default_zones_and_store(self) -> None:
        devices = [
            LightDevice("A", "a", "192.168.1.10", "0123456789abcdef", "3.3"),
            LightDevice("B", "b", "192.168.1.11", "0123456789abcdef", "3.3"),
            LightDevice("C", "c", "192.168.1.12", "0123456789abcdef", "3.3"),
        ]
        config = ScreenSyncConfig(zones=3)
        config.assign_default_zones(devices)
        self.assertEqual([config.zone_for(d) for d in devices], [0, 1, 2])

        with self.subTest("store"):
            import tempfile

            with tempfile.TemporaryDirectory() as tmp:
                store = ScreenSyncStore(Path(tmp))
                store.save(config)
                loaded = store.load()
                self.assertEqual(loaded.zones, 3)
                self.assertEqual(loaded.zone_map, config.zone_map)

    def test_monitors_are_enumerated(self) -> None:
        monitors = list_monitors()
        self.assertGreaterEqual(len(monitors), 1)
        self.assertGreater(monitors[0].width, 0)


class ScreenAnalyzerTests(unittest.TestCase):
    @staticmethod
    def _stripes() -> Image.Image:
        image = Image.new("RGB", (96, 54), (0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 31, 53), fill=(255, 0, 0))
        draw.rectangle((32, 0, 63, 53), fill=(0, 255, 0))
        draw.rectangle((64, 0, 95, 53), fill=(0, 0, 255))
        return image

    def test_zone_colours(self) -> None:
        config = ScreenSyncConfig(
            zones=3,
            sample_grid=1,
            ignore_hud=False,
            smoothing=0.3,
            brightness_min=10,
            brightness_max=90,
        )
        frame = ScreenAnalyzer().update(self._stripes(), config, 1.0)
        self.assertFalse(frame.black)
        self.assertEqual(len(frame.zones), 3)
        red, green, blue = frame.zones
        self.assertGreater(red.rgb[0], red.rgb[1])
        self.assertGreater(green.rgb[1], green.rgb[0])
        self.assertGreater(blue.rgb[2], blue.rgb[0])
        self.assertTrue(all(10 <= target.brightness <= 90 for target in frame.zones))

    def test_letterbox_and_hud(self) -> None:
        image = Image.new("RGB", (96, 54), (0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 10, 95, 43), fill=(0, 0, 255))
        draw.rectangle((0, 0, 95, 4), fill=(255, 255, 255))
        config = ScreenSyncConfig(
            zones=3,
            sample_grid=1,
            ignore_hud=True,
            smoothing=0.3,
            brightness_min=10,
            brightness_max=90,
        )
        frame = ScreenAnalyzer().update(image, config, 1.0)
        self.assertFalse(frame.black)
        # The white HUD strip must not dominate the top zone.
        self.assertGreater(frame.zones[0].rgb[2], frame.zones[0].rgb[0])
        self.assertGreater(frame.zones[0].rgb[2], frame.zones[0].rgb[1])

    def test_black_detection(self) -> None:
        config = ScreenSyncConfig(ignore_hud=False, hold_on_black=True)
        frame = ScreenAnalyzer().update(Image.new("RGB", (96, 54), (0, 0, 0)), config, 1.0)
        self.assertTrue(frame.black)
        self.assertTrue(frame.warning)


class FakeCapture:
    def __init__(self, image: Image.Image) -> None:
        self.image = image
        self.closed = False

    def grab(self) -> Image.Image:
        return self.image.copy()

    def close(self) -> None:
        self.closed = True


class FakeController:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[int, int, int], int]] = []

    def submit_colour_frame(self, device, rgb, brightness):
        future: Future = Future()
        future.set_result(LightResult(device.id, device.name, True))
        self.calls.append((device.id, rgb, brightness))
        return future


class ScreenRunnerTests(unittest.TestCase):
    def test_runner_streams_and_stops(self) -> None:
        controller = FakeController()
        image = ScreenAnalyzerTests._stripes()
        runner = ScreenSyncRunner(controller)  # type: ignore[arg-type]
        runner._capture_factory = lambda _index: FakeCapture(image)  # type: ignore[assignment]
        devices = [
            LightDevice("A", "a", "192.168.1.10", "0123456789abcdef", "3.3"),
            LightDevice("B", "b", "192.168.1.11", "0123456789abcdef", "3.3"),
        ]
        config = ScreenSyncConfig(
            zones=2,
            sample_grid=1,
            ignore_hud=False,
            smoothing=0.3,
            fps=30,
            brightness_min=10,
            brightness_max=90,
        )
        runner.start(devices, config, {"a": 0, "b": 1})
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and runner.frame_count < 5:
            time.sleep(0.02)
        self.assertGreater(runner.frame_count, 0)
        self.assertIsNotNone(runner.last_frame)
        targets = runner.last_targets
        self.assertIn("a", targets)
        self.assertIn("b", targets)
        colors = runner.stop()
        self.assertFalse(runner.is_running)
        self.assertGreaterEqual(len(colors), 1)


if __name__ == "__main__":
    unittest.main()
