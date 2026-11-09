# Words — Offline AI Writing Assistant

<div align="center">

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%2011%20%7C%2010-0078D6.svg?logo=windows&logoColor=white)](https://microsoft.com)
[![Privacy](https://img.shields.io/badge/Privacy-100%25%20Offline-success.svg)](#privacy--offline-guarantee)
[![Runtime](https://img.shields.io/badge/Engine-Node.js%20%2B%20Python-339933.svg?logo=node.js&logoColor=white)](engine/)
[![Model](https://img.shields.io/badge/LLM-Qwen2.5--3B--Instruct--Q4_K_M-purple.svg)](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF)
[![Grammar Linter](https://img.shields.io/badge/Linter-Harper%20WASM-orange.svg)](https://github.com/Automattic/harper)

**A minimalist, blazingly fast, 100% offline writing assistant for Windows.**  
Fix grammar, paraphrase complex ideas, and humanize synthetic prose — entirely on your local machine with zero telemetry.

[Features](#key-features) • [Architecture](#architecture) • [Getting Started](#quick-start) • [API Specs](#api-specification) • [Memory Management](#aggressive-memory-lifecycle)

</div>

---

## Overview

**Words** is an offline alternative to cloud-reliant writing assistants like Grammarly. Designed from the ground up for low-spec dual-core and quad-core laptops (e.g., Intel Core i3 with 8 GB RAM), it marries instant WebAssembly-powered linting with on-demand local quantized LLM inference.

### Why Words?
- 🔒 **100% Offline & Private**: Zero external API calls, zero analytics, zero data leaves your local device (`127.0.0.1` binding only).
- ⚡ **Near-Zero Idle Footprint**: Idle memory consumption is ~50–100 MB. The ~2 GB LLM is loaded strictly on demand and automatically purged from RAM after 60 seconds of inactivity.
- 🛡️ **Code & Hotkey Immunity**: Keyboard shortcuts (`Ctrl+Alt+W`), file extensions, identifiers, and URLs are protected by regex guardrails and will never be mangled.
- 🎯 **Visual Diff Inspection**: Interactive token-level diff cards highlight changes with categorized tags (*Spelling*, *Grammar*, *Capitalization*).
- 🌓 **Native Windows Experience**: EdgeChromium native desktop window (`pywebview`), system theme detection, and dedicated taskbar integration.

---

## Key Features

| Capability | Engine | Latency / Cost | Description |
|---|---|---|---|
| **Contextual Grammar Check** | Local LLM / Harper WASM | Fast (~1–3s) | Identifies contextual spelling errors, subject-verb disagreements, punctuation, and casing mistakes. |
| **Paraphrase** | Qwen2.5-3B-Instruct | Local CPU | Rewrites text with intellectual depth, lexical sophistication, and syntactic variety while strictly preserving technical vocabulary. |
| **Humanize** | Qwen2.5-3B-Instruct | Local CPU | Eliminates robotic AI tropes (*"delve"*, *"testament"*, *"tapestry"*), introducing dynamic sentence burstiness and human cadence. |
| **Correct All Pipeline** | Harper + LLM Chained | Hybrid | Runs instantaneous Harper WASM grammar correction first, then chains into paraphrase or humanization. |
| **Visual Diff Inspector** | Real-time JS / Tokenizer | Instant | Generates inspectable correction cards (`token_wrong` &rarr; `token_fix`) with actionable reason tooltips. |

---

## Architecture

```
+-------------------------------------------------------------+
|                  Desktop UI (pywebview)                     |
|  - app.py: Native Win32 window, taskbar grouping, AppUserModelID
|  - ui/index.html: Vanilla ES6/CSS3, dual-panel split view   |
+------------------------------+------------------------------+
                               | HTTP (http://127.0.0.1:8787)
+------------------------------v------------------------------+
|               Node.js Engine (engine/server.mjs)            |
|  - REST API & CORS Preflight                                |
|  - Protected Range Filters (hotkeys, URLs, filenames)       |
|  - Token-Level Diff Extraction (extractWordDiffs)           |
|  - Dynamic LLM Process Manager (On-Demand / 60s Idle Auto-Kill)
+---------------+------------------------------+---------------+
                |                              |
        In-Process WASM                Spawned Subprocess
                |                      (http://127.0.0.1:8088)
                v                              v
+------------------------------+ +----------------------------+
|     Harper Grammar Engine    | |    llama-server.exe (bin/) |
|  - harper.js (Rust -> WASM)  | |  - llama.cpp HTTP server   |
|  - Technical dictionary      | |  - Model: Qwen2.5-3B-      |
|  - Instant linting & fallback| |    Instruct (Q4_K_M GGUF)  |
+------------------------------+ +----------------------------+
```

---

## Aggressive Memory Lifecycle

To run seamlessly on resource-constrained hardware (e.g. 8 GB RAM machines):

```
User Action (Paraphrase/Humanize)
             │
             ▼
   Is LLM running?
     ├── YES ────► Execute generation immediately
     └── NO  ────► Spawn llama-server.exe (loads 2 GB into RAM)
                          │
                          ▼
                   Execute Generation
                          │
                          ▼
            Start 60s Inactivity Countdown
                          │
         ┌────────────────┴────────────────┐
         ▼                                 ▼
   New request arrives?            Timer reaches 60s
   ├── YES ──► Reset timer         └── NO ──► Execute taskkill /t /f
                                              Reclaim 2 GB RAM instantly
```

---

## Quick Start

### 1. Prerequisites
- **OS**: Windows 10 or 11 (64-bit)
- **Python**: 3.10+ ([python.org](https://www.python.org/downloads/))
- **Node.js**: 18+ ([nodejs.org](https://nodejs.org/))

### 2. Automated One-Click Setup

Run `setup.bat` to install all dependencies and create the necessary directories:

```cmd
setup.bat
```

### 3. Model & Binary Setup

1. **Download the GGUF model (~2.1 GB)**:
   - Download [`qwen2.5-3b-instruct-q4_k_m.gguf`](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf).
   - Place it inside the `models/` directory:
     ```
     models/qwen2.5-3b-instruct-q4_k_m.gguf
     ```

2. **Download llama.cpp Windows binaries**:
   - Download the latest Windows release (`llama-b*-bin-win-cpu-x64.zip`) from [llama.cpp releases](https://github.com/ggerganov/llama.cpp/releases).
   - Extract `llama-server.exe` and its supporting DLLs (`llama.dll`, `ggml.dll`, `libomp.dll`) into the `bin/` directory:
     ```
     bin/llama-server.exe
     bin/*.dll
     ```

### 4. Launching the Assistant

- **Start**: Double-click `start.bat` (or run `python app.py`).
- **Stop**: Double-click `stop.bat` to gracefully terminate all engine and LLM background services.

---

## API Specification

The Node.js engine service binds strictly to `http://127.0.0.1:8787`.

### Endpoints

#### `GET /health` or `GET /status`
Returns service readiness, Harper status, and LLM runtime lifecycle metrics.
```json
{
  "status": "ok",
  "harperReady": true,
  "llm": {
    "state": "ready",
    "idleSecondsLeft": 48,
    "activeRequests": 0,
    "modelLoaded": true,
    "modelFileExists": true,
    "binExists": true
  }
}
```

#### `POST /check`
Runs contextual grammar and spell check. Falls back to Harper WASM if LLM is unavailable.
- **Request**:
  ```json
  { "text": "Hwo can help me with this orher feature?" }
  ```
- **Response**:
  ```json
  {
    "text": "Hwo can help me with this orher feature?",
    "correctedText": "Who can help me with this other feature?",
    "lints": [
      {
        "problemText": "Hwo",
        "suggestions": ["Who"],
        "kind": "Spelling",
        "message": "Correct 'Hwo' to 'Who'"
      },
      {
        "problemText": "orher",
        "suggestions": ["other"],
        "kind": "Spelling",
        "message": "Correct 'orher' to 'other'"
      }
    ],
    "engine": "llama"
  }
  ```

#### `POST /paraphrase`
Rewrites text to achieve intellectual depth and lexical richness while preserving technical terms.
- **Request**:
  ```json
  { "text": "The server is slow because the database has too many queries running at once." }
  ```
- **Response**:
  ```json
  {
    "original": "The server is slow because the database has too many queries running at once.",
    "result": "Elevated query contention and concurrent transaction volume are measurably degrading server throughput."
  }
  ```

#### `POST /humanize`
Rewrites text into natural, rhythmic prose devoid of formulaic AI markers.
- **Request**:
  ```json
  { "text": "It is important to note that the implementation utilizes quantized neural weights to mitigate excessive memory consumption." }
  ```
- **Response**:
  ```json
  {
    "original": "It is important to note...",
    "result": "By compressing the model's weights down to 4-bit chunks, we keep it nimble enough to run without hogging your laptop's RAM."
  }
  ```

#### `POST /unload`
Immediately terminates `llama-server.exe` to reclaim ~2 GB of RAM without waiting for the 60-second idle timer.

#### `POST /shutdown`
Unloads the LLM and initiates a graceful shutdown of the Node.js server.

---

## Project Structure

```
grammar_checker/
├── Assets/
│   ├── Icons/             # Windows icons (.ico and multi-res .png)
│   └── words_icon.png
├── bin/                   # llama.cpp binaries (git-ignored)
│   └── README.md          # Download and placement instructions
├── engine/
│   ├── node_modules/      # Engine dependencies (git-ignored)
│   ├── package.json       # Node package configuration
│   └── server.mjs         # Core backend engine, Harper & llama coordinator
├── models/                # GGUF quantized models (git-ignored)
│   └── README.md          # Model download guide
├── ui/
│   ├── favicon.png
│   ├── logo.png
│   └── index.html         # Vanilla JS/CSS dual-panel desktop UI
├── app.py                 # Desktop launcher (pywebview + Win32 taskbar integration)
├── start.bat              # One-click launch script
├── stop.bat               # One-click clean shutdown script
├── setup.bat              # One-click dependency setup script
├── requirements.txt       # Pinned Python dependencies
├── .gitignore             # Airtight exclusion rules
├── LICENSE                # MIT License
└── README.md              # Project documentation
```

---

## Privacy & Offline Guarantee

- **Zero Telemetry**: No tracking, phone-home code, or analytics.
- **Loopback Only**: All network services explicitly bind to `127.0.0.1`.
- **Self-Contained**: Operates fully disconnected from the internet once model weights and dependencies are downloaded.

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
