# Architecture: Words (Offline Writing Assistant)

"Words" is a minimalist, 100% offline writing assistant for Windows. It provides contextual grammar/spelling correction, paraphrasing, and humanizing without sending any data to the cloud.

---

## 1. High-Level Topology

```
+-----------------------------------------------------------+
|                   Desktop UI (pywebview)                  |
|  - app.py: Native Win32 window, taskbar icon, app lifecycle|
|  - ui/index.html: Vanilla JS/CSS UI, dual-panel, diff cards|
+-----------------------------+-----------------------------+
                              | HTTP (http://127.0.0.1:8787)
+-----------------------------v-----------------------------+
|               Node.js Engine (engine/server.mjs)          |
|  - REST API & Request Routing                             |
|  - Prompt Engineering & Word-Level Diff Extraction        |
|  - Protected Patterns Filter (hotkeys, URLs, code tokens)  |
|  - Dynamic LLM Lifecycle Manager (on-demand / 60s idle)   |
+--------------+-----------------------------+--------------+
               |                             |
       In-Process WASM               Spawned Subprocess
               |                     (http://127.0.0.1:8088)
               v                             v
+-----------------------------+ +---------------------------+
|    Harper Grammar Engine    | |    llama-server (bin/)    |
| - harper.js (Rust -> WASM)  | | - llama.cpp HTTP server   |
| - Custom technical dictionary| | - Model: Qwen2.5-3B-      |
| - Fast linter & fallback    | |   Instruct (Q4_K_M GGUF)  |
+-----------------------------+ +---------------------------+
```

---

## 2. Core Components

### 2.1 Desktop Shell (`app.py`)
- **Technology**: Python 3 + `pywebview` (EdgeChromium runtime).
- **Responsibilities**:
  - Sets Windows `AppUserModelID` (`com.words.assistant`) and Win32 icon properties for clean taskbar grouping.
  - Checks if the background engine is alive on port `8787`; auto-launches `node engine/server.mjs` via `subprocess.Popen` if offline.
  - Ensures clean engine termination on app exit.

### 2.2 Frontend UI (`ui/index.html`)
- **Technology**: Vanilla HTML5, CSS3, ES6 JavaScript (zero heavy frameworks).
- **Features**:
  - Two-pane layout: Original Text vs Polished Result.
  - Interactive "Error Detected" cards (`token_wrong` &rarr; `token_fix`) categorized by Spelling, Grammar, or Capitalization.
  - Live heartbeat polling (`/status`) showing model load state and idle countdown.
  - Adaptive light/dark theming via CSS variables and `prefers-color-scheme`.

### 2.3 Backend Engine Coordinator (`engine/server.mjs`)
- **Technology**: Node.js HTTP Server (`http`, `child_process`).
- **Port**: `127.0.0.1:8787`.
- **Responsibilities**:
  - **Prompt Execution**: Implements specialized system prompts for Grammar, Paraphrase, and Humanize.
  - **Diff Extraction**: Computes token-level differences (`extractWordDiffs`) between input and LLM output to produce inspectable issue cards.
  - **Entity Protection**: Preserves hotkeys (e.g., `Ctrl+Alt+W`), file extensions, code identifiers, and URLs using regex guardrails.
  - **Graceful Fallback**: If LLM execution fails or is unavailable, seamlessly falls back to Harper WASM.

### 2.4 LLM Lifecycle Manager (`LlamaManager` in `server.mjs`)
- **Runtime**: `bin/llama-server.exe` (`llama.cpp` binary) serving `models/qwen2.5-3b-instruct-q4_k_m.gguf` on port `8088`.
- **Resource Constraints**: Designed for low-spec dual-core CPUs with 8 GB RAM (e.g., Intel Core i3).
- **On-Demand Loading**: Process is only spawned when an LLM feature (Grammar, Paraphrase, Humanize) is invoked.
- **60-Second Auto-Unload**: An inactivity timer terminates `llama-server.exe` (`taskkill /t /f`) after 60s of silence to immediately free ~2 GB RAM.

### 2.5 Local Grammar Linter (`HarperManager`)
- **Technology**: `harper.js` (Rust engine compiled to WebAssembly with American English dialect).
- **Role**: Instant, near-zero RAM grammar and spell-checking with technical vocabulary injection (`COMMON_TECH_WORDS`). Serves as fallback and rule validation.

---

## 3. API Contract (`127.0.0.1:8787`)

| Endpoint | Method | Input Payload | Output / Description |
|---|---|---|---|
| `/health`, `/status` | `GET` | _None_ | Engine health, Harper readiness, LLM state (`unloaded`, `loading`, `ready`, `processing`), and idle seconds remaining. |
| `/check` | `POST` | `{"text": "..."}` | Runs contextual grammar check via LLM (or Harper fallback). Returns `{text, correctedText, lints}`. |
| `/paraphrase` | `POST` | `{"text": "..."}` | Rewrites text for clarity, intellectual depth, and syntactic variety. Returns `{original, result}`. |
| `/humanize` | `POST` | `{"text": "..."}` | Rewrites text to remove robotic AI tropes, varying sentence rhythm. Returns `{original, result}`. |
| `/correct-all` | `POST` | `{"text": "...", "mode": "..."}` | Chained pipeline: Harper grammar check &rarr; optional Paraphrase/Humanize. |
| `/unload` | `POST` | _None_ | Forces immediate unload of `llama-server.exe` to reclaim RAM. |
| `/shutdown` | `POST` | _None_ | Unloads LLM and gracefully terminates the Node.js server. |

---

## 4. Key Design Patterns & Guarantees

1. **Strict Offline & Local-Only**: All bindings strictly listen on `127.0.0.1`. No telemetry, analytics, or external web requests.
2. **Aggressive RAM Management**: Idle footprint is limited to Node.js and PyWebView (~50–100 MB). The 2 GB LLM is completely purged after 60s of inactivity.
3. **Idempotent Token Preservation**: Shortcut expressions, file paths, and technical acronyms are immune to typo replacement via regex masks.
4. **Resilient Startup**: PyWebView window (`app.py`) can launch independently and automatically boot the engine service if it is not already running.
