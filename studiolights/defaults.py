"""Seed data: demo bulbs, demo scenes and the devices_template.json skeleton."""

from __future__ import annotations

from typing import Any

from .models import (
    SCENE_FLOW,
    SCENE_GLOBAL,
    SCENE_SNAPSHOT,
    FlowConfig,
    LightDevice,
    LightState,
    Scene,
)

DEMO_DEVICE_IDS = (
    "bfaa11bb22cc33dd44e1",
    "bfaa11bb22cc33dd44e2",
    "bfaa11bb22cc33dd44e3",
)


def demo_devices() -> list[LightDevice]:
    """Three fake bulbs so the UI is usable before the wizard is run."""
    return [
        LightDevice(
            name="Luce SX",
            device_id=DEMO_DEVICE_IDS[0],
            ip="192.168.1.101",
            local_key="0123456789abcdef",
            version="3.3",
        ),
        LightDevice(
            name="Luce DX",
            device_id=DEMO_DEVICE_IDS[1],
            ip="192.168.1.102",
            local_key="fedcba9876543210",
            version="3.3",
        ),
        LightDevice(
            name="Luce Sfondo",
            device_id=DEMO_DEVICE_IDS[2],
            ip="192.168.1.103",
            local_key="0a1b2c3d4e5f6071",
            version="3.4",
        ),
    ]


def demo_states() -> dict[str, LightState]:
    return {
        DEMO_DEVICE_IDS[0]: LightState(
            power=True, mode="colour", brightness=80, rgb=(0, 220, 255)
        ),
        DEMO_DEVICE_IDS[1]: LightState(
            power=True, mode="colour", brightness=80, rgb=(175, 35, 255)
        ),
        DEMO_DEVICE_IDS[2]: LightState(
            power=True, mode="white", brightness=30, colortemp=35
        ),
    }


def demo_scenes() -> list[Scene]:
    """Seven ready-to-use studio scenes (2 snapshots + 1 infinite flow)."""
    sx, dx, background = DEMO_DEVICE_IDS
    return [
        Scene(
            id="scn_lavoro_neutro",
            name="Lavoro Neutro",
            type=SCENE_GLOBAL,
            state=LightState(power=True, mode="white", brightness=85, colortemp=55),
        ),
        Scene(
            id="scn_relax_caldo",
            name="Relax Caldo",
            type=SCENE_GLOBAL,
            state=LightState(power=True, mode="white", brightness=35, colortemp=8),
        ),
        Scene(
            id="scn_cyberpunk_dual",
            name="Cyberpunk Dual-Tone",
            type=SCENE_SNAPSHOT,
            demo=True,
            lights={
                sx: LightState(power=True, mode="colour", brightness=85, rgb=(0, 225, 255)),
                dx: LightState(power=True, mode="colour", brightness=85, rgb=(255, 25, 190)),
                background: LightState(power=True, mode="colour", brightness=40, rgb=(25, 15, 110)),
            },
            state=LightState(power=True, mode="colour", brightness=85, rgb=(0, 225, 255)),
        ),
        Scene(
            id="scn_full_red",
            name="Full Red",
            type=SCENE_GLOBAL,
            state=LightState(power=True, mode="colour", brightness=100, rgb=(255, 0, 0)),
        ),
        Scene(
            id="scn_deep_purple",
            name="Deep Purple",
            type=SCENE_GLOBAL,
            state=LightState(power=True, mode="colour", brightness=65, rgb=(110, 30, 200)),
        ),
        Scene(
            id="scn_cinema_soft",
            name="Cinema Soft",
            type=SCENE_SNAPSHOT,
            demo=True,
            lights={
                sx: LightState(power=True, mode="colour", brightness=20, rgb=(255, 135, 40)),
                dx: LightState(power=True, mode="colour", brightness=18, rgb=(20, 45, 180)),
                background: LightState(power=False, mode="white", brightness=10, colortemp=20),
            },
            state=LightState(power=True, mode="colour", brightness=20, rgb=(255, 135, 40)),
        ),
        Scene(
            id="scn_aurora_flow",
            name="Aurora Flow",
            type=SCENE_FLOW,
            flow=FlowConfig(
                palette=[
                    "#00e5ff",
                    "#35e0c8",
                    "#7cff6b",
                    "#3da5ff",
                    "#6c5ce7",
                    "#ff4fd8",
                    "#ff8a3d",
                    "#ffd166",
                ],
                segment_seconds=2.5,
                fps=10,
                phase_offset=True,
                brightness=75,
            ),
        ),
    ]


def devices_template() -> dict[str, Any]:
    """Skeleton mirroring the output of `python -m tinytuya wizard`."""
    return {
        "_instructions": [
            "Questo file è solo un modello: NON viene letto dall'app.",
            "1) Installa le dipendenze: pip install -r requirements.txt",
            "2) Esegui: python -m tinytuya wizard",
            "3) Salva il devices.json generato nella root del progetto (accanto a main.py)",
            "4) Apri Studio Lights > Impostazioni > Importa devices.json",
            "Le Local Key sono segreti: non committare devices.json su Git.",
        ],
        "version": "3.3",
        "devices": [
            {
                "name": "Luce SX",
                "id": "bf00000000000000000001",
                "ip": "192.168.1.101",
                "key": "0123456789abcdef",
                "version": "3.3",
            },
            {
                "name": "Luce DX",
                "id": "bf00000000000000000002",
                "ip": "192.168.1.102",
                "key": "fedcba9876543210",
                "version": "3.4",
            },
            {
                "name": "Luce Sfondo",
                "id": "bf00000000000000000003",
                "ip": "",
                "key": "0a1b2c3d4e5f6071",
                "version": "3.5",
            },
        ],
    }
