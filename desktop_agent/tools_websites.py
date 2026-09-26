"""
Website control: open named sites or arbitrary URLs in the default browser.

Uses the OS default-browser handler so the user's real Chrome/Edge/Firefox
opens at the requested destination (independent of the Playwright automation
browser and the in-app holographic BrowserAgent).
"""

from __future__ import annotations

import time
import webbrowser
from typing import Any, Dict
from urllib.parse import quote

from .registry import ToolError, register

# Named shortcuts the model can request by friendly name.
SITE_URLS: Dict[str, str] = {
    "youtube": "https://www.youtube.com",
    "gmail": "https://mail.google.com",
    "chatgpt": "https://chatgpt.com",
    "openai": "https://chat.openai.com",
    "google": "https://www.google.com",
    "github": "https://github.com",
    "wikipedia": "https://www.wikipedia.org",
    "reddit": "https://www.reddit.com",
    "twitter": "https://twitter.com",
    "x": "https://x.com",
    "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "linkedin": "https://www.linkedin.com",
    "maps": "https://maps.google.com",
    "translate": "https://translate.google.com",
    "drive": "https://drive.google.com",
    "calendar": "https://calendar.google.com",
    "amazon": "https://www.amazon.com",
    "netflix": "https://www.netflix.com",
    "spotify": "https://open.spotify.com",
    "stack overflow": "https://stackoverflow.com",
    "stackoverflow": "https://stackoverflow.com",
    "huggingface": "https://huggingface.co",
}


def _normalize_url(raw: str) -> str:
    url = raw.strip()
    if not url:
        raise ToolError("Empty URL.")
    if "://" not in url:
        # Treat bare "youtube.com" as https://youtube.com
        url = "https://" + url
    return url


def open_url(url: str) -> str:
    """Open a URL in the default browser; returns the resolved URL."""
    url = _normalize_url(url)
    ok = webbrowser.open(url, new=2)  # new tab in a new window group if possible
    if not ok:
        raise ToolError(f"Failed to open default browser for {url}.")
    return url


@register("openWebsite")
def open_website(args: Dict[str, Any]) -> Dict[str, Any]:
    name = args.get("name")
    url = args.get("url")
    if name and not url:
        key = str(name).strip().lower()
        if key in SITE_URLS:
            url = SITE_URLS[key]
        else:
            # Treat the name itself as a domain if it looks like one.
            url = str(name)
    if not url and not name:
        raise ToolError("Provide 'name' (e.g. 'youtube') or 'url'.")
    resolved = open_url(url or str(name))
    return {"result": f"Opened {resolved} in the default browser."}


# Expose for sibling modules (tools_search).
def _build_search_url(engine: str, query: str) -> str:
    q = quote(query)
    base = {
        "google": f"https://www.google.com/search?q={q}",
        "youtube": f"https://www.youtube.com/results?search_query={q}",
        "github": f"https://github.com/search?q={q}&type=repositories",
        "chatgpt": f"https://www.google.com/search?q={q}",  # no search API
        "duckduckgo": f"https://duckduckgo.com/?q={q}",
        "bing": f"https://www.bing.com/search?q={q}",
        "amazon": f"https://www.amazon.com/s?k={q}",
        "wikipedia": f"https://en.wikipedia.org/w/index.php?search={q}",
    }
    if engine not in base:
        raise ToolError(
            f"Unsupported search engine '{engine}'. Choose from "
            f"{', '.join(sorted(base))}."
        )
    return base[engine]


SUPPORTED_BROWSER_PROCESSES = {
    "opera.exe",
    "opera_gx.exe",
    "chrome.exe",
    "msedge.exe",
    "brave.exe",
    "firefox.exe",
    "vivaldi.exe",
    "arc.exe",
}

SUPPORTED_BROWSER_TITLE_MARKERS = [
    " - opera",
    " - google chrome",
    " - microsoft​ edge",
    " - brave",
    " - mozilla firefox",
    " - vivaldi",
    " - arc",
]


