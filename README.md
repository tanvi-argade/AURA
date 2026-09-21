# AURA — Adaptive Unified Reasoning Assistant

AURA is a voice-based AI desktop assistant designed for Windows.

The assistant, **MIA**, provides a natural voice interface for interacting with the computer and performing desktop tasks through AI-powered commands.

## Features

* Voice-based interaction
* Gemini Live integration
* Windows application control
* File and folder operations
* Screenshot and screen analysis
* Browser interaction
* System information
* Volume and brightness controls
* Clipboard operations
* Desktop automation
* Memory support
* OCR and screenshot analysis

## Technology Stack

* React
* TypeScript
* Vite
* Electron
* Node.js
* Express
* Python
* FastAPI
* Gemini API
* WebSocket

## Project Structure

```text
src/              React frontend
electron/         Electron desktop application
desktop_agent/    Python desktop-control agent
server.ts         Node.js backend
server_memory.ts  Memory handling
run_agent.py      Python agent launcher
```

## How It Works

```text
User
  ↓
MIA
  ↓
React / Electron
  ↓
Node.js Server
  ↓
Gemini Live
  ↓
Python Desktop Agent
  ↓
Windows
```

## Local Setup

### 1. Install Node dependencies

```bash
npm install
```

### 2. Create Python virtual environment

```bash
python -m venv .venv
```

Activate it on Windows:

```powershell
.\.venv\Scripts\Activate.ps1
```

### 3. Install Python dependencies

```powershell
python -m pip install -r desktop_agent\requirements.txt
```

### 4. Configure environment variables

Create a `.env` file using `.env.example` and add the required API credentials.


### 5. Build the application

```bash
npm run build
```

### 6. Run the Electron application

```bash
npm run electron
```

## Development Status

AURA is currently under active development.

The core Electron application, Gemini Live connection, Node.js backend, and Python desktop-control agent are working. Individual desktop capabilities are still being tested and refined.

## Project Name

**AURA — Adaptive Unified Reasoning Assistant**

**AI Assistant:** MIA
