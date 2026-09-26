"""
System information: CPU, RAM, disk usage, GPU (best-effort), temperature.

All read-only. psutil powers the core metrics; GPU stats come from
nvidia-ml-py3 (pynvml) when an NVIDIA GPU is present, and degrade gracefully
otherwise. Temperature is best-effort via psutil.sensors_temperatures (Linux)
or WMI on Windows when available.
"""

from __future__ import annotations

import ctypes
import datetime as _dt
import os
import platform
import shutil
from typing import Any, Dict

from .registry import register


def _bytes_human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if n < 1024.0:
            return f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}EB"


def _get_cpu_name() -> str:
    """Retrieve the actual CPU processor name/model string."""
    if platform.system() == "Windows":
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            val = winreg.QueryValueEx(k, "ProcessorNameString")[0]
            if val and str(val).strip():
                return str(val).strip()
        except Exception:
            pass
    proc = platform.processor()
    if proc and proc.strip():
        return proc.strip()
    return os.environ.get("PROCESSOR_IDENTIFIER", "Unknown Processor")


def _get_windows_version_info() -> Dict[str, str]:
    """Retrieve detailed Windows version information, including Windows 11 detection."""
    arch = platform.machine() or "64-bit"
    if platform.system() != "Windows":
        return {
            "os_name": platform.platform(),
            "product_name": platform.system(),
            "build": platform.release(),
            "architecture": arch,
        }

    product = "Windows"
    display_version = ""
    build = ""
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion")
        try:
            product = winreg.QueryValueEx(k, "ProductName")[0]
        except OSError:
            pass
        try:
            display_version = winreg.QueryValueEx(k, "DisplayVersion")[0]
        except OSError:
            pass
        try:
            build = str(winreg.QueryValueEx(k, "CurrentBuild")[0])
        except OSError:
            pass
    except Exception:
        pass

    if build.isdigit() and int(build) >= 22000 and "Windows 10" in product:
        product = product.replace("Windows 10", "Windows 11")

    ver_parts = [product]
    if display_version:
        ver_parts.append(display_version)
    if build:
        ver_parts.append(f"(Build {build})")
    ver_parts.append(arch)

    return {
        "os_name": " ".join(ver_parts),
        "product_name": product,
        "display_version": display_version,
        "build": build,
        "architecture": arch,
    }


