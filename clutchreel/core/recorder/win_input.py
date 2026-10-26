"""Entrada de teclado de bajo nivel (SendInput con scancodes) y foco de ventana.

Se usa solo como último recurso cuando el puerto de consola de CS2 no responde.
No toca memoria del juego ni inyecta código: simula pulsaciones de teclado.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import time
from ctypes import wintypes

log = logging.getLogger(__name__)

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_UNICODE = 0x0004

SCANCODES = {
    "`": 0x29,
    "enter": 0x1C,
    "esc": 0x01,
    "f9": 0x43,
    "f10": 0x44,
    "f11": 0x57,
    "f12": 0x58,
}


if sys.platform == "win32":

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("padding", ctypes.c_byte * 32)]

    class _INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]

    _user32 = ctypes.WinDLL("user32", use_last_error=True)

    def _send(inputs: list[_INPUT]) -> None:
        arr = (_INPUT * len(inputs))(*inputs)
        sent = _user32.SendInput(len(inputs), arr, ctypes.sizeof(_INPUT))
        if sent != len(inputs):
            log.debug("SendInput envió %d/%d", sent, len(inputs))

    def _key_input(scan: int, up: bool = False, unicode_char: int | None = None) -> _INPUT:
        inp = _INPUT()
        inp.type = INPUT_KEYBOARD
        if unicode_char is not None:
            inp.u.ki = _KEYBDINPUT(0, unicode_char, KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0), 0, None)
        else:
            inp.u.ki = _KEYBDINPUT(0, scan, KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0), 0, None)
        return inp

    def press_scancode(name: str, hold: float = 0.05) -> None:
        scan = SCANCODES[name]
        _send([_key_input(scan)])
        time.sleep(hold)
        _send([_key_input(scan, up=True)])

    def type_text(text: str, delay: float = 0.01) -> None:
        for ch in text:
            code = ord(ch)
            _send([_key_input(0, unicode_char=code)])
            _send([_key_input(0, up=True, unicode_char=code)])
            time.sleep(delay)

    def _window_exe(hwnd: int) -> str:
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            import psutil

            return (psutil.Process(pid.value).name() or "").lower()
        except Exception:  # noqa: BLE001
            return ""

    def focus_window(title_contains: str, exe_name: str = "cs2.exe") -> bool:
        """Pone en primer plano la ventana del proceso ``exe_name`` cuyo título contiene ``title_contains``.

        Se comprueba el ejecutable para no confundir CS2 con, p. ej., una pestaña del
        navegador titulada «Counter-Strike 2».
        """
        found: list[int] = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def enum_proc(hwnd: int, _lparam: int) -> bool:
            if not _user32.IsWindowVisible(hwnd):
                return True
            length = _user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            _user32.GetWindowTextW(hwnd, buf, length + 1)
            if title_contains.lower() in buf.value.lower() and (not exe_name or _window_exe(hwnd) == exe_name.lower()):
                found.append(hwnd)
                return False
            return True

        _user32.EnumWindows(enum_proc, 0)
        if not found:
            return False
        hwnd = found[0]
        if _user32.IsIconic(hwnd):
            _user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        # Windows solo deja cambiar el primer plano a quien tiene la última entrada:
        # una pulsación de Alt (sin efecto en el juego) desbloquea SetForegroundWindow.
        _user32.keybd_event(0x12, 0, 0, 0)
        _user32.keybd_event(0x12, 0, KEYEVENTF_KEYUP, 0)
        _user32.SetForegroundWindow(hwnd)
        time.sleep(0.3)
        return bool(_user32.GetForegroundWindow() == hwnd)

else:  # pragma: no cover - solo Windows

    def press_scancode(name: str, hold: float = 0.05) -> None:
        raise OSError("Solo disponible en Windows")

    def type_text(text: str, delay: float = 0.01) -> None:
        raise OSError("Solo disponible en Windows")

    def focus_window(title_contains: str, exe_name: str = "cs2.exe") -> bool:
        return False
