"""MYRAA Desktop Control Agent.

A local FastAPI service exposing JARVIS-style desktop automation tools that
MYRAA's Node bridge (server.ts) calls over HTTP. This module package only
hosts tool code; run with:

    uvicorn desktop_agent.main:app --host 127.0.0.1 --port 8765
"""

__version__ = "1.0.0"

import ctypes
import platform

if platform.system() == "Windows":
    try:
        hdesk = ctypes.windll.user32.OpenInputDesktop(0, False, 0x01FF)
        if hdesk:
            ctypes.windll.user32.SetThreadDesktop(hdesk)
    except Exception:
        pass
