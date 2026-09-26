"""
Screenshot & screen-reading: capture, save, OCR, and read on-screen text.

  takeScreenshot    -> capture full screen, return metadata (+ small base64)
  saveScreenshot    -> capture & write to a file under the Screenshots folder
  analyzeScreenshot-> capture, run OCR (pytesseract), return extracted text
  readScreen        -> OCR the active window region + name the active window

OCR requires the Tesseract OCR engine + the pytesseract wrapper. If either is
missing, the OCR tools return a graceful 'unavailable' message instead of
crashing; non-OCR capture still works.
"""

from __future__ import annotations

import base64
import ctypes
import io
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .registry import ToolError, register
from .tools_files import PICTURES_DIR, _ensure_safe, _resolve_file, _resolve_folder

SCREENSHOTS_DIR = PICTURES_DIR / "AuraScreenshots"


def _enable_dpi_awareness() -> None:
    """Ensure process DPI awareness is active so window/screen coords match physical pixels."""
    if sys.platform != "win32":
        return
    try:
        # Per-monitor DPI awareness v2 (Windows 10 1703+)
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


_enable_dpi_awareness()


def _ensure_desktop_access() -> None:
    """Ensure the calling thread is attached to the active interactive input desktop."""
    if sys.platform != "win32":
        return
    try:
        user32 = ctypes.windll.user32
        hdesk = user32.OpenInputDesktop(0, False, 0x01FF)
        if hdesk:
            user32.SetThreadDesktop(hdesk)
            user32.CloseDesktop(hdesk)
    except Exception:
        pass


def _capture() -> "Any":
    """Capture the full virtual screen as a PIL Image."""
    try:
        from PIL import ImageGrab

        _ensure_desktop_access()
        img = ImageGrab.grab(all_screens=True, include_layered_windows=True)
        return img
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"Screen capture failed: {e}")


def _capture_region(bbox):
    try:
        from PIL import ImageGrab

        _ensure_desktop_access()
        return ImageGrab.grab(bbox=bbox, all_screens=False, include_layered_windows=True)
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"Region capture failed: {e}")


def _active_window_bbox():
    """Return (left, top, right, bottom) of the foreground window, or None."""
    try:
        import win32gui

        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None
        rect = win32gui.GetWindowRect(hwnd)  # (l, t, r, b)
        return rect
    except Exception:
        return None


def _active_window_title() -> str:
    try:
        import win32gui

        hwnd = win32gui.GetForegroundWindow()
        return win32gui.GetWindowText(hwnd) if hwnd else ""
    except Exception:
        return ""


def _image_to_b64(img, fmt="PNG", quality=70) -> str:
    buf = io.BytesIO()
    if fmt.upper() == "JPEG":
        img.convert("RGB").save(buf, format="JPEG", quality=quality)
    else:
        img.save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _image_size_kb(img) -> int:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return len(buf.getvalue()) // 1024


def _run_ocr(img) -> str:
    try:
        import pytesseract
    except ImportError:
        raise ToolError(
            "OCR unavailable: the 'pytesseract' package is not installed."
        )
    # Ensure the Tesseract binary is discoverable.
    exe = os.environ.get("TESSERACT_PATH") or _find_tesseract_exe()
    if exe:
        pytesseract.pytesseract.tesseract_cmd = exe
    try:
        return pytesseract.image_to_string(img)
    except Exception as e:  # noqa: BLE001
        raise ToolError(
            "OCR failed (is the Tesseract engine installed?). Detail: " + str(e)
        )


def _find_tesseract_exe() -> Optional[str]:
    candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def _trim_ocr(text: str, max_chars: int = 1500) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    out = "\n".join(lines)
    if len(out) > max_chars:
        out = out[:max_chars] + "…"
    return out


@register("takeScreenshot")
def take_screenshot(args: Dict[str, Any]) -> Dict[str, Any]:
    img = _capture()
    include_image = bool(args.get("include_image", False))
    result: Dict[str, Any] = {
        "result": f"Captured screen ({img.width}x{img.height}).",
        "width": img.width,
        "height": img.height,
    }
    if include_image:
        # Downscale + JPEG to keep payload small for the WS bridge.
        max_dim = int(args.get("max_dim", 1280))
        if max(img.size) > max_dim:
            ratio = max_dim / max(img.size)
            img_small = img.resize(
                (max(1, int(img.width * ratio)), max(1, int(img.height * ratio)))
            )
        else:
            img_small = img
        result["image_base64"] = _image_to_b64(img_small, fmt="JPEG", quality=60)
        result["image_mime"] = "image/jpeg"
    return result