def _is_browser_window(hwnd: int, title: str) -> tuple[bool, str]:
    """Check if hwnd belongs to a supported browser. Returns (is_browser, browser_name)."""
    try:
        import win32process
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid:
            try:
                import psutil
                pname = psutil.Process(pid).name().lower()
                if pname in SUPPORTED_BROWSER_PROCESSES:
                    clean_name = pname.replace(".exe", "").replace("_gx", " GX").capitalize()
                    return True, clean_name
            except Exception:
                pass
    except Exception:
        pass

    t_lower = title.lower()
    for marker in SUPPORTED_BROWSER_TITLE_MARKERS:
        if marker in t_lower:
            return True, marker.replace(" - ", "").strip().title()

    return False, ""


def _send_ctrl_w() -> None:
    """Send Ctrl+W shortcut to close the active tab in the focused browser window."""
    try:
        import pyautogui
        pyautogui.hotkey("ctrl", "w")
    except Exception:
        import ctypes
        VK_CONTROL = 0x11
        VK_W = 0x57
        KEYEVENTF_KEYUP = 0x0002
        ctypes.windll.user32.keybd_event(VK_CONTROL, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_W, 0, 0, 0)
        time.sleep(0.05)
        ctypes.windll.user32.keybd_event(VK_W, 0, KEYEVENTF_KEYUP, 0)
        ctypes.windll.user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def _send_next_tab() -> None:
    """Send Ctrl+PageDown to switch to the next tab in the focused browser."""
    try:
        import pyautogui
        pyautogui.hotkey("ctrl", "pagedown")
    except Exception:
        import ctypes
        VK_CONTROL = 0x11
        VK_NEXT = 0x22  # Page Down
        KEYEVENTF_KEYUP = 0x0002
        ctypes.windll.user32.keybd_event(VK_CONTROL, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_NEXT, 0, 0, 0)
        time.sleep(0.05)
        ctypes.windll.user32.keybd_event(VK_NEXT, 0, KEYEVENTF_KEYUP, 0)
        ctypes.windll.user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def _send_prev_tab() -> None:
    """Send Ctrl+PageUp to switch to the previous tab in the focused browser."""
    try:
        import pyautogui
        pyautogui.hotkey("ctrl", "pageup")
    except Exception:
        import ctypes
        VK_CONTROL = 0x11
        VK_PRIOR = 0x21  # Page Up
        KEYEVENTF_KEYUP = 0x0002
        ctypes.windll.user32.keybd_event(VK_CONTROL, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_PRIOR, 0, 0, 0)
        time.sleep(0.05)
        ctypes.windll.user32.keybd_event(VK_PRIOR, 0, KEYEVENTF_KEYUP, 0)
        ctypes.windll.user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def _send_alt_left() -> None:
    """Send Alt+Left shortcut to navigate back in the focused browser window."""
    try:
        import pyautogui
        pyautogui.hotkey("alt", "left")
    except Exception:
        import ctypes
        VK_MENU = 0x12
        VK_LEFT = 0x25
        KEYEVENTF_KEYUP = 0x0002
        ctypes.windll.user32.keybd_event(VK_MENU, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_LEFT, 0, 0, 0)
        time.sleep(0.05)
        ctypes.windll.user32.keybd_event(VK_LEFT, 0, KEYEVENTF_KEYUP, 0)
        ctypes.windll.user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)


def _send_alt_right() -> None:
    """Send Alt+Right shortcut to navigate forward in the focused browser window."""
    try:
        import pyautogui
        pyautogui.hotkey("alt", "right")
    except Exception:
        import ctypes
        VK_MENU = 0x12
        VK_RIGHT = 0x27
        KEYEVENTF_KEYUP = 0x0002
        ctypes.windll.user32.keybd_event(VK_MENU, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_RIGHT, 0, 0, 0)
        time.sleep(0.05)
        ctypes.windll.user32.keybd_event(VK_RIGHT, 0, KEYEVENTF_KEYUP, 0)
        ctypes.windll.user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)


