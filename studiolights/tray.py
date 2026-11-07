"""Windows notification-area (system tray) icon implemented with Win32 APIs."""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
from collections.abc import Callable
from pathlib import Path

LOGGER = logging.getLogger("studiolights.tray")

_IS_WINDOWS = sys.platform == "win32"

WM_APP = 0x8000
WM_NULL = 0x0000
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B

NIM_ADD = 0x00000000
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
LR_DEFAULTSIZE = 0x00000040

MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
TPM_RETURNCMD = 0x0100
TPM_RIGHTBUTTON = 0x0002
TPM_NONOTIFY = 0x0080

IDI_APPLICATION = 32512

if _IS_WINDOWS:
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("hWnd", wintypes.HWND),
            ("uID", wintypes.UINT),
            ("uFlags", wintypes.UINT),
            ("uCallbackMessage", wintypes.UINT),
            ("hIcon", wintypes.HICON),
            ("szTip", wintypes.WCHAR * 128),
            ("dwState", wintypes.DWORD),
            ("dwStateMask", wintypes.DWORD),
            ("szInfo", wintypes.WCHAR * 256),
            ("uVersion", wintypes.UINT),
            ("szInfoTitle", wintypes.WCHAR * 64),
            ("dwInfoFlags", wintypes.DWORD),
            ("guidItem", GUID),
            ("hBalloonIcon", wintypes.HICON),
        ]

    WNDPROC = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]

    _user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    _user32.RegisterClassW.restype = wintypes.ATOM
    _user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
    _user32.UnregisterClassW.restype = wintypes.BOOL
    _user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        wintypes.LPVOID,
    ]
    _user32.CreateWindowExW.restype = wintypes.HWND
    _user32.DefWindowProcW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    _user32.DefWindowProcW.restype = ctypes.c_ssize_t
    _user32.DestroyWindow.argtypes = [wintypes.HWND]
    _user32.DestroyWindow.restype = wintypes.BOOL
    _user32.PostMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    _user32.PostMessageW.restype = wintypes.BOOL
    _user32.GetMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG),
        wintypes.HWND,
        wintypes.UINT,
        wintypes.UINT,
    ]
    _user32.GetMessageW.restype = ctypes.c_int
    _user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    _user32.TranslateMessage.restype = wintypes.BOOL
    _user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    _user32.DispatchMessageW.restype = ctypes.c_ssize_t
    _user32.PostQuitMessage.argtypes = [ctypes.c_int]
    _user32.PostQuitMessage.restype = None
    _user32.LoadImageW.argtypes = [
        wintypes.HINSTANCE,
        wintypes.LPCWSTR,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    _user32.LoadImageW.restype = wintypes.HANDLE
    _user32.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
    _user32.LoadIconW.restype = wintypes.HICON
    _user32.DestroyIcon.argtypes = [wintypes.HICON]
    _user32.DestroyIcon.restype = wintypes.BOOL
    _user32.CreatePopupMenu.argtypes = []
    _user32.CreatePopupMenu.restype = wintypes.HMENU
    _user32.AppendMenuW.argtypes = [
        wintypes.HMENU,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPCWSTR,
    ]
    _user32.AppendMenuW.restype = wintypes.BOOL
    _user32.TrackPopupMenu.argtypes = [
        wintypes.HMENU,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        ctypes.c_void_p,
    ]
    _user32.TrackPopupMenu.restype = ctypes.c_int
    _user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    _user32.GetCursorPos.restype = wintypes.BOOL
    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _user32.SetForegroundWindow.restype = wintypes.BOOL
    _user32.DestroyMenu.argtypes = [wintypes.HMENU]
    _user32.DestroyMenu.restype = wintypes.BOOL

    _shell32.Shell_NotifyIconW.argtypes = [
        wintypes.DWORD,
        ctypes.POINTER(NOTIFYICONDATAW),
    ]
    _shell32.Shell_NotifyIconW.restype = wintypes.BOOL

    _kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    _kernel32.GetModuleHandleW.restype = wintypes.HMODULE


class TrayIcon:
    """Small tray icon with an "Apri / Esci" menu.

    The icon lives on a dedicated thread with its own Win32 message loop, so the
    Tk main loop is never blocked. Callbacks run on that thread: the app feeds
    them into a thread-safe queue and polls it from Tk.
    """

    ICON_ID = 1
    MENU_OPEN = 1001
    MENU_EXIT = 1002
    CALLBACK_MESSAGE = WM_APP + 20

    def __init__(
        self,
        icon_path: Path,
        *,
        on_open: Callable[[], None],
        on_exit: Callable[[], None],
    ) -> None:
        self._icon_path = Path(icon_path)
        self._on_open = on_open
        self._on_exit = on_exit
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._hwnd: int | None = None
        self._hinstance: int | None = None
        self._class_name = f"StudioLightsTray_{id(self)}"
        self._icon: int = 0
        self._icon_owned = False
        self._added = False
        self._wndproc = WNDPROC(self._handle_message) if _IS_WINDOWS else None

    # ------------------------------------------------------------- lifecycle
    def start(self) -> bool:
        if not _IS_WINDOWS:
            return False
        if self._thread is not None and self._thread.is_alive():
            return self._added
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._run, name="studiolights-tray", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(3.0):
            LOGGER.warning("Timeout durante l'avvio dell'icona nella tray.")
            return False
        return self._added

    def stop(self) -> None:
        if not _IS_WINDOWS:
            return
        hwnd = self._hwnd
        if hwnd:
            _user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        thread = self._thread
        if (
            thread is not None
            and thread.is_alive()
            and thread is not threading.current_thread()
        ):
            thread.join(timeout=2.0)
        self._thread = None

    # ---------------------------------------------------------------- thread
    def _run(self) -> None:
        try:
            self._hinstance = _kernel32.GetModuleHandleW(None)
            wc = WNDCLASSW()
            wc.lpfnWndProc = self._wndproc
            wc.hInstance = self._hinstance
            wc.lpszClassName = self._class_name
            if not _user32.RegisterClassW(ctypes.byref(wc)):
                LOGGER.warning(
                    "RegisterClassW tray fallito (errore %s).",
                    ctypes.get_last_error(),
                )
                return
            hwnd = _user32.CreateWindowExW(
                0,
                self._class_name,
                "Studio Lights",
                0,
                0,
                0,
                0,
                0,
                None,
                None,
                self._hinstance,
                None,
            )
            if not hwnd:
                LOGGER.warning(
                    "CreateWindowExW tray fallito (errore %s).",
                    ctypes.get_last_error(),
                )
                return
            self._hwnd = hwnd
            self._add_icon()
            self._ready.set()
            msg = wintypes.MSG()
            while True:
                result = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result <= 0:
                    break
                _user32.TranslateMessage(ctypes.byref(msg))
                _user32.DispatchMessageW(ctypes.byref(msg))
        except Exception:
            LOGGER.exception("Errore nel thread della tray.")
        finally:
            if self._hwnd:
                self._remove_icon()
                _user32.DestroyWindow(self._hwnd)
                self._hwnd = None
            if self._hinstance:
                _user32.UnregisterClassW(self._class_name, self._hinstance)
                self._hinstance = None
            self._ready.set()

    # --------------------------------------------------------------- message
    def _handle_message(self, hwnd, message, wparam, lparam):
        try:
            if message == self.CALLBACK_MESSAGE:
                if wparam == self.ICON_ID:
                    if lparam == WM_LBUTTONUP:
                        self._safe(self._on_open)
                    elif lparam in (WM_RBUTTONUP, WM_CONTEXTMENU):
                        self._show_menu()
                    return 0
            elif message == WM_CLOSE:
                self._remove_icon()
                _user32.DestroyWindow(hwnd)
                return 0
            elif message == WM_DESTROY:
                if self._hwnd == hwnd:
                    self._hwnd = None
                _user32.PostQuitMessage(0)
                return 0
        except Exception:
            LOGGER.exception("Errore nel callback della tray.")
        return _user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _show_menu(self) -> None:
        if not self._hwnd:
            return
        point = wintypes.POINT()
        _user32.GetCursorPos(ctypes.byref(point))
        menu = _user32.CreatePopupMenu()
        if not menu:
            return
        try:
            _user32.AppendMenuW(menu, MF_STRING, self.MENU_OPEN, "Apri Studio Lights")
            _user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            _user32.AppendMenuW(menu, MF_STRING, self.MENU_EXIT, "Esci")
            _user32.SetForegroundWindow(self._hwnd)
            command = _user32.TrackPopupMenu(
                menu,
                TPM_RETURNCMD | TPM_RIGHTBUTTON | TPM_NONOTIFY,
                point.x,
                point.y,
                0,
                self._hwnd,
                None,
            )
            _user32.PostMessageW(self._hwnd, WM_NULL, 0, 0)
            if command == self.MENU_OPEN:
                self._safe(self._on_open)
            elif command == self.MENU_EXIT:
                self._safe(self._on_exit)
        finally:
            _user32.DestroyMenu(menu)

    # ------------------------------------------------------------------ icon
    def _add_icon(self) -> None:
        if not self._hwnd:
            return
        if not self._icon:
            handle = 0
            if self._icon_path.exists():
                handle = _user32.LoadImageW(
                    None,
                    str(self._icon_path),
                    IMAGE_ICON,
                    0,
                    0,
                    LR_LOADFROMFILE | LR_DEFAULTSIZE,
                )
                self._icon_owned = bool(handle)
            if not handle:
                handle = _user32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))
                self._icon_owned = False
            self._icon = int(handle or 0)
        nid = self._make_nid()
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = self.CALLBACK_MESSAGE
        nid.hIcon = self._icon
        nid.szTip = "Studio Lights — controllo luci LAN"
        self._added = bool(_shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))
        if not self._added:
            LOGGER.warning(
                "Shell_NotifyIcon NIM_ADD fallito (errore %s).",
                ctypes.get_last_error(),
            )

    def _remove_icon(self) -> None:
        if self._added and self._hwnd:
            nid = self._make_nid()
            _shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
        self._added = False
        if self._icon and self._icon_owned:
            _user32.DestroyIcon(self._icon)
        self._icon = 0
        self._icon_owned = False

    def _make_nid(self) -> NOTIFYICONDATAW:
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = self.ICON_ID
        return nid

    @staticmethod
    def _safe(callback: Callable[[], None]) -> None:
        try:
            callback()
        except Exception:
            LOGGER.exception("Callback tray fallita.")