@register("saveScreenshot")
def save_screenshot(args: Dict[str, Any]) -> Dict[str, Any]:
    img = _capture()
    stamp = time.strftime("%Y%m%d-%H%M%S")

    raw_path = args.get("path") or args.get("filename")
    folder = args.get("folder")
    name = args.get("name")

    if raw_path:
        raw_str = str(raw_path).strip()
        if folder:
            base_folder = _resolve_folder(str(folder))
            out_path = (base_folder / raw_str).resolve()
        else:
            if "/" not in raw_str and "\\" not in raw_str:
                SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
                out_path = (SCREENSHOTS_DIR / raw_str).resolve()
            else:
                out_path = _resolve_file(raw_str)
    elif folder:
        base_folder = _resolve_folder(str(folder))
        base_folder.mkdir(parents=True, exist_ok=True)
        fname = f"{name}-{stamp}.png" if name else f"screenshot-{stamp}.png"
        out_path = (base_folder / fname).resolve()
    else:
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        fname = f"{name}-{stamp}.png" if name else f"screenshot-{stamp}.png"
        out_path = (SCREENSHOTS_DIR / fname).resolve()

    if out_path.suffix.lower() not in (".png", ".jpg", ".jpeg"):
        out_path = out_path.with_suffix(".png")

    _ensure_safe(out_path, allow_anywhere=bool(args.get("allow_anywhere", False)))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, format="PNG")

    result: Dict[str, Any] = {
        "result": f"Saved screenshot to {out_path}.",
        "path": str(out_path),
        "width": img.width,
        "height": img.height,
    }

    if bool(args.get("include_image", False)):
        max_dim = int(args.get("max_dim", 1280))
        if max(img.size) > max_dim:
            ratio = max_dim / max(img.size)
            img_small = img.resize(
                (max(1, int(img.width * ratio)), max(1, int(img.height * ratio)))
            )
        else:
            img_small = img
        result["image_base64"] = _image_to_b64(img_small, fmt="JPEG", quality=60)
        result["image_mime"] = "image/jpeg"

    return result


@register("analyzeScreenshot")
def analyze_screenshot(args: Dict[str, Any]) -> Dict[str, Any]:
    img = _capture()
    try:
        text = _run_ocr(img)
    except ToolError as e:
        text = f"OCR unavailable: {e.message}"

    # Downscale + JPEG to keep payload lightweight for Gemini Live visual context
    max_dim = int(args.get("max_dim", 1280))
    if max(img.size) > max_dim:
        ratio = max_dim / max(img.size)
        img_small = img.resize(
            (max(1, int(img.width * ratio)), max(1, int(img.height * ratio)))
        )
    else:
        img_small = img

    return {
        "result": "Screenshot captured and analyzed.",
        "text": _trim_ocr(text, int(args.get("max_chars", 1500))),
        "width": img.width,
        "height": img.height,
        "image_base64": _image_to_b64(img_small, fmt="JPEG", quality=60),
        "image_mime": "image/jpeg",
    }


@register("readScreen")
def read_screen(args: Dict[str, Any]) -> Dict[str, Any]:
    """OCR the active window and report its title + visible text."""
    title = _active_window_title()
    bbox = _active_window_bbox()
    if bbox:
        try:
            img = _capture_region(bbox)
        except ToolError:
            img = _capture()
    else:
        img = _capture()
    try:
        text = _run_ocr(img)
        visible = _trim_ocr(text, int(args.get("max_chars", 1500))) or "(no readable text)"
    except ToolError as e:
        return {
            "result": f"Active window: {title or 'unknown'}. OCR unavailable: {e.message}",
            "active_window": title,
        }
    return {
        "result": f"Active window '{title or 'unknown'}' contains readable text.",
        "active_window": title,
        "text": visible,
    }


__all__ = [
    "take_screenshot",
    "save_screenshot",
    "analyze_screenshot",
    "read_screen",
]
