"""
Application control: launch and close common Windows applications.

Launch strategy is layered for robustness:
  1. Try a known executable / shell verb (fastest, most reliable).
  2. Fall back to the Windows "where"/App Paths lookup via `start`.

Closing uses taskkill on the matching process image name, with a graceful
grace period so apps can save work.
"""

from __future__ import annotations

import ast
import math
import operator
import os
import re
import shutil
import subprocess
import time
import winreg
from typing import Any, Dict

from .registry import ToolError, register

# Curated core Windows applications
APP_COMMANDS: Dict[str, Dict[str, str]] = {
    "calculator": {"target": "calc.exe", "image": "CalculatorApp.exe", "label": "Calculator"},
    "calc": {"target": "calc.exe", "image": "CalculatorApp.exe", "label": "Calculator"},
    "settings": {"target": "ms-settings:", "image": "SystemSettings.exe", "label": "Settings"},
    "file explorer": {"target": "explorer.exe", "image": "explorer.exe", "label": "File Explorer"},
    "explorer": {"target": "explorer.exe", "image": "explorer.exe", "label": "File Explorer"},
    "task manager": {"target": "taskmgr.exe", "image": "Taskmgr.exe", "label": "Task Manager"},
    "taskmanager": {"target": "taskmgr.exe", "image": "Taskmgr.exe", "label": "Task Manager"},
    "taskmgr": {"target": "taskmgr.exe", "image": "Taskmgr.exe", "label": "Task Manager"},
    "notepad": {"target": "notepad.exe", "image": "notepad.exe", "label": "Notepad"},
    "paint": {"target": "mspaint.exe", "image": "mspaint.exe", "label": "Paint"},
    "snipping tool": {"target": "SnippingTool.exe", "image": "SnippingTool.exe", "label": "Snipping Tool"},
    "command prompt": {"target": "cmd.exe", "image": "cmd.exe", "label": "Command Prompt"},
    "cmd": {"target": "cmd.exe", "image": "cmd.exe", "label": "Command Prompt"},
    "powershell": {"target": "powershell.exe", "image": "powershell.exe", "label": "PowerShell"},
}

COMMON_ALIASES: Dict[str, str] = {
    "chrome": "google chrome",
    "google chrome": "google chrome",
    "edge": "microsoft edge",
    "ms edge": "microsoft edge",
    "microsoft edge": "microsoft edge",
    "vscode": "visual studio code",
    "vs code": "visual studio code",
    "code": "visual studio code",
    "visual studio code": "visual studio code",
    "calc": "calculator",
    "calculator app": "calculator",
    "the calculator": "calculator",
    "windows calculator": "calculator",
    "win calc": "calculator",
    "settings app": "settings",
    "file explorer": "file explorer",
    "windows explorer": "file explorer",
    "taskmgr": "task manager",
    "task manager": "task manager",
    "taskmanager": "task manager",
}

_DISCOVERED_APPS: Dict[str, Dict[str, str]] | None = None