def _matches_tab_query(title: str, query: str) -> bool:
    """Case-insensitive check if window title matches website or tab query."""
    if not query:
        return True
    t_lower = title.lower()
    q_lower = query.lower().strip()
    if "://" in q_lower:
        q_lower = q_lower.split("://", 1)[1]
    if q_lower.startswith("www."):
        q_lower = q_lower[4:]
    q_core = q_lower.split("/")[0].split(".")[0] if "." in q_lower else q_lower
    return q_lower in t_lower or (bool(q_core) and q_core in t_lower)


@register("closeBrowserTab")
def close_browser_tab(args: Dict[str, Any]) -> Dict[str, Any]:
    import time
    from .tools_windows import (
        _focus,
        _get_all_windows,
        _get_foreground_window,
        _is_alt_tab_window,
        _window_title,
    )

    target_query = (
        args.get("title")
        or args.get("name")
        or args.get("tab")
        or args.get("url")
        or ""
    ).strip()

    # Collect visible browser windows in Z-order
    browser_windows: list[tuple[int, str, str]] = []
    for h in _get_all_windows():
        if _is_alt_tab_window(h):
            t = _window_title(h)
            is_browser, bname = _is_browser_window(h, t)
            if is_browser:
                browser_windows.append((h, t, bname))

    if not browser_windows:
        raise ToolError(
            "No supported browser window (Opera, Chrome, Edge, Brave, Firefox) is currently open."
        )

    # 1. Check currently active tab of each browser window first
    for h, t, bname in browser_windows:
        if _matches_tab_query(t, target_query):
            _focus(h)
            time.sleep(0.1)
            _send_ctrl_w()
            return {
                "result": f"Closed active browser tab '{t}' in {bname}."
            }

    # If no specific query was requested, close active tab in foreground browser
    if not target_query:
        fg = _get_foreground_window()
        for h, t, bname in browser_windows:
            if h == fg:
                _focus(h)
                time.sleep(0.1)
                _send_ctrl_w()
                return {"result": f"Closed active browser tab '{t}' in {bname}."}
        h, t, bname = browser_windows[0]
        _focus(h)
        time.sleep(0.1)
        _send_ctrl_w()
        return {"result": f"Closed active browser tab '{t}' in {bname}."}

    # 2. Not currently active -> cycle background tabs with Ctrl+PageDown in each open browser
    for h, start_title, bname in browser_windows:
        _focus(h)
        time.sleep(0.1)

        current_title = _window_title(h) or start_title
        steps_forward = 0
        matched = False
        matched_title = ""
        max_tabs = 25

        for _ in range(max_tabs):
            _send_next_tab()
            steps_forward += 1
            time.sleep(0.08)

            new_title = _window_title(h)
            if _matches_tab_query(new_title, target_query):
                matched = True
                matched_title = new_title
                _send_ctrl_w()
                break

            if new_title == current_title:
                # Circled all the way back to the starting tab
                break

        if matched:
            return {
                "result": f"Found and closed browser tab '{matched_title}' in {bname}."
            }

        # Tab not found in this window -> restore the original tab
        for _ in range(steps_forward):
            if _window_title(h) == current_title:
                break
            _send_prev_tab()
            time.sleep(0.04)

    browser_names = ", ".join(sorted(set(b[2] for b in browser_windows)))
    raise ToolError(
        f"No open browser tab found matching '{target_query}' in active browsers ({browser_names})."
    )


