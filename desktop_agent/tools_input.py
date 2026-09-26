"""
Desktop input automation: mouse movement, mouse clicks, keyboard typing, key presses, and scrolling.

Uses pyautogui as the native input backend.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

try:
    import pyautogui
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0.02
except ImportError:
    pyautogui = None

from .registry import ToolError, register


def _check_backend() -> None:
    if pyautogui is None:
        raise ToolError("pyautogui is not installed in the environment.")


@register("mouseMove")
def mouse_move(args: Dict[str, Any]) -> Dict[str, Any]:
    """Move mouse cursor to (x, y) coordinates."""
    _check_backend()
    x_val = args.get("x")
    y_val = args.get("y")
    if x_val is None or y_val is None:
        raise ToolError("Parameters 'x' and 'y' are required.")

    try:
        x = int(x_val)
        y = int(y_val)
        pyautogui.moveTo(x, y)
        cur_pos = pyautogui.position()
        return {
            "result": f"Moved mouse to ({cur_pos.x}, {cur_pos.y}).",
            "x": cur_pos.x,
            "y": cur_pos.y,
        }
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"Could not move mouse: {e}") from e


@register("mouseClick")
def mouse_click(args: Dict[str, Any]) -> Dict[str, Any]:
    """Click mouse button, optionally moving to (x, y) first."""
    _check_backend()
    x_val = args.get("x")
    y_val = args.get("y")
    button_val = str(args.get("button", "left")).lower().strip()
    clicks = int(args.get("clicks", 1))

    if button_val in ("double", "double_click", "doubleclick"):
        button = "left"
        clicks = 2
    elif button_val in ("right", "secondary"):
        button = "right"
    elif button_val in ("middle", "center"):
        button = "middle"
    else:
        button = "left"

    try:
        if x_val is not None and y_val is not None:
            x = int(x_val)
            y = int(y_val)
            pyautogui.click(x=x, y=y, clicks=clicks, button=button)
        else:
            pyautogui.click(clicks=clicks, button=button)

        cur_pos = pyautogui.position()
        action_name = "Double-clicked" if clicks == 2 else f"Clicked {button} button"
        return {
            "result": f"{action_name} at ({cur_pos.x}, {cur_pos.y}).",
            "x": cur_pos.x,
            "y": cur_pos.y,
            "button": button,
            "clicks": clicks,
        }
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"Could not click mouse: {e}") from e


@register("typeText")
def type_text(args: Dict[str, Any]) -> Dict[str, Any]:
    """Type text into the active focused window."""
    _check_backend()
    text = args.get("text")
    if text is None:
        raise ToolError("Parameter 'text' is required.")

    press_enter = bool(args.get("press_enter", args.get("enter", False)))
    interval = float(args.get("interval", 0.0))

    try:
        text_str = str(text)
        pyautogui.write(text_str, interval=interval)
        if press_enter:
            time.sleep(0.05)
            pyautogui.press("enter")

        return {
            "result": f"Typed text ({len(text_str)} chars){' and pressed Enter' if press_enter else ''}.",
            "text": text_str if len(text_str) <= 100 else text_str[:100] + "…",
            "press_enter": press_enter,
        }
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"Could not type text: {e}") from e


@register("pressKey")
def press_key(args: Dict[str, Any]) -> Dict[str, Any]:
    """Press a single key or key combination (e.g. Enter, Tab, Escape, ctrl+home, ctrl+end)."""
    _check_backend()
    key_val = args.get("key") or args.get("name")
    if not key_val:
        raise ToolError("Parameter 'key' is required.")

    key = str(key_val).lower().strip()
    key_aliases = {
        "return": "enter",
        "esc": "escape",
        "del": "delete",
        "ctrl": "ctrl",
        "control": "ctrl",
        "alt": "alt",
        "shift": "shift",
        "windows": "win",
        "super": "win",
        "cmd": "win",
        "spacebar": "space",
    }

    if "+" in key:
        raw_parts = [k.strip() for k in key.split("+") if k.strip()]
        norm_parts = [key_aliases.get(p, p) for p in raw_parts]
        try:
            pyautogui.hotkey(*norm_parts)
            return {"result": f"Pressed key combination: {'+'.join(norm_parts)}."}
        except Exception as e:  # noqa: BLE001
            raise ToolError(f"Could not press hotkey '{key}': {e}") from e

    norm_key = key_aliases.get(key, key)
    try:
        pyautogui.press(norm_key)
        return {"result": f"Pressed key: {norm_key}."}
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"Could not press key '{key}': {e}") from e


def _get_safe_foreground_center() -> tuple[int, int]:
    """Find a safe center coordinate inside the foreground window's client/content area."""
    try:
        screen_w, screen_h = pyautogui.size()
    except Exception:
        screen_w, screen_h = 1920, 1080

    try:
        import win32gui
        hwnd = win32gui.GetForegroundWindow()
        if hwnd:
            rect = win32gui.GetWindowRect(hwnd)  # (left, top, right, bottom)
            l, t, r, b = rect
            # Clamp to screen bounds
            l = max(0, min(screen_w - 1, l))
            r = max(0, min(screen_w, r))
            t = max(0, min(screen_h - 1, t))
            b = max(0, min(screen_h, b))
            if (r - l) > 80 and (b - t) > 80:
                # Content center (offset down slightly to stay clear of tab bars / address bars)
                center_x = l + (r - l) // 2
                center_y = t + int((b - t) * 0.55)
                return center_x, center_y
    except Exception:
        pass

    return screen_w // 2, screen_h // 2


