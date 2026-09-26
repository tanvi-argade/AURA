"""
File management: create / read / rename / delete / move / open / search.

Safety model:
  * All paths are resolved with expanduser and normalized to absolute.
  * Deletion sends files/folders to the Recycle Bin via `send2trash` when
    available (preferred), and otherwise refuses to delete rather than
    permanently removing data.
  * Operations are confined to a set of SAFE_ROOTS by default; paths that
    escape these roots (e.g. C:\\Windows) are rejected unless explicitly
    marked `allow_anywhere` by the caller.
"""

from __future__ import annotations

import fnmatch
import os
import platform
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from .registry import ToolError, register

HOME = Path(os.path.expanduser("~"))


def _get_user_folder(name: str) -> Path:
    """Resolve a known user folder (Desktop, Documents, etc.), prioritizing Windows Registry / OneDrive when active."""
    if platform.system() == "Windows":
        reg_map = {
            "Desktop": "Desktop",
            "Documents": "Personal",
            "Pictures": "My Pictures",
            "Music": "My Music",
            "Videos": "My Video",
            "Downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
        }
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
            reg_val_name = reg_map.get(name, name)
            try:
                raw_val = winreg.QueryValueEx(k, reg_val_name)[0]
                p = Path(os.path.expandvars(str(raw_val))).resolve()
                if p.exists():
                    return p
            except OSError:
                pass
        except Exception:
            pass

    for env_var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        od_base = os.environ.get(env_var)
        if od_base:
            od_folder = Path(od_base) / name
            if od_folder.exists():
                return od_folder
    od_home = HOME / "OneDrive" / name
    if od_home.exists():
        return od_home
    return HOME / name


DESKTOP_DIR = _get_user_folder("Desktop")
DOCUMENTS_DIR = _get_user_folder("Documents")
DOWNLOADS_DIR = _get_user_folder("Downloads")
PICTURES_DIR = _get_user_folder("Pictures")
MUSIC_DIR = _get_user_folder("Music")
VIDEOS_DIR = _get_user_folder("Videos")

# Roots under which file operations are freely permitted.
SAFE_ROOTS: List[Path] = [
    HOME,
    DESKTOP_DIR,
    DOCUMENTS_DIR,
    DOWNLOADS_DIR,
    PICTURES_DIR,
    MUSIC_DIR,
    VIDEOS_DIR,
    Path(os.getcwd()),  # project root
]

# Friendly folder aliases -> resolved path.
FOLDER_ALIASES: Dict[str, Path] = {
    "desktop": DESKTOP_DIR,
    "documents": DOCUMENTS_DIR,
    "downloads": DOWNLOADS_DIR,
    "pictures": PICTURES_DIR,
    "photos": PICTURES_DIR,
    "music": MUSIC_DIR,
    "videos": VIDEOS_DIR,
    "home": HOME,
    "this pc": Path("C:\\"),
    "c drive": Path("C:\\"),
}


def _resolve_folder(name_or_path: Optional[str]) -> Path:
    if not name_or_path:
        raise ToolError("Parameter 'name' or 'path' is required.")
    raw = str(name_or_path).strip()
    norm = raw.replace("\\", "/").lower()

    if norm in FOLDER_ALIASES:
        return FOLDER_ALIASES[norm]

    for alias, alias_path in FOLDER_ALIASES.items():
        if alias in ("this pc", "c drive", "home"):
            continue
        prefix = alias + "/"
        if norm.startswith(prefix):
            rel = raw[len(prefix):]
            return (alias_path / rel).resolve()

    p = Path(os.path.expandvars(os.path.expanduser(raw))).resolve()
    return p


def _resolve_file(path: Optional[str], *, must_exist: bool = False) -> Path:
    if not path:
        raise ToolError("Parameter 'path' is required.")
    raw = str(path).strip()
    norm = raw.replace("\\", "/").lower()

    if norm in FOLDER_ALIASES:
        p = FOLDER_ALIASES[norm]
        if must_exist and not p.exists():
            raise ToolError(f"File does not exist: {p}")
        return p

    for alias, alias_path in FOLDER_ALIASES.items():
        if alias in ("this pc", "c drive", "home"):
            continue
        prefix = alias + "/"
        if norm.startswith(prefix):
            rel = raw[len(prefix):]
            p = (alias_path / rel).resolve()
            if must_exist and not p.exists():
                raise ToolError(f"File does not exist: {p}")
            return p

    p = Path(os.path.expandvars(os.path.expanduser(raw))).resolve()
    if must_exist and not p.exists():
        raise ToolError(f"File does not exist: {p}")
    return p