def _get_target_browser_window() -> tuple[int, str, str]:
    """Find the active or top-most supported browser window. Returns (hwnd, title, browser_name)."""
    from .tools_windows import (
        _get_all_windows,
        _get_foreground_window,
        _is_alt_tab_window,
        _window_title,
    )

    fg = _get_foreground_window()
    if fg:
        fg_title = _window_title(fg)
        is_b, bname = _is_browser_window(fg, fg_title)
        if is_b:
            return fg, fg_title, bname

    for h in _get_all_windows():
        if _is_alt_tab_window(h):
            t = _window_title(h)
            is_b, bname = _is_browser_window(h, t)
            if is_b:
                return h, t, bname

    raise ToolError(
        "No supported browser window (Opera, Chrome, Edge, Brave, Firefox) is currently open."
    )


@register("browserBack")
def browser_back(args: Dict[str, Any]) -> Dict[str, Any]:
    from .tools_windows import _focus

    hwnd, _, bname = _get_target_browser_window()
    _focus(hwnd)
    time.sleep(0.1)
    _send_alt_left()
    return {"result": f"Navigated back in {bname}."}


@register("browserForward")
def browser_forward(args: Dict[str, Any]) -> Dict[str, Any]:
    from .tools_windows import _focus

    hwnd, _, bname = _get_target_browser_window()
    _focus(hwnd)
    time.sleep(0.1)
    _send_alt_right()
    return {"result": f"Navigated forward in {bname}."}


MEDIA_ACTION_KEYS = {
    "play": "k",
    "pause": "k",
    "toggle": "k",
    "mute": "m",
    "unmute": "m",
    "fullscreen": "f",
    "skip_forward": "l",
    "skip_backward": "j",
    "forward": "l",
    "backward": "j",
    "skip": "l",
}


@register("browserMediaAction")
def browser_media_action(args: Dict[str, Any]) -> Dict[str, Any]:
    import pyautogui
    from .tools_windows import _focus

    action = str(args.get("action") or "toggle").lower().strip()
    key = MEDIA_ACTION_KEYS.get(action)
    if not key:
        valid_actions = ", ".join(sorted(set(MEDIA_ACTION_KEYS.keys())))
        raise ToolError(f"Unsupported media action '{action}'. Choose from: {valid_actions}.")

    hwnd, _, bname = _get_target_browser_window()
    _focus(hwnd)
    time.sleep(0.1)

    try:
        pyautogui.press(key)
    except Exception:
        import ctypes
        VK_MAP = {"k": 0x4B, "m": 0x4D, "f": 0x46, "l": 0x4C, "j": 0x4A}
        vk = VK_MAP.get(key, 0x4B)
        KEYEVENTF_KEYUP = 0x0002
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        time.sleep(0.05)
        ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)

    return {"result": f"Executed media action '{action}' in {bname}."}


