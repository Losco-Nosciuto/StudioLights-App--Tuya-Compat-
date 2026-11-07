"""Studio Lights entry point."""

from __future__ import annotations

import argparse
import ctypes
import logging
import sys

from studiolights import __version__
from studiolights.config import project_root
from studiolights.util import setup_logging


def _prepare_windows() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("StudioLights.App")
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Studio Lights - controllo luci Tuya in LAN")
    parser.add_argument("--version", action="version", version=f"Studio Lights {__version__}")
    args = parser.parse_args()
    _ = args

    _prepare_windows()
    log = setup_logging(project_root() / "logs")

    from studiolights.instance import SingleInstance

    instance = SingleInstance()
    if not instance.acquire():
        log.info("Studio Lights è già attiva: ripristino la finestra esistente.")
        return 0

    try:
        from studiolights.ui.app import StudioLightsApp

        app = StudioLightsApp()
        instance.watch(app.request_restore)
        app.mainloop()
    except Exception:
        log.exception("Errore fatale all'avvio")
        try:
            from tkinter import messagebox

            messagebox.showerror(
                "Studio Lights",
                "Errore fatale all'avvio.\n\nDettagli in logs\\studiolights.log",
            )
        except Exception:
            pass
        return 1
    return 0


if __name__ == "__main__":
    logging.getLogger("studiolights").info("Avvio Studio Lights %s", __version__)
    raise SystemExit(main())