def _get_installed_apps() -> Dict[str, Dict[str, str]]:
    global _DISCOVERED_APPS
    if _DISCOVERED_APPS is not None:
        return _DISCOVERED_APPS

    apps: Dict[str, Dict[str, str]] = {}

    # 1. Start Menu shortcuts (.lnk files)
    try:
        import win32com.client
        wscript = win32com.client.Dispatch("WScript.Shell")
        dirs = [
            os.path.expandvars(r"%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs"),
            os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
        ]
        for folder in dirs:
            if not os.path.exists(folder):
                continue
            for root, _, files in os.walk(folder):
                for file in files:
                    if file.lower().endswith(".lnk"):
                        lnk_path = os.path.join(root, file)
                        name = os.path.splitext(file)[0].strip()
                        try:
                            sc = wscript.CreateShortcut(lnk_path)
                            target = sc.TargetPath
                            if target and target.lower().endswith(".exe"):
                                apps[name.lower()] = {
                                    "label": name,
                                    "target": lnk_path,
                                    "image": os.path.basename(target),
                                }
                        except Exception:
                            pass
    except Exception:
        pass

    # 2. Windows Registry App Paths (HKLM and HKCU)
    for root_key in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(root_key, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths") as key:
                for i in range(winreg.QueryInfoKey(key)[0]):
                    try:
                        subkey_name = winreg.EnumKey(key, i)
                        with winreg.OpenKey(key, subkey_name) as subkey:
                            val, _ = winreg.QueryValueEx(subkey, "")
                            if val and os.path.exists(val):
                                app_name = os.path.splitext(subkey_name)[0].lower()
                                if app_name not in apps:
                                    apps[app_name] = {
                                        "label": os.path.splitext(subkey_name)[0],
                                        "target": val,
                                        "image": subkey_name,
                                    }
                    except OSError:
                        pass
        except OSError:
            pass

    _DISCOVERED_APPS = apps
    return apps


def _resolve_app(key: str) -> Dict[str, str]:
    norm = (key or "").strip().lower()
    if not norm:
        raise ToolError("Parameter 'name' (application name) is required.")

    if norm in ("wordpad", "write"):
        raise ToolError("WordPad has been deprecated and removed from modern Windows.")

    # 1. Check curated core applications
    if norm in APP_COMMANDS:
        return APP_COMMANDS[norm]

    alias_target = COMMON_ALIASES.get(norm, norm)
    if alias_target in APP_COMMANDS:
        return APP_COMMANDS[alias_target]

    # Handle natural calculator name queries containing 'calc' or 'calculator'
    if "calculator" in norm or "calc" in norm.split() or norm.startswith("calc"):
        return APP_COMMANDS["calculator"]

    # 2. Check dynamically discovered applications
    installed = _get_installed_apps()

    # Exact match on alias_target or norm
    if alias_target in installed:
        return installed[alias_target]
    if norm in installed:
        return installed[norm]

    # Substring matching
    for k, v in installed.items():
        if alias_target in k or norm in k:
            return v

    # 3. Direct PATH fallback
    which_target = shutil.which(norm) or shutil.which(f"{norm}.exe")
    if which_target:
        image = os.path.basename(which_target)
        return {"target": which_target, "image": image, "label": norm.title()}

    raise ToolError(f"Could not find installed application matching '{key}'.")


def _launch(spec: Dict[str, str]) -> None:
    target = spec.get("target") or spec.get("exe") or spec.get("shell") or spec.get("uwp")
    if not target:
        raise ToolError(f"App spec for {spec.get('label', 'application')} is missing a launch target.")
    try:
        os.startfile(target)
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"Could not launch {spec.get('label', 'application')}: {e}") from e


@register("openApplication")
def open_application(args: Dict[str, Any]) -> Dict[str, Any]:
    name = args.get("name") or args.get("application")
    if not name:
        raise ToolError("Parameter 'name' (application name) is required.")
    spec = _resolve_app(str(name))
    _launch(spec)
    return {"result": f"{spec['label']} opened."}


def _is_running(image: str) -> bool:
    try:
        res = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return image.lower() in res.stdout.lower()
    except Exception:
        return False


@register("closeApplication")
def close_application(args: Dict[str, Any]) -> Dict[str, Any]:
    name = args.get("name") or args.get("application")
    force = bool(args.get("force", False))
    if not name:
        raise ToolError("Parameter 'name' (application name) is required.")
    spec = _resolve_app(str(name))
    image = spec["image"]

    is_calculator = (
        spec.get("label") == "Calculator"
        or image.lower() in ("calculatorapp.exe", "calculator.exe")
        or spec.get("target") == "calc.exe"
    )
    images_to_check = ["CalculatorApp.exe", "Calculator.exe"] if is_calculator else [image]

    running_images = [img for img in images_to_check if _is_running(img)]
    if not running_images:
        raise ToolError(f"{spec['label']} is not running.")

    is_modern = (
        "uwp" in spec
        or is_calculator
        or image.lower() in ("systemsettings.exe", "screenclippinghost.exe")
        or spec.get("shell") == "calc"
    )

    for img in running_images:
        cmd = f'taskkill /IM "{img}" /F' if (force or is_modern) else f'taskkill /IM "{img}"'
        try:
            res = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception as e:  # noqa: BLE001
            raise ToolError(f"Could not close {spec['label']}: {e}") from e

        if res.returncode != 0:
            err = res.stderr.strip() or f"taskkill exited with code {res.returncode}"
            if "not found" not in err.lower():
                raise ToolError(f"Could not close {spec['label']}: {err}")

    # Verify that the target process is actually no longer running
    for _ in range(6):
        time.sleep(0.15)
        if not any(_is_running(img) for img in running_images):
            return {"result": f"Closed {spec['label']}."}

    if any(_is_running(img) for img in running_images):
        hint = " (use force=True to force close)." if not force else "."
        raise ToolError(f"Could not close {spec['label']}. The application is still running{hint}")

    return {"result": f"Closed {spec['label']}."}


