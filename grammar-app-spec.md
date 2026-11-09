# Offline Writing Assistant: Project Spec (Windows, v1)

## 1. Goal

A minimalist, offline Grammarly alternative for Windows 11. Version 1 is a Windows desktop app that opens as a popup over any app. A browser extension comes later and talks to the same local engine.

## 2. Target Machine

- Infinix Inbox X1
- Intel Core i3-1005G1 (2 cores, 4 threads)
- 8 GB RAM
- Intel UHD graphics (no dedicated GPU, so no GPU inference)
- Windows 11

Design rule: the app must stay light. Idle RAM use should be small, and the LLM must not stay loaded when unused.

## 3. Features

1. **Grammar and spelling:** Harper, a Rust-based offline checker. Fast and light. Covers English only in v1.
2. **Paraphrase:** Local LLM, Qwen2.5-3B-Instruct (or Llama 3.2 3B Instruct), quantized to Q4_K_M (about 2 GB). Verify the exact model and file before download.
3. **Humanizer:** Local LLM with a style prompt that rewrites text in a more natural voice. It is a style rewrite only. It does not guarantee passing AI detectors.
4. **Correct All:** One button runs grammar first, then paraphrase or humanize if selected, and shows a single result for review.
5. **Manual trigger only:** Nothing runs in the background. Work starts only when the user presses a button or the hotkey.

## 4. User Interface

- Minimalist popup window: input area, result area, and three buttons (Grammar, Paraphrase, Humanize) plus Correct All.
- Copy and Replace buttons for the result.
- Theme follows Windows light or dark mode. Read the system setting and apply matching CSS variables.
- Clean, few borders, one accent color, no clutter.

## 5. Interaction

- Global hotkey: **Ctrl+Alt+G** opens the popup.
- Flow: the user selects text in any app, presses Ctrl+Alt+G, the app copies the selection, the popup shows it, the user picks an action, and Replace pastes the result back into the original app.
- Fallback: if the copy step fails, the popup opens empty for manual paste.

## 6. Resource Management

- **LLM loads on demand.** The model loads when the user first requests paraphrase or humanize.
- **Unload after 60 seconds idle** to free roughly 2 GB of RAM.
- Harper runs on demand as well, so grammar checks start instantly and use very little memory.
- Show a small status line ("Loading model...") during the first load, since it may take several seconds on this CPU.

## 7. Architecture

```
+------------------------------+
|  Tauri popup (UI, Windows)   |
|  - theme detection           |
|  - hotkey handler            |
+--------------+---------------+
               | local HTTP (127.0.0.1 only)
+--------------v---------------+
|  Engine service              |
|  - Harper (grammar)          |
|  - llama.cpp server (LLM)    |
|    loaded on demand,        |
|    unloaded after 60s idle   |
+------------------------------+
```

- **Shell:** Tauri (Rust), not Electron, to keep RAM low.
- **LLM runtime:** llama.cpp (llama-server), run locally.
- **Grammar engine:** Harper, called from the engine service.
- **Browser extension (later):** connects to the same local engine on 127.0.0.1.

## 8. Offline Requirement

- Everything runs on the device after the one-time model and dependency download.
- No telemetry, no cloud calls, no account.
- Local server binds to 127.0.0.1 only.

## 9. Out of Scope for v1

- Browser extension
- Languages other than English (LanguageTool is the planned upgrade path)
- Real-time (as-you-type) checking
- Background or automatic checking
- Plagiarism or AI-detector scoring

## 10. Open Items to Confirm During Build

- Exact model file and its RAM use on this laptop (test first)
- Real token speed on the i3-1005G1 (expected to be low, roughly 3-8 tokens per second; measure)
- Reliability of the copy-and-paste method in apps that block clipboard access
- Whether the popup should stay on top of other windows

## 11. Acceptance Checklist

- [ ] Ctrl+Alt+G opens the popup from any app
- [ ] Popup follows Windows light/dark mode
- [ ] Grammar check returns results offline
- [ ] Paraphrase and humanize work offline after the first load
- [ ] Model unloads after 60 seconds idle (verify in Task Manager)
- [ ] Idle RAM use stays low when the model is unloaded
- [ ] Correct All runs grammar then the selected rewrite mode
- [ ] Replace pastes the result back into the original app
