"""
Window management: minimize / maximize / restore / move / close windows or switch apps.

Uses native Win32 APIs for foreground window management, Z-order enumeration,
window placement, and focus control with SetForegroundWindow restriction handling.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import platform
import time
from typing import Any, Dict, List, Optional, Tuple

import win32api
import win32con
import win32gui
import win32process

from .registry import ToolError, register

SW_MINIMIZE = 6
SW_MAXIMIZE = 3
SW_RESTORE = 9
SW_SHOW = 5
SW_HIDE = 0

_INPUT_DESKTOP_ATTACHED = False


def _ensure_input_desktop() -> None:
    """Ensure current thread is attached to the interactive input desktop."""
    global _INPUT_DESKTOP_ATTACHED
    if _INPUT_DESKTOP_ATTACHED:
        return
    try:
        hdesk = ctypes.windll.user32.OpenInputDesktop(0, False, 0x01FF)
        if hdesk:
            if ctypes.windll.user32.SetThreadDesktop(hdesk):
                _INPUT_DESKTOP_ATTACHED = True
    except Exception:
        pass


def _get_all_windows() -> List[int]:
    """Enumerate all windows on the interactive input desktop in Z-order."""
    _ensure_input_desktop()
    hwnds: List[int] = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def proc(h, _):
        hwnds.append(h)
        return True

    cb = WNDENUMPROC(proc)
    try:
        ctypes.windll.user32.EnumWindows(cb, 0)
    except Exception:
        pass

    if not hwnds:
        try:
            hdesk = ctypes.windll.user32.OpenInputDesktop(0, False, 0x01FF)
            if hdesk:
                ctypes.windll.user32.EnumDesktopWindows(hdesk, cb, 0)
        except Exception:
            pass

    return hwnds


def _window_title(hwnd) -> str:
    try:
        buf = ctypes.create_unicode_buffer(512)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
        return buf.value.strip()
    except Exception:
        return ""


def _is_alt_tab_window(hwnd) -> bool:
    """Filter for genuine top-level application windows (similar to Alt+Tab)."""
    try:
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            return False
        title = _window_title(hwnd)
        if not title:
            return False
        # Exclude background system artifacts
        if title in (
            "Program Manager",
            "Windows Input Experience",
            "Settings",
            "Default IME",
            "MSCTFIME UI",
            "DesktopWindowXamlSource",
        ):
            return False

        # Filter cloaked windows (suspended UWP)
        cloaked = wintypes.DWORD()
        res = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
        )
        if res == 0 and cloaked.value != 0:
            return False

        # Filter tool windows
        ex_style = ctypes.windll.user32.GetWindowLongW(hwnd, win32con.GWL_EXSTYLE)
        if (ex_style & win32con.WS_EX_TOOLWINDOW) and not (
            ex_style & win32con.WS_EX_APPWINDOW
        ):
            return False

        rect = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        if (rect.right - rect.left) <= 0 or (rect.bottom - rect.top) <= 0:
            return False

        return True
    except Exception:
        return False


def _get_visible_windows() -> List[Tuple[int, str]]:
    """Return list of (hwnd, title) for all visible top-level application windows in Z-order."""
    hwnds = _get_all_windows()
    visible: List[Tuple[int, str]] = []
    for h in hwnds:
        if _is_alt_tab_window(h):
            visible.append((h, _window_title(h)))
    return visible


def _find_matching_windows(query: str) -> List[Tuple[int, str]]:
    """Return all matching visible windows with titles containing query in Z-order."""
    hwnds = _get_all_windows()
    matches: List[Tuple[int, str]] = []
    for h in hwnds:
        if ctypes.windll.user32.IsWindowVisible(h):
            title = _window_title(h)
            if title and query.lower() in title.lower():
                matches.append((h, title))
    return matches


def _get_foreground_window():
    if platform.system() != "Windows":
        return None
    try:
        _ensure_input_desktop()
        hwnd = win32gui.GetForegroundWindow()
        return hwnd if hwnd else None
    except Exception:
        return None


def _show_window(hwnd, cmd) -> None:
    try:
        _ensure_input_desktop()
        win32gui.ShowWindow(hwnd, cmd)
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"Could not change window state: {e}") from e


def _close_window_hwnd(hwnd) -> None:
    try:
        _ensure_input_desktop()
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"Could not close window: {e}") from e


def _focus(hwnd) -> bool:
    """Bring hwnd to foreground, bypassing Windows SetForegroundWindow restrictions.

    Returns True if target window successfully became the foreground window.
    """
    if platform.system() != "Windows":
        return False

    _ensure_input_desktop()

    # 1. If minimized, restore it first
    placement = win32gui.GetWindowPlacement(hwnd)
    if placement[1] == win32con.SW_SHOWMINIMIZED:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    else:
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)

    if win32gui.GetForegroundWindow() == hwnd:
        return True

    # 2. Try SwitchToThisWindow (Windows User32 helper specifically for window switching)
    try:
        ctypes.windll.user32.SwitchToThisWindow(hwnd, True)
    except Exception:
        pass

    time.sleep(0.08)
    if win32gui.GetForegroundWindow() == hwnd:
        return True

    # 3. AttachThreadInput to both foreground window thread and target thread
    fg_hwnd = win32gui.GetForegroundWindow()
    fg_tid, _ = win32process.GetWindowThreadProcessId(fg_hwnd) if fg_hwnd else (0, 0)
    target_tid, _ = win32process.GetWindowThreadProcessId(hwnd)
    cur_tid = win32api.GetCurrentThreadId()

    attached_fg = False
    attached_target = False

    if fg_tid and fg_tid != cur_tid:
        try:
            ctypes.windll.user32.AttachThreadInput(cur_tid, fg_tid, True)
            attached_fg = True
        except Exception:
            pass

    if target_tid and target_tid != cur_tid:
        try:
            ctypes.windll.user32.AttachThreadInput(cur_tid, target_tid, True)
            attached_target = True
        except Exception:
            pass

    try:
        ctypes.windll.user32.AllowSetForegroundWindow(-1)
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    finally:
        if attached_fg:
            try:
                ctypes.windll.user32.AttachThreadInput(cur_tid, fg_tid, False)
            except Exception:
                pass
        if attached_target:
            try:
                ctypes.windll.user32.AttachThreadInput(cur_tid, target_tid, False)
            except Exception:
                pass

    time.sleep(0.08)
    if win32gui.GetForegroundWindow() == hwnd:
        return True

    # 4. Alt key pulse bypass
    try:
        VK_MENU = 0x12
        KEYEVENTF_KEYUP = 0x0002
        ctypes.windll.user32.keybd_event(VK_MENU, 0, 0, 0)
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        ctypes.windll.user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    except Exception:
        pass

    time.sleep(0.08)
    return win32gui.GetForegroundWindow() == hwnd


def _resolve_target(args: Dict[str, Any]) -> Tuple[int, str]:
    """Pick the hwnd to operate on: explicit title + optional index, or foreground window."""
    _ensure_input_desktop()
    title: Optional[str] = (
        args.get("title")
        or args.get("name")
        or args.get("application")
        or args.get("app")
    )
    if title:
        matches = _find_matching_windows(str(title))
        if not matches:
            raise ToolError(f"No visible window with title containing '{title}'.")
        idx = int(args.get("index", args.get("window_index", 0)))
        if idx < 0 or idx >= len(matches):
            idx = 0
        return matches[idx]

    hwnd = _get_foreground_window()
    if not hwnd:
        raise ToolError("No active window found.")
    return hwnd, _window_title(hwnd)


@register("minimizeWindow")
def minimize_window(args: Dict[str, Any]) -> Dict[str, Any]:
    title: Optional[str] = (
        args.get("title")
        or args.get("name")
        or args.get("application")
        or args.get("app")
    )
    if title and "index" not in args and "window_index" not in args:
        matches = _find_matching_windows(str(title))
        minimizable = [
            m for m in matches
            if win32gui.GetWindowPlacement(m[0])[1] != win32con.SW_SHOWMINIMIZED
        ]
        if minimizable:
            hwnd, title_name = minimizable[0]
            _show_window(hwnd, SW_MINIMIZE)
            return {"result": f"Minimized window: {title_name}."}

    hwnd, title_res = _resolve_target(args)
    _show_window(hwnd, SW_MINIMIZE)
    return {"result": f"Minimized window: {title_res or 'active window'}."}


@register("maximizeWindow")
def maximize_window(args: Dict[str, Any]) -> Dict[str, Any]:
    title: Optional[str] = (
        args.get("title")
        or args.get("name")
        or args.get("application")
        or args.get("app")
    )
    if title and "index" not in args and "window_index" not in args:
        matches = _find_matching_windows(str(title))
        maximizable = [
            m for m in matches
            if win32gui.GetWindowPlacement(m[0])[1] != win32con.SW_SHOWMAXIMIZED
        ]
        if maximizable:
            hwnd, title_name = maximizable[0]
            _show_window(hwnd, SW_MAXIMIZE)
            return {"result": f"Maximized window: {title_name}."}

    hwnd, title_res = _resolve_target(args)
    _show_window(hwnd, SW_MAXIMIZE)
    return {"result": f"Maximized window: {title_res or 'active window'}."}


@register("restoreWindow")
def restore_window(args: Dict[str, Any]) -> Dict[str, Any]:
    """Restore a minimized window back to desktop or a maximized window back to normal size."""
    title: Optional[str] = (
        args.get("title")
        or args.get("name")
        or args.get("application")
        or args.get("app")
    )
    if title and "index" not in args and "window_index" not in args:
        matches = _find_matching_windows(str(title))
        restorable = [
            m for m in matches
            if win32gui.GetWindowPlacement(m[0])[1] in (win32con.SW_SHOWMINIMIZED, win32con.SW_SHOWMAXIMIZED)
        ]
        if restorable:
            hwnd, title_name = restorable[0]
            _show_window(hwnd, SW_RESTORE)
            _focus(hwnd)
            return {"result": f"Restored window: {title_name}."}

    hwnd, title_res = _resolve_target(args)
    _show_window(hwnd, SW_RESTORE)
    _focus(hwnd)
    return {"result": f"Restored window: {title_res or 'active window'}."}


@register("moveWindow")
def move_window(args: Dict[str, Any]) -> Dict[str, Any]:
    """Move and optionally resize a window."""
    hwnd, title = _resolve_target(args)

    # Ensure window is not minimized or maximized before moving
    placement = win32gui.GetWindowPlacement(hwnd)
    if placement[1] in (win32con.SW_SHOWMAXIMIZED, win32con.SW_SHOWMINIMIZED):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        time.sleep(0.1)

    rect = win32gui.GetWindowRect(hwnd)
    cur_w = rect[2] - rect[0]
    cur_h = rect[3] - rect[1]

    try:
        hmon = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST)
        mon_info = win32api.GetMonitorInfo(hmon)
        work_rect = mon_info.get("Work", mon_info.get("Monitor", (0, 0, 1920, 1080)))
        work_x = work_rect[0]
        work_y = work_rect[1]
        work_w = work_rect[2] - work_rect[0]
        work_h = work_rect[3] - work_rect[1]
    except Exception:
        work_x = 0
        work_y = 0
        work_w = 1920
        work_h = 1080

    w = int(args.get("width", cur_w))
    h = int(args.get("height", cur_h))

    pos_raw = (
        args.get("position")
        or args.get("direction")
        or args.get("to")
        or args.get("preset")
        or args.get("align")
        or ""
    )
    pos = str(pos_raw).lower().strip()
    x_val = args.get("x")
    y_val = args.get("y")

    if "center" in pos or "middle" in pos:
        x = work_x + max(0, (work_w - w) // 2)
        y = work_y + max(0, (work_h - h) // 2)
    elif "left" in pos:
        x = work_x
        y = work_y + max(0, (work_h - h) // 2) if y_val is None else int(y_val)
    elif "right" in pos:
        x = work_x + max(0, work_w - w)
        y = work_y + max(0, (work_h - h) // 2) if y_val is None else int(y_val)
    elif "top" in pos:
        x = work_x + max(0, (work_w - w) // 2) if x_val is None else int(x_val)
        y = work_y
    elif "bottom" in pos:
        x = work_x + max(0, (work_w - w) // 2) if x_val is None else int(x_val)
        y = work_y + max(0, work_h - h)
    else:
        if x_val is None and y_val is None:
            raise ToolError(
                "Parameters 'x' and 'y' (or position preset 'center', 'left', 'right') are required."
            )
        x = int(x_val if x_val is not None else rect[0])
        y = int(y_val if y_val is not None else rect[1])

    try:
        win32gui.MoveWindow(hwnd, x, y, w, h, True)
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"Could not move window: {e}") from e

    time.sleep(0.15)
    new_rect = win32gui.GetWindowRect(hwnd)

    # Verify that position changed or matches target
    tolerance = 15
    if abs(new_rect[0] - x) > tolerance or abs(new_rect[1] - y) > tolerance:
        if new_rect[0] == rect[0] and new_rect[1] == rect[1]:
            raise ToolError(
                f"Window did not move. Position remains ({new_rect[0]}, {new_rect[1]})."
            )

    return {
        "result": f"Moved window: {title or 'active window'} to ({new_rect[0]}, {new_rect[1]}).",
        "x": new_rect[0],
        "y": new_rect[1],
        "width": new_rect[2] - new_rect[0],
        "height": new_rect[3] - new_rect[1],
    }


@register("closeWindow")
def close_window(args: Dict[str, Any]) -> Dict[str, Any]:
    hwnd, title = _resolve_target(args)
    _close_window_hwnd(hwnd)
    return {"result": f"Closed window: {title or 'active window'}."}


@register("switchApplication")
def switch_application(args: Dict[str, Any]) -> Dict[str, Any]:
    """Focus a window by title, or cycle windows if no title given."""
    title = args.get("title") or args.get("application")
    if title:
        hwnd, matched_title = _resolve_target(args)
        if not _focus(hwnd):
            if win32gui.GetForegroundWindow() != hwnd:
                raise ToolError(
                    f"Could not bring '{matched_title}' to the foreground (focus was restricted by Windows)."
                )
        return {"result": f"Switched to: {matched_title}."}

    # No specific title -> cycle to the next visible top-level application window
    windows = _get_visible_windows()
    if not windows:
        raise ToolError("No visible application windows found to cycle between.")

    fg = win32gui.GetForegroundWindow()
    hwnds = [w[0] for w in windows]

    if fg in hwnds:
        current_idx = hwnds.index(fg)
        next_idx = (current_idx + 1) % len(hwnds)
    else:
        next_idx = 1 if len(hwnds) > 1 else 0

    next_hwnd, next_title = windows[next_idx]
    if not _focus(next_hwnd):
        if win32gui.GetForegroundWindow() != next_hwnd:
            raise ToolError(
                f"Could not switch to '{next_title}' (focus was restricted by Windows)."
            )

    return {"result": f"Switched to: {next_title}."}


__all__ = [
    "minimize_window",
    "maximize_window",
    "restore_window",
    "move_window",
    "close_window",
    "switch_application",
]