@register("calculate")
def calculate(args: Dict[str, Any]) -> Dict[str, Any]:
    raw_expr = args.get("expression") or args.get("query") or args.get("calculation") or args.get("input") or ""
    if not str(raw_expr).strip():
        raise ToolError("Parameter 'expression' is required for calculation.")

    text = str(raw_expr).strip()
    # Normalize natural language phrasing to Python arithmetic
    text = re.sub(r'(?i)\bsquare\s+root\s+of\s+', 'sqrt(', text)
    text = re.sub(r'(\d+(?:\.\d+)?)\s*(?:%|percent)\s*of\s*(\d+(?:\.\d+)?)', r'((\1/100.0)*\2)', text)
    text = re.sub(r'(?i)\bmultiplied\s+by\b', '*', text)
    text = re.sub(r'(?i)\btimes\b', '*', text)
    text = re.sub(r'(?i)\bdivided\s+by\b', '/', text)
    text = re.sub(r'(?i)\bplus\b', '+', text)
    text = re.sub(r'(?i)\bminus\b', '-', text)
    text = re.sub(r'(?i)\bto\s+the\s+power\s+of\b', '**', text)
    text = text.replace('^', '**')
    text = re.sub(r'(\d+)\s*[xX]\s*(\d+)', r'\1 * \2', text)

    ops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }
    funcs = {
        'sqrt': math.sqrt,
        'abs': abs,
        'round': round,
        'sin': math.sin,
        'cos': math.cos,
        'tan': math.tan,
        'floor': math.floor,
        'ceil': math.ceil,
        'log': math.log,
        'log10': math.log10,
        'pow': math.pow,
    }
    consts = {'pi': math.pi, 'e': math.e}

    def _eval(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        elif isinstance(node, ast.Constant):
            return node.value
        elif isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type not in ops:
                raise ToolError(f"Unsupported mathematical operator: {op_type.__name__}")
            left = _eval(node.left)
            right = _eval(node.right)
            return ops[op_type](left, right)
        elif isinstance(node, ast.UnaryOp):
            op_type = type(node.op)
            if op_type not in ops:
                raise ToolError(f"Unsupported unary operator: {op_type.__name__}")
            return ops[op_type](_eval(node.operand))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            func_name = node.func.id.lower()
            if func_name in funcs:
                return funcs[func_name](*[_eval(a) for a in node.args])
            raise ToolError(f"Unsupported math function: {func_name}")
        elif isinstance(node, ast.Name):
            name_lower = node.id.lower()
            if name_lower in consts:
                return consts[name_lower]
            raise ToolError(f"Unrecognized identifier: {node.id}")
        raise ToolError(f"Unsupported expression element: {ast.dump(node)}")

    try:
        tree = ast.parse(text, mode='eval')
        val = _eval(tree)
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Could not calculate expression '{raw_expr}': {e}") from e

    if isinstance(val, float) and val.is_integer():
        val_display = int(val)
    elif isinstance(val, float):
        val_display = round(val, 6)
    else:
        val_display = val

    return {
        "result": f"{str(raw_expr).strip()} = {val_display}",
        "value": val_display,
        "expression": str(raw_expr).strip(),
    }


__all__ = ["open_application", "close_application", "calculate", "APP_COMMANDS"]
