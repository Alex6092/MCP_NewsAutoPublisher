"""Énumération des fenêtres Windows (ctypes, sans dépendance)."""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass


class CaptureError(Exception):
    pass


@dataclass
class WindowInfo:
    title: str
    x: int
    y: int
    width: int
    height: int
    pid: int

    def as_dict(self) -> dict:
        return asdict(self)


def is_windows() -> bool:
    return sys.platform == "win32"


def list_windows() -> list[WindowInfo]:
    if not is_windows():
        raise CaptureError("La liste des fenêtres n'est disponible que sous Windows.")
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    dwmapi = ctypes.windll.dwmapi  # type: ignore[attr-defined]
    try:  # coordonnées en pixels physiques (écrans à 125 %, 150 %…)
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # type: ignore[attr-defined]
    except Exception:
        pass

    windows: list[WindowInfo] = []
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        rect = wintypes.RECT()
        # DWMWA_EXTENDED_FRAME_BOUNDS = 9 : rectangle visible, sans les bordures invisibles.
        if dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)) != 0:
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w < 200 or h < 150:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        windows.append(WindowInfo(buf.value, rect.left, rect.top, w, h, pid.value))
        return True

    user32.EnumWindows(enum_proc(callback), 0)
    return windows


def find_window(title_part: str) -> WindowInfo:
    needle = title_part.lower()
    candidates = [w for w in list_windows() if needle in w.title.lower()]
    if not candidates:
        raise CaptureError(
            f"Aucune fenêtre visible ne contient « {title_part} ». Lance le jeu ou l'éditeur "
            "(fenêtré ou plein écran fenêtré), ou appelle list_windows pour voir les titres."
        )
    # La plus grande fenêtre correspondante est en général la bonne (jeu / éditeur principal).
    return max(candidates, key=lambda w: w.width * w.height)