def _ensure_safe(p: Path, allow_anywhere: bool = False) -> None:
    if allow_anywhere:
        return
    real = str(p)
    for root in SAFE_ROOTS:
        try:
            root_real = str(root.resolve())
        except Exception:
            continue
        if real == root_real or real.startswith(root_real + os.sep):
            return
    raise ToolError(
        f"Path '{p}' is outside AURA's safe folders (Desktop, Documents, "
        f"Downloads, Pictures, Music, Videos, home, and the project folder). "
        f"Pass allow_anywhere=true only if you really mean it."
    )


@register("createFile")
def create_file(args: Dict[str, Any]) -> Dict[str, Any]:
    raw_path = args.get("path") or args.get("filename") or args.get("name")
    if not raw_path:
        raise ToolError("Parameter 'path' or 'filename'/'name' is required.")
    folder = args.get("folder") or args.get("directory")
    content = args.get("content", "")
    overwrite = bool(args.get("overwrite", False))

    raw_path_str = str(raw_path).strip()

    if folder:
        base_folder = _resolve_folder(str(folder))
        norm = raw_path_str.replace("\\", "/").lower()
        for alias in FOLDER_ALIASES:
            prefix = alias + "/"
            if norm.startswith(prefix):
                raw_path_str = raw_path_str[len(prefix):]
                break
        p = (base_folder / raw_path_str).resolve()
    else:
        # If a bare filename is provided (no directory separators), default to Desktop
        if "/" not in raw_path_str and "\\" not in raw_path_str:
            p = (DESKTOP_DIR / raw_path_str).resolve()
        else:
            p = _resolve_file(raw_path_str)

    _ensure_safe(p)

    if p.exists() and not overwrite:
        raise ToolError(
            f"File already exists: {p}. Pass overwrite=true to replace it."
        )
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(content), encoding="utf-8")
    return {"result": f"Created file: {p}", "path": str(p)}


@register("readFile")
def read_file(args: Dict[str, Any]) -> Dict[str, Any]:
    path = args.get("path")
    max_chars = int(args.get("max_chars", 8000))
    p = _resolve_file(path, must_exist=True)
    _ensure_safe(p)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except UnicodeDecodeError:
        return {"result": f"(Binary file, {p.stat().st_size} bytes): {p}"}
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n…[truncated, {len(text) - max_chars} more chars]"
    return {"result": text, "path": str(p)}


@register("renameFile")
def rename_file(args: Dict[str, Any]) -> Dict[str, Any]:
    path = args.get("path")
    new_name = args.get("new_name")
    if not new_name:
        raise ToolError("Parameter 'new_name' is required.")
    p = _resolve_file(path, must_exist=True)
    _ensure_safe(p)
    target = (p.parent / str(new_name)).resolve()
    _ensure_safe(target)
    if target.exists():
        raise ToolError(f"A file already exists at the target name: {target}")
    p.rename(target)
    return {"result": f"Renamed {p.name} -> {target.name}", "path": str(target)}


@register("deleteFile")
def delete_file(args: Dict[str, Any]) -> Dict[str, Any]:
    path = args.get("path")
    permanent = bool(args.get("permanent", False))
    p = _resolve_file(path, must_exist=True)
    _ensure_safe(p)

    if permanent:
        if p.is_dir():
            import shutil

            shutil.rmtree(p)
        else:
            p.unlink()
        return {"result": f"Permanently deleted: {p}"}

    # Prefer recycle bin.
    try:
        import send2trash  # type: ignore

        send2trash.send2trash(str(p))
        return {"result": f"Moved to Recycle Bin: {p}"}
    except ImportError:
        raise ToolError(
            "Safe deletion requires the 'send2trash' package. Install it or pass "
            "permanent=true (use with care)."
        )
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"Could not move to Recycle Bin: {e}")


@register("moveFile")
def move_file(args: Dict[str, Any]) -> Dict[str, Any]:
    path = args.get("path")
    destination = args.get("destination")
    p = _resolve_file(path, must_exist=True)
    _ensure_safe(p)
    dest = Path(os.path.expandvars(os.path.expanduser(str(destination)))).resolve()
    # If destination is an existing directory, keep the filename.
    if dest.is_dir():
        dest = dest / p.name
    _ensure_safe(dest)
    if dest.exists():
        raise ToolError(f"Destination already exists: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    p.rename(dest)
    return {"result": f"Moved {p.name} -> {dest}", "path": str(dest)}


@register("openFile")
def open_file(args: Dict[str, Any]) -> Dict[str, Any]:
    """Open an existing file using the operating system's default registered application."""
    path = args.get("path") or args.get("file") or args.get("name")
    if not path:
        raise ToolError("Parameter 'path' is required.")
    allow_anywhere = bool(args.get("allow_anywhere", False))
    p = _resolve_file(path, must_exist=True)
    _ensure_safe(p, allow_anywhere=allow_anywhere)

    if p.is_dir():
        return open_folder({"path": str(p)})

    try:
        if platform.system() == "Windows":
            os.startfile(str(p))
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", str(p)], close_fds=True)
        else:
            subprocess.Popen(["xdg-open", str(p)], close_fds=True)
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"Could not open file '{p.name}': {e}") from e

    return {"result": f"Opened file: {p.name}", "path": str(p)}