@register("mouseScroll")
def mouse_scroll(args: Dict[str, Any]) -> Dict[str, Any]:
    """Scroll the mouse wheel in the active window or at specific coordinates."""
    _check_backend()

    scroll_sizes = {
        "small": 5,
        "little": 5,
        "slight": 5,
        "normal": 20,
        "medium": 20,
        "large": 40,
        "lot": 40,
    }

    size_val = args.get("size")
    if size_val and str(size_val).lower().strip() in scroll_sizes:
        amount = scroll_sizes[str(size_val).lower().strip()]
    else:
        amount_val = args.get("amount", args.get("clicks", args.get("lines", 20)))
        try:
            amount = int(amount_val)
        except Exception:
            amount = 20

    direction = str(args.get("direction", "down")).lower().strip()
    x_val = args.get("x")
    y_val = args.get("y")
    scroll_kwargs: Dict[str, int] = {}
    if x_val is not None and y_val is not None:
        try:
            scroll_kwargs["x"] = int(x_val)
            scroll_kwargs["y"] = int(y_val)
        except Exception:
            pass
    else:
        # When x/y not provided, move cursor to safe content center of foreground window
        target_x, target_y = _get_safe_foreground_center()
        try:
            pyautogui.moveTo(target_x, target_y)
            scroll_kwargs["x"] = target_x
            scroll_kwargs["y"] = target_y
        except Exception:
            pass

    try:
        # In pyautogui.scroll, positive is UP/RIGHT, negative is DOWN/LEFT.
        # Windows standard WHEEL_DELTA is 120 per notch.
        delta = abs(amount) * 120
        if "up" in direction:
            pyautogui.scroll(delta, **scroll_kwargs)
        elif "down" in direction:
            pyautogui.scroll(-delta, **scroll_kwargs)
        elif "left" in direction:
            pyautogui.hscroll(-delta, **scroll_kwargs)
        elif "right" in direction:
            pyautogui.hscroll(delta, **scroll_kwargs)
        else:
            pyautogui.scroll(-delta, **scroll_kwargs)

        target_str = f" at ({scroll_kwargs['x']}, {scroll_kwargs['y']})" if scroll_kwargs else ""
        return {"result": f"Scrolled {direction} by {abs(amount)}{target_str}."}
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"Could not scroll: {e}") from e


__all__ = [
    "mouse_move",
    "mouse_click",
    "type_text",
    "press_key",
    "mouse_scroll",
]