@register("clickElement")
def click_element(args: Dict[str, Any]) -> Dict[str, Any]:
    import re
    import pyautogui
    import pytesseract
    import win32gui
    from .tools_screenshot import _capture_region, _find_tesseract_exe
    from .tools_windows import _focus

    target = (
        args.get("target")
        or args.get("text")
        or args.get("element")
        or args.get("query")
        or ""
    ).strip()

    if not target:
        raise ToolError("Parameter 'target' is required (e.g. 'first result', 'Sign in', 'Python tutorial').")

    hwnd, _, bname = _get_target_browser_window()
    _focus(hwnd)
    time.sleep(0.2)

    rect = win32gui.GetWindowRect(hwnd)
    if rect[2] - rect[0] <= 100 or rect[3] - rect[1] <= 100:
        raise ToolError(f"{bname} window is minimized or too small to interact with.")

    screen_w, screen_h = pyautogui.size()
    l = max(0, min(screen_w - 1, rect[0]))
    t = max(0, min(screen_h - 1, rect[1]))
    r = max(0, min(screen_w, rect[2]))
    b = max(0, min(screen_h, rect[3]))
    bbox = (l, t, r, b)

    img = _capture_region(bbox)
    tess_exe = _find_tesseract_exe()
    if tess_exe:
        pytesseract.pytesseract.tesseract_cmd = tess_exe

    try:
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    except Exception as e:
        raise ToolError(f"Screen text extraction failed: {e}")

    words = []
    for i in range(len(data["text"])):
        txt = data["text"][i].strip()
        if txt:
            w_left = data["left"][i]
            w_top = data["top"][i]
            w_w = data["width"][i]
            w_h = data["height"][i]
            words.append({
                "text": txt,
                "clean": re.sub(r"[^\w]", "", txt.lower()),
                "left": w_left,
                "top": w_top,
                "right": w_left + w_w,
                "bottom": w_top + w_h,
                "block": data["block_num"][i],
                "par": data["par_num"][i],
                "line": data["line_num"][i],
            })

    if not words:
        raise ToolError(f"No visible text was detected on the active {bname} screen.")

    from collections import defaultdict
    line_groups = defaultdict(list)
    for w in words:
        line_groups[(w["block"], w["par"], w["line"])].append(w)

    lines = []
    for (blk, par, ln), l_words in line_groups.items():
        l_words.sort(key=lambda x: x["left"])
        line_text = " ".join(w["text"] for w in l_words)
        clean_text = " ".join(w["clean"] for w in l_words if w["clean"])
        lines.append({
            "text": line_text,
            "clean": clean_text,
            "left": min(w["left"] for w in l_words),
            "top": min(w["top"] for w in l_words),
            "right": max(w["right"] for w in l_words),
            "bottom": max(w["bottom"] for w in l_words),
            "words": l_words,
        })

    ord_map = {
        "first": 0, "1st": 0,
        "second": 1, "2nd": 1,
        "third": 2, "3rd": 2,
        "fourth": 3, "4th": 3,
        "fifth": 4, "5th": 4,
    }
    m_ord = re.search(r"\b(first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th)\b", target.lower())
    is_ordinal = bool(m_ord) and any(kw in target.lower() for kw in ("result", "video", "link", "item", "option", "one", "entry"))

    matched_box = None
    matched_label = ""

    if is_ordinal:
        target_idx = ord_map[m_ord.group(1).lower()]
        candidates = [
            ln for ln in lines
            if ln["top"] > 120 and (ln["right"] - ln["left"]) > 40 and len(ln["clean"]) > 4
        ]
        nav_words = {"search", "filters", "all", "videos", "shorts", "subscriptions", "library", "history"}
        filtered = [c for c in candidates if not all(w in nav_words for w in c["clean"].split())]
        if not filtered:
            filtered = candidates

        filtered.sort(key=lambda x: (x["top"] // 30, x["left"]))
        if target_idx < len(filtered):
            match = filtered[target_idx]
            matched_box = (match["left"], match["top"], match["right"], match["bottom"])
            matched_label = match["text"]
        else:
            raise ToolError(
                f"Requested {m_ord.group(1)} result, but only {len(filtered)} visible content elements were found on screen."
            )

    # 2. Text / descriptor-aware matching
    if not matched_box:
        clean_target = re.sub(r"[^\w\s]", "", target.lower()).strip()
        raw_tokens = clean_target.split()

        # Generic UI descriptor words to ignore when looking for on-screen text
        UI_DESCRIPTOR_WORDS = {"button", "btn", "link", "icon", "tab", "menu", "item", "option"}
        meaningful_tokens = [t for t in raw_tokens if t not in UI_DESCRIPTOR_WORDS]
        if not meaningful_tokens:
            meaningful_tokens = raw_tokens
        meaningful_target = " ".join(meaningful_tokens)

        # 2a. Dedicated Skip / Ad handler (supports "Skip", "Skip Ad", "Skip Ads", "Skip in 5", "Skip button")
        if "skip" in raw_tokens or "skip" in meaningful_tokens:
            skip_matches = [
                ln for ln in lines
                if "skip" in ln["clean"]
            ]
            if skip_matches:
                content_skip = [ln for ln in skip_matches if ln["top"] > 120]
                best_skip = content_skip[0] if content_skip else skip_matches[0]
                matched_box = (best_skip["left"], best_skip["top"], best_skip["right"], best_skip["bottom"])
                matched_label = best_skip["text"]

        # 2b. Exact substring match with original clean_target
        if not matched_box:
            line_matches = [
                ln for ln in lines
                if clean_target in re.sub(r"[^\w\s]", "", ln["text"].lower())
            ]
            if line_matches:
                content_matches = [ln for ln in line_matches if ln["top"] > 100]
                best = content_matches[0] if content_matches else line_matches[0]
                matched_box = (best["left"], best["top"], best["right"], best["bottom"])
                matched_label = best["text"]

        # 2c. Substring match with meaningful_target (descriptors like "button" stripped)
        if not matched_box and meaningful_target != clean_target:
            meaningful_matches = [
                ln for ln in lines
                if meaningful_target in re.sub(r"[^\w\s]", "", ln["text"].lower())
            ]
            if meaningful_matches:
                content_matches = [ln for ln in meaningful_matches if ln["top"] > 100]
                best = content_matches[0] if content_matches else meaningful_matches[0]
                matched_box = (best["left"], best["top"], best["right"], best["bottom"])
                matched_label = best["text"]

        # 2d. All meaningful tokens in line
        if not matched_box and meaningful_tokens:
            token_matches = [
                ln for ln in lines
                if all(tok in ln["clean"] for tok in meaningful_tokens)
            ]
            if token_matches:
                content_matches = [ln for ln in token_matches if ln["top"] > 100]
                best = content_matches[0] if content_matches else token_matches[0]
                matched_box = (best["left"], best["top"], best["right"], best["bottom"])
                matched_label = best["text"]

        # 2e. Partial token overlap (if multiple meaningful tokens, select line with highest overlap)
        if not matched_box and len(meaningful_tokens) >= 2:
            scored = []
            for ln in lines:
                if ln["top"] > 100:
                    score = sum(1 for tok in meaningful_tokens if tok in ln["clean"])
                    if score >= 1:
                        scored.append((score, ln))
            if scored:
                scored.sort(key=lambda s: s[0], reverse=True)
                if scored[0][0] >= max(1, len(meaningful_tokens) // 2):
                    best = scored[0][1]
                    matched_box = (best["left"], best["top"], best["right"], best["bottom"])
                    matched_label = best["text"]

        # 2f. Single meaningful token match in individual words
        if not matched_box and len(meaningful_tokens) == 1:
            single_word = meaningful_tokens[0]
            word_matches = [
                w for w in words
                if single_word == w["clean"] or single_word in w["clean"] or w["clean"].startswith(single_word)
            ]
            if word_matches:
                content_matches = [w for w in word_matches if w["top"] > 100]
                best = content_matches[0] if content_matches else word_matches[0]
                matched_box = (best["left"], best["top"], best["right"], best["bottom"])
                matched_label = best["text"]

    if not matched_box:
        raise ToolError(
            f"Could not find any visible element matching '{target}' on the active {bname} screen."
        )

    click_x = l + (matched_box[0] + matched_box[2]) // 2
    click_y = t + (matched_box[1] + matched_box[3]) // 2

    pyautogui.moveTo(click_x, click_y, duration=0.1)
    pyautogui.click(click_x, click_y)

    return {
        "result": f"Clicked '{matched_label.strip()}' at screen coordinates ({click_x}, {click_y}) in {bname}.",
        "target": target,
        "x": click_x,
        "y": click_y,
    }


__all__ = [
    "open_website",
    "close_browser_tab",
    "browser_back",
    "browser_forward",
    "browser_media_action",
    "click_element",
    "open_url",
    "SITE_URLS",
    "_build_search_url",
]