@register("systemInfo")
def system_info(args: Dict[str, Any]) -> Dict[str, Any]:
    # Try importing psutil; if not available, fallback to pure Windows APIs / stdlib
    psutil = None
    try:
        import psutil as _psutil
        psutil = _psutil
    except ImportError:
        psutil = None

    # 1. CPU / Processor
    cpu_name = _get_cpu_name()
    if psutil:
        try:
            cpu_percent = psutil.cpu_percent(interval=0.3)
        except Exception:
            cpu_percent = None
        cpu_count_logical = psutil.cpu_count(logical=True) or (os.cpu_count() or 1)
        cpu_count_physical = psutil.cpu_count(logical=False) or cpu_count_logical
    else:
        cpu_percent = None
        cpu_count_logical = os.cpu_count() or 1
        cpu_count_physical = cpu_count_logical

    cpu_usage_str = f", {cpu_percent}% usage" if cpu_percent is not None else ""
    cpu_str = f"{cpu_name} ({cpu_count_physical} cores / {cpu_count_logical} threads{cpu_usage_str})"

    # 2. RAM
    ram_total = 0
    ram_used = 0
    ram_percent = 0
    if psutil:
        try:
            vm = psutil.virtual_memory()
            ram_total = vm.total
            ram_used = vm.used
            ram_percent = vm.percent
        except Exception:
            pass

    if ram_total == 0 and platform.system() == "Windows":
        try:
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                ram_total = stat.ullTotalPhys
                ram_used = stat.ullTotalPhys - stat.ullAvailPhys
                ram_percent = stat.dwMemoryLoad
        except Exception:
            pass

    ram_str = f"{_bytes_human(ram_total)} total ({_bytes_human(ram_used)} used, {ram_percent}% load)"

    # 3. Disks
    disks: Dict[str, Dict[str, Any]] = {}
    if psutil:
        seen = set()
        try:
            for part in psutil.disk_partitions(all=False):
                mp = part.mountpoint
                if mp in seen:
                    continue
                seen.add(mp)
                try:
                    du = psutil.disk_usage(mp)
                    disks[mp] = {
                        "total": _bytes_human(du.total),
                        "used": _bytes_human(du.used),
                        "free": _bytes_human(du.free),
                        "percent": du.percent,
                    }
                except Exception:
                    continue
        except Exception:
            pass

    if not disks:
        system_drive = os.environ.get("SystemDrive", "C:") + "\\"
        try:
            du_std = shutil.disk_usage(system_drive)
            used_pct = round(((du_std.total - du_std.free) / du_std.total) * 100, 1) if du_std.total else 0
            disks[system_drive] = {
                "total": _bytes_human(du_std.total),
                "used": _bytes_human(du_std.total - du_std.free),
                "free": _bytes_human(du_std.free),
                "percent": used_pct,
            }
        except Exception:
            pass

    # 4. Uptime
    uptime_seconds = 0
    uptime_str = "Unknown"
    if psutil:
        try:
            boot = psutil.boot_time()
            uptime_td = _dt.datetime.now() - _dt.datetime.fromtimestamp(boot)
            uptime_seconds = int(uptime_td.total_seconds())
            uptime_str = str(uptime_td).split(".")[0]
        except Exception:
            pass

    if uptime_seconds == 0 and platform.system() == "Windows":
        try:
            ms = ctypes.windll.kernel32.GetTickCount64()
            uptime_td = _dt.timedelta(milliseconds=ms)
            uptime_seconds = int(uptime_td.total_seconds())
            uptime_str = str(uptime_td).split(".")[0]
        except Exception:
            pass

    # 5. Battery
    battery_info: Dict[str, Any] | None = None
    battery_str = ""
    if psutil and hasattr(psutil, "sensors_battery"):
        try:
            battery = psutil.sensors_battery()
            if battery is not None:
                secs = battery.secsleft if battery.secsleft >= 0 else None
                time_left_str = ""
                if secs is not None:
                    m, s = divmod(secs, 60)
                    h, m = divmod(m, 60)
                    time_left_str = f" ({h}h {m}m remaining)"
                charging_str = "plugged in" if battery.power_plugged else "on battery"
                battery_str = f" Battery {battery.percent}% ({charging_str}{time_left_str})."
                battery_info = {
                    "percent": battery.percent,
                    "power_plugged": battery.power_plugged,
                    "secsleft": secs,
                }
        except Exception:
            pass

    if battery_info is None and platform.system() == "Windows":
        try:
            class SYSTEM_POWER_STATUS(ctypes.Structure):
                _fields_ = [
                    ("ACLineStatus", ctypes.c_byte),
                    ("BatteryFlag", ctypes.c_byte),
                    ("BatteryLifePercent", ctypes.c_byte),
                    ("SystemStatusFlag", ctypes.c_byte),
                    ("BatteryLifeTime", ctypes.c_ulong),
                    ("BatteryFullLifeTime", ctypes.c_ulong),
                ]

            sps = SYSTEM_POWER_STATUS()
            if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(sps)):
                pct = sps.BatteryLifePercent
                if pct <= 100:
                    plugged = sps.ACLineStatus == 1
                    charging_str = "plugged in" if plugged else "on battery"
                    secs = int(sps.BatteryLifeTime) if sps.BatteryLifeTime != 0xFFFFFFFF and not plugged else None
                    time_left_str = ""
                    if secs is not None:
                        m, s = divmod(secs, 60)
                        h, m = divmod(m, 60)
                        time_left_str = f" ({h}h {m}m remaining)"
                    battery_str = f" Battery {pct}% ({charging_str}{time_left_str})."
                    battery_info = {
                        "percent": pct,
                        "power_plugged": plugged,
                        "secsleft": secs,
                    }
        except Exception:
            pass

    # 6. Windows Version & Architecture
    os_info = _get_windows_version_info()

    return {
        "result": (
            f"Processor: {cpu_str}. "
            f"RAM: {ram_str}. "
            f"OS: {os_info['os_name']}. "
            f"Storage: {len(disks)} disk(s) monitored. "
            f"Uptime: {uptime_str}.{battery_str}"
        ),
        "specifications": {
            "processor": cpu_name,
            "physical_cores": cpu_count_physical,
            "logical_cores": cpu_count_logical,
            "cpu_percent": cpu_percent,
            "ram_total": _bytes_human(ram_total),
            "ram_used": _bytes_human(ram_used),
            "ram_percent": ram_percent,
            "os": os_info["os_name"],
            "windows_build": os_info["build"],
            "architecture": os_info["architecture"],
        },
        "cpu": {
            "model": cpu_name,
            "percent": cpu_percent,
            "physical_cores": cpu_count_physical,
            "logical_cores": cpu_count_logical,
        },
        "ram": {
            "percent": ram_percent,
            "used": _bytes_human(ram_used),
            "total": _bytes_human(ram_total),
        },
        "disks": disks,
        "uptime_seconds": uptime_seconds,
        "battery": battery_info,
        "os": os_info["os_name"],
        "architecture": os_info["architecture"],
    }


