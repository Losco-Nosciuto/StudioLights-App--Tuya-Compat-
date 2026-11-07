"""Single-instance guard so a second launch restores the running app."""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
from collections.abc import Callable

LOGGER = logging.getLogger("studiolights.instance")

_IS_WINDOWS = sys.platform == "win32"

ERROR_ALREADY_EXISTS = 183
EVENT_MODIFY_STATE = 0x0002
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0x00000000
WAIT_FAILED = 0xFFFFFFFF

if _IS_WINDOWS:
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    _kernel32.CreateMutexW.restype = wintypes.HANDLE
    _kernel32.CreateEventW.argtypes = [
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    _kernel32.CreateEventW.restype = wintypes.HANDLE
    _kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    _kernel32.OpenEventW.restype = wintypes.HANDLE
    _kernel32.SetEvent.argtypes = [wintypes.HANDLE]
    _kernel32.SetEvent.restype = wintypes.BOOL
    _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL


class SingleInstance:
    """Named mutex plus an event used to wake the existing instance."""

    def __init__(self, name: str = "StudioLights.App") -> None:
        self._name = name
        self._mutex: int | None = None
        self._event: int | None = None
        self._watch_thread: threading.Thread | None = None

    def acquire(self) -> bool:
        """Return True for the first instance; signal and return False otherwise."""
        if not _IS_WINDOWS:
            return True
        mutex = _kernel32.CreateMutexW(
            None, False, f"Local\\{self._name}.Mutex"
        )
        if not mutex:
            LOGGER.warning("CreateMutexW fallito: proseguo senza single-instance.")
            return True
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            event = _kernel32.OpenEventW(
                EVENT_MODIFY_STATE, False, f"Local\\{self._name}.Show"
            )
            if event:
                _kernel32.SetEvent(event)
                _kernel32.CloseHandle(event)
            _kernel32.CloseHandle(mutex)
            return False
        self._mutex = int(mutex)
        self._event = int(
            _kernel32.CreateEventW(None, False, False, f"Local\\{self._name}.Show")
            or 0
        )
        return True

    def watch(self, on_activate: Callable[[], None]) -> None:
        """Call `on_activate` when another launch asks to bring the app back."""
        if not _IS_WINDOWS or not self._event:
            return
        if self._watch_thread is not None and self._watch_thread.is_alive():
            return

        event = self._event

        def loop() -> None:
            while True:
                result = _kernel32.WaitForSingleObject(event, 500)
                if result == WAIT_OBJECT_0:
                    try:
                        on_activate()
                    except Exception:
                        LOGGER.exception("Callback single-instance fallita.")
                elif result == WAIT_FAILED:
                    return

        self._watch_thread = threading.Thread(
            target=loop, name="studiolights-instance", daemon=True
        )
        self._watch_thread.start()