@register("openFolder")
def open_folder(args: Dict[str, Any]) -> Dict[str, Any]:
    folder = _resolve_folder(args.get("name") or args.get("path"))
    if not folder.exists():
        raise ToolError(f"Folder does not exist: {folder}")
    # Explorer on Windows, open elsewhere.
    if platform.system() == "Windows":
        subprocess.Popen(f'explorer "{folder}"', shell=True, close_fds=True)
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", str(folder)], close_fds=True)
    else:
        subprocess.Popen(["xdg-open", str(folder)], close_fds=True)
    return {"result": f"Opened folder: {folder}", "path": str(folder)}


@register("listFiles")
def list_files(args: Dict[str, Any]) -> Dict[str, Any]:
    folder = _resolve_folder(args.get("name") or args.get("path"))
    if not folder.exists():
        raise ToolError(f"Folder does not exist: {folder}")
    pattern = args.get("pattern") or "*"
    try:
        names = sorted(
            [p.name + ("/" if p.is_dir() else "") for p in folder.glob(pattern)]
        )
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"Could not list folder: {e}")
    return {
        "result": f"{len(names)} item(s) in {folder}",
        "items": names[:500],
        "count": len(names),
    }


IGNORED_SEARCH_DIRS = {
    "appdata",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".git",
    ".svn",
    ".hg",
}


@register("searchFiles")
def search_files(args: Dict[str, Any]) -> Dict[str, Any]:
    """Find files by name glob/substring or extension under a folder or common user locations.

    Examples:
      name="notes"                            -> searches for *notes* in Desktop, Documents, Downloads
      name="*.py" folder="Documents"          -> all python files under Documents
      extension="py"                          -> same as name="*.py"
      name="report*" folder="Desktop"
    """
    folder_arg = args.get("folder") or args.get("under")
    name = args.get("name") or args.get("pattern")
    extension = args.get("extension")
    limit = int(args.get("limit", 100))

    if extension:
        ext_str = str(extension).strip()
        if not ext_str.startswith("."):
            ext_str = "." + ext_str
        pattern = "*" + ext_str
    elif name:
        raw_name = str(name).strip()
        if "*" not in raw_name and "?" not in raw_name:
            pattern = f"*{raw_name}*"
        else:
            pattern = raw_name
    else:
        raise ToolError("Provide 'name' glob/substring or 'extension'.")

    # Resolve search roots: explicit folder or default safe common user locations
    if folder_arg:
        resolved = _resolve_folder(folder_arg)
        if not resolved.exists():
            raise ToolError(f"Folder does not exist: {resolved}")
        search_roots = [resolved]
        scope_desc = str(resolved)
    else:
        # Default: search safe common user locations (Desktop, Documents, Downloads)
        search_roots = []
        for candidate in [DESKTOP_DIR, DOCUMENTS_DIR, DOWNLOADS_DIR]:
            if candidate.exists() and candidate not in search_roots:
                search_roots.append(candidate)
        if not search_roots:
            search_roots = [HOME]
        scope_desc = "Desktop, Documents, and Downloads"

    matches: List[str] = []
    for s_root in search_roots:
        if not s_root.exists():
            continue
        for root, dirs, files in os.walk(s_root):
            # Prune heavy/unnecessary and hidden directories in-place
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".") and d.lower() not in IGNORED_SEARCH_DIRS
            ]
            for fname in files:
                if fnmatch.fnmatch(fname.lower(), pattern.lower()):
                    matches.append(os.path.join(root, fname))
                    if len(matches) >= limit:
                        break
            if len(matches) >= limit:
                break
        if len(matches) >= limit:
            break

    return {
        "result": f"Found {len(matches)} file(s) matching '{pattern}' in {scope_desc}",
        "matches": matches,
        "count": len(matches),
    }


__all__ = [
    "create_file",
    "open_file",
    "read_file",
    "rename_file",
    "delete_file",
    "move_file",
    "open_folder",
    "list_files",
    "search_files",
]