def _gpu_stats() -> list:
    try:
        import pynvml  # type: ignore
        from pynvml import (  # type: ignore
            NVML_TEMPERATURE_GPU,
            NVML_CLOCK_GRAPHICS,
            NVML_CLOCK_MEM,
            nvmlInit,
            nvmlDeviceGetCount,
            nvmlDeviceGetHandleByIndex,
            nvmlDeviceGetName,
            nvmlDeviceGetUtilizationRates,
            nvmlDeviceGetMemoryInfo,
            nvmlDeviceGetTemperature,
            nvmlDeviceGetClockInfo,
        )
    except Exception:
        return []

    gpus = []
    try:
        nvmlInit()
        count = nvmlDeviceGetCount()
        for i in range(count):
            h = nvmlDeviceGetHandleByIndex(i)
            util = nvmlDeviceGetUtilizationRates(h)
            mem = nvmlDeviceGetMemoryInfo(h)
            gpus.append(
                {
                    "index": i,
                    "name": nvmlDeviceGetName(h).decode() if isinstance(nvmlDeviceGetName(h), bytes) else str(nvmlDeviceGetName(h)),
                    "gpu_utilization_percent": util.gpu,
                    "memory_utilization_percent": util.memory,
                    "memory_total": _bytes_human(mem.total),
                    "memory_used": _bytes_human(mem.used),
                    "memory_free": _bytes_human(mem.free),
                    "temperature_c": nvmlDeviceGetTemperature(h, NVML_TEMPERATURE_GPU),
                }
            )
    except Exception:
        return []
    return gpus


@register("gpuInfo")
def gpu_info(args: Dict[str, Any]) -> Dict[str, Any]:
    gpus = _gpu_stats()
    if not gpus:
        return {
            "result": (
                "No NVIDIA GPU stats available via pynvml (no NVIDIA GPU, "
                "driver missing, or nvidia-ml-py3 not installed)."
            ),
            "gpus": [],
        }
    summary = "; ".join(
        f"{g['name']}: {g['gpu_utilization_percent']}% GPU, "
        f"{g['memory_used']}/{g['memory_total']} VRAM, {g['temperature_c']}°C"
        for g in gpus
    )
    return {"result": summary, "gpus": gpus}


@register("temperatureInfo")
def temperature_info(args: Dict[str, Any]) -> Dict[str, Any]:
    # Prefer GPU temp if available (NVIDIA), then psutil sensors.
    gpus = _gpu_stats()
    temps: Dict[str, Any] = {}
    for g in gpus:
        temps[f"gpu{g['index']}"] = g["temperature_c"]

    try:
        import psutil

        sensors = psutil.sensors_temperatures() if hasattr(psutil, "sensors_temperatures") else {}
        for name, entries in (sensors or {}).items():
            for entry in entries[:1]:
                temps[name] = entry.current
    except Exception:
        pass

    # Windows CPU temps generally require admin + OpenHardwareMonitor/LibreHardwareMonitor.
    if not temps:
        return {
            "result": (
                "Temperature reading unavailable. On Windows, CPU temps need "
                "LibreHardwareMonitor or admin access; GPU temps need an NVIDIA GPU."
            ),
            "temperatures": {},
        }
    summary = ", ".join(f"{k}={v}°C" for k, v in temps.items())
    return {"result": f"Temperatures: {summary}.", "temperatures": temps}


__all__ = ["system_info", "gpu_info", "temperature_info"]
