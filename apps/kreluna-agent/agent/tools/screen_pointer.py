"""Mouse visibile, limitato a coordinate già ricavate dalla finestra controllata."""

from __future__ import annotations

import ctypes
import ctypes.util
import sys
import time


class CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


def _inside(x: int, y: int, width: int, height: int) -> bool:
    return 0 <= x < width and 0 <= y < height


def move_and_click(
    x: int,
    y: int,
    *,
    screen_width: int,
    screen_height: int,
    start_x: int | None = None,
    start_y: int | None = None,
    click: bool = True,
) -> bool:
    """Muove il puntatore davvero. Non accetta coordinate fuori schermo."""

    x, y = int(x), int(y)
    if not _inside(x, y, screen_width, screen_height):
        return False
    sx = x if start_x is None else max(0, min(int(start_x), screen_width - 1))
    sy = y if start_y is None else max(0, min(int(start_y), screen_height - 1))
    if sys.platform == "darwin":
        return _mac_move(sx, sy, x, y, click)
    if sys.platform == "win32":
        return _windows_move(sx, sy, x, y, click)
    return False


def _points(sx: int, sy: int, x: int, y: int, steps: int = 12):
    for index in range(1, steps + 1):
        ratio = index / steps
        yield CGPoint(sx + (x - sx) * ratio, sy + (y - sy) * ratio)


def _mac_move(sx: int, sy: int, x: int, y: int, click: bool) -> bool:
    path = ctypes.util.find_library("ApplicationServices")
    if not path:
        return False
    quartz = ctypes.CDLL(path)
    quartz.CGWarpMouseCursorPosition.argtypes = [CGPoint]
    quartz.CGWarpMouseCursorPosition.restype = ctypes.c_int32
    for point in _points(sx, sy, x, y):
        quartz.CGWarpMouseCursorPosition(point)
        time.sleep(0.012)
    if not click:
        return True
    quartz.CGEventCreateMouseEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, CGPoint, ctypes.c_uint32]
    quartz.CGEventCreateMouseEvent.restype = ctypes.c_void_p
    quartz.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    quartz.CFRelease.argtypes = [ctypes.c_void_p]
    for kind in (1, 2):  # left mouse down, left mouse up
        event = quartz.CGEventCreateMouseEvent(None, kind, CGPoint(x, y), 0)
        if not event:
            return False
        quartz.CGEventPost(0, event)
        quartz.CFRelease(event)
    return True


def _windows_move(sx: int, sy: int, x: int, y: int, click: bool) -> bool:
    user32 = ctypes.windll.user32
    for point in _points(sx, sy, x, y):
        user32.SetCursorPos(round(point.x), round(point.y))
        time.sleep(0.012)
    if click:
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        user32.mouse_event(0x0004, 0, 0, 0, 0)
    return True
