import http from 'node:http';
import { spawn, exec } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import fs from 'node:fs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const PORT = 8787;
const LLAMA_PORT = 8088;
const IDLE_TIMEOUT_MS = 60 * 1000; // 60s idle unload

const BIN_DIR = path.resolve(__dirname, '..', 'bin');
const MODELS_DIR = path.resolve(__dirname, '..', 'models');
const LLAMA_EXE = path.join(BIN_DIR, 'llama-server.exe');
const MODEL_FILE = path.join(MODELS_DIR, 'qwen2.5-3b-instruct-q4_k_m.gguf');

// Cache model existence check
let cachedModelFileExists = fs.existsSync(MODEL_FILE);

const COMMON_TECH_WORDS = [
  'Ctrl', 'Control', 'Alt', 'Shift', 'Cmd', 'Command', 'Win', 'hotkey', 'hotkeys',
  'shortcut', 'shortcuts', 'wording', 'prompting', 'quantized', 'quantization',
  'GGUF', 'LLM', 'LLMs', 'API', 'APIs', 'frontend', 'backend', 'UI', 'UX', 'CLI',
  'repo', 'repos', 'WASM', 'runtime', 'latency', 'token', 'tokens', 'inference',
  'embeddings', 'GPU', 'CPU', 'AVX', 'AVX2', 'multimodal', 'hyperparameter',
  'fine-tuning', 'fine-tuned', 'params', 'dataset', 'datasets', 'localhost',
  'daemon', 'subagent', 'antigravity', 'IDE', 'SDK', 'MSVC', 'config', 'configs',
  'async', 'sync', 'taskbar', 'popup', 'minimalist', 'keybd', 'pywebview'
];

const PROTECTED_PATTERNS = [
  /\b(?:Ctrl|Control|Alt|Shift|Cmd|Command|Win|Windows|Meta|Option)\+(?:[A-Za-z0-9+]|\b[A-Za-z0-9]+\b)+/gi,
  /\b[\w-]+\.(?:exe|mjs|js|py|json|md|txt|html|css|png|ico|zip|gguf)\b/gi,
  /(?:https?:\/\/|www\.)\S+|[\w.-]+@[\w.-]+\.\w+/gi,
  /\b[A-Z0-9_]{3,}\b/g
];

// ==========================================
// 1. Harper WASM Manager (with init lock)
// ==========================================
class HarperManager {
  constructor() {
    this.linter = null;
    this.ready = false;
    this.initPromise = null;
  }

  async init() {
    if (this.ready) return true;
    if (this.initPromise) return this.initPromise;

    this.initPromise = (async () => {
      try {
        const { LocalLinter, Dialect } = await import('harper.js');
        const { binaryInlined } = await import('harper.js/binaryInlined');
        this.linter = new LocalLinter({ binary: binaryInlined, dialect: Dialect.American });
        await this.linter.setup();

        if (typeof this.linter.importWords === 'function') {
          await this.linter.importWords(COMMON_TECH_WORDS);
        }

        this.ready = true;
        console.log('[Harper] Grammar engine initialized with extended technical vocabulary.');
        return true;
      } catch (err) {
        console.error('[Harper] Failed to initialize:', err);
        this.ready = false;
        throw err;
      } finally {
        this.initPromise = null;
      }
    })();

    return this.initPromise;
  }

  async check(text) {
    if (!this.ready) await this.init();
    if (!text || text.trim().length === 0) {
      return { text: '', lints: [], correctedText: '' };
    }

    const protectedRanges = [];
    for (const pattern of PROTECTED_PATTERNS) {
      let match;
      pattern.lastIndex = 0;
      while ((match = pattern.exec(text)) !== null) {
        protectedRanges.push({ start: match.index, end: match.index + match[0].length });
      }
    }

    const rawLints = await this.linter.lint(text);
    const lints = [];

    for (const item of rawLints) {
      const span = item.span();
      const problem = item.get_problem_text();

      // Overlap check
      const isProtected = protectedRanges.some(r =>
        span.start < r.end && span.end > r.start
      );

      if (isProtected) continue;

      if (problem.toLowerCase() === 'ctrl' && item.message().toLowerCase().includes('informal')) {
        continue;
      }

      const suggestions = item.suggestions().map(s => s.get_replacement_text());
      lints.push({
        message: item.message(),
        kind: item.lint_kind_pretty ? item.lint_kind_pretty() : item.lint_kind(),
        start: span.start,
        end: span.end,
        problemText: problem,
        suggestions
      });
    }

    let correctedText = text;
    const sorted = [...lints].sort((a, b) => b.start - a.start);
    for (const lint of sorted) {
      if (lint.suggestions && lint.suggestions.length > 0) {
        correctedText = correctedText.slice(0, lint.start) + lint.suggestions[0] + correctedText.slice(lint.end);
      }
    }

    return { text, lints, correctedText };
  }
}

// ==========================================
// 2. llama.cpp Lifecycle Manager (Safe Concurrency)
// ==========================================
class LlamaManager {
  constructor() {
    this.process = null;
    this.state = 'unloaded'; // 'unloaded' | 'loading' | 'ready' | 'processing'
    this.idleTimer = null;
    this.lastActiveTime = 0;
    this.loadingPromise = null;
    this.activeRequests = 0;
  }

  clearIdleTimer() {
    if (this.idleTimer) {
      clearTimeout(this.idleTimer);
      this.idleTimer = null;
    }
  }

  armIdleTimer() {
    this.clearIdleTimer();
    // Only arm idle timer if engine is ready and no active requests are running
    if (this.state !== 'ready' || this.activeRequests > 0 || !this.process) {
      return;
    }
    this.lastActiveTime = Date.now();
    this.idleTimer = setTimeout(() => {
      console.log('[LLM] 60s idle threshold reached. Unloading model to reclaim RAM...');
      this.unload();
    }, IDLE_TIMEOUT_MS);
  }

  async ensureReady() {
    if ((this.state === 'ready' || this.state === 'processing') && this.process) {
      return true;
    }
    if (this.loadingPromise) {
      await this.loadingPromise;
      return true;
    }

    this.loadingPromise = this._startServer();
    try {
      await this.loadingPromise;
      return true;
    } catch (err) {
      this.state = 'unloaded';
      throw err;
    } finally {
      this.loadingPromise = null;
    }
  }

  async _startServer() {
    if (!fs.existsSync(LLAMA_EXE)) {
      throw new Error(`llama-server executable not found at ${LLAMA_EXE}`);
    }
    cachedModelFileExists = fs.existsSync(MODEL_FILE);
    if (!cachedModelFileExists) {
      throw new Error(`Model file not found at ${MODEL_FILE}. Please download the model.`);
    }

    this.state = 'loading';
    this.clearIdleTimer();
    console.log(`[LLM] Launching llama-server.exe for model: ${MODEL_FILE}...`);

    const args = [
      '-m', MODEL_FILE,
      '--port', String(LLAMA_PORT),
      '--host', '127.0.0.1',
      '-c', '2048',
      '-t', '4',
      '--log-disable'
    ];

    const currentProcess = spawn(LLAMA_EXE, args, {
      stdio: 'ignore',
      detached: false,
      windowsHide: true
    });
    this.process = currentProcess;

    let hasExited = false;
    currentProcess.on('error', (err) => {
      console.error('[LLM] Server spawn error:', err);
      if (this.process === currentProcess) {
        this.state = 'unloaded';
        this.process = null;
      }
      hasExited = true;
    });

    currentProcess.on('exit', (code, signal) => {
      console.log(`[LLM] llama-server exited with code ${code}, signal ${signal}`);
      if (this.process === currentProcess) {
        this.state = 'unloaded';
        this.process = null;
      }
      hasExited = true;
      this.clearIdleTimer();
    });

    // Poll health endpoint with process liveliness check (max 45 seconds)
    const startTime = Date.now();
    while (Date.now() - startTime < 45000) {
      if (hasExited || this.process !== currentProcess) {
        this.unload();
        throw new Error('llama-server process exited unexpectedly during startup');
      }

      await new Promise(r => setTimeout(r, 600));
      try {
        const resp = await fetch(`http://127.0.0.1:${LLAMA_PORT}/health`);
        if (resp.ok && !hasExited) {
          this.state = 'ready';
          this.armIdleTimer();
          console.log(`[LLM] Model is loaded and ready in ${((Date.now() - startTime) / 1000).toFixed(1)}s!`);
          return;
        }
      } catch (e) {
        // Still initializing
      }
    }

    this.unload();
    throw new Error('llama-server startup timed out after 45s');
  }

  unload() {
    this.clearIdleTimer();
    const proc = this.process;
    this.process = null;
    this.state = 'unloaded';

    if (proc) {
      const pid = proc.pid;
      console.log(`[LLM] Terminating llama-server (PID: ${pid})...`);
      try {
        proc.removeAllListeners();
        if (process.platform === 'win32' && pid) {
          exec(`taskkill /pid ${pid} /t /f`, () => {});
        } else {
          proc.kill('SIGTERM');
        }
      } catch (err) {
        // Already closed or access
      }
    }
    console.log('[LLM] Model unloaded. RAM reclaimed.');
  }

  async generate(systemPrompt, userText) {
    await this.ensureReady();
    this.activeRequests++;
    this.state = 'processing';
    this.clearIdleTimer();

    try {
      const payload = {
        model: 'qwen2.5-3b-instruct',
        messages: [
          { role: 'system', content: systemPrompt },
          { role: 'user', content: userText }
        ],
        temperature: 0.3,
        max_tokens: 1024,
        stream: false
      };

      const response = await fetch(`http://127.0.0.1:${LLAMA_PORT}/v1/chat/completions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!response.ok) {
        throw new Error(`LLM API returned status ${response.status}: ${await response.text()}`);
      }

      const data = await response.json();
      return (data.choices?.[0]?.message?.content || '').trim();
    } finally {
      this.activeRequests = Math.max(0, this.activeRequests - 1);
      // Only set to ready and arm idle timer if engine was not unloaded
      if (this.process && this.state !== 'unloaded') {
        if (this.activeRequests === 0) {
          this.state = 'ready';
          this.armIdleTimer();
        }
      }
    }
  }

  getStatus() {
    const idleSecondsLeft = (this.state === 'ready' && this.lastActiveTime && this.process)
      ? Math.max(0, Math.round((IDLE_TIMEOUT_MS - (Date.now() - this.lastActiveTime)) / 1000))
      : 0;

    return {
      state: this.state,
      idleSecondsLeft,
      activeRequests: this.activeRequests,
      modelLoaded: (this.state === 'ready' || this.state === 'processing') && Boolean(this.process),
      modelFileExists: cachedModelFileExists,
      binExists: fs.existsSync(LLAMA_EXE)
    };
  }
}

// ==========================================
// 3. System Prompts & Word-Level Diffing
// ==========================================
const PROMPT_GRAMMAR = `You are an elite, contextual grammar and spell checker.
Your sole job is to fix all spelling errors, contextual typos, capitalization flaws, grammatical mistakes, and punctuation errors while strictly preserving the author's original meaning, voice, intent, formatting, and technical terms.

EXAMPLES:
- "grammatical error handling works as expecetd with orher features." -> "Grammatical error handling works as expected with other features."
- "If need to pgive all work to LLM give it." -> "If you need to give all work to the LLM, give it."
- "ANlaylyze the full code and fix all bugs and ensure stability. Thansk!" -> "Analyze the full code, fix all bugs, and ensure stability. Thanks!"
- "Hwo can help me with this?" -> "Who can help me with this?"
- "They does not know what happened." -> "They do not know what happened."

CRITICAL DIRECTIVES:
- Correct contextual typos accurately (e.g., "orher" -> "other", "pgive" -> "give", "ANlaylyze" -> "Analyze", "Thansk" -> "Thanks").
- Preserve all keyboard shortcuts, code identifiers, filenames, and formatting.
- Do NOT rewrite or rephrase sentences that are already grammatically sound.
- Output ONLY the corrected text.
- Do NOT output any intro, outro, explanations, pleasantries, or quotes.`;

const PROMPT_PARAPHRASE = `You are a distinguished prose stylist, rhetorician, and senior editor.
Your objective is to rewrite text to achieve intellectual depth, lexical richness ("complex wording"), syntactic variety, and immaculate clarity.

CORE COMPETENCIES & DOMAIN EXAMPLES:

1. Technical & Engineering:
   - Original: "The server is slow because the database has too many queries running at once."
   - Paraphrase: "Elevated query contention and concurrent transaction volume are measurably degrading server throughput."

2. Executive & Analytical:
   - Original: "We looked at the numbers and saw that customers aren't sticking around."
   - Paraphrase: "Cohort retention metrics reveal accelerating customer attrition across recent adoption cycles."

3. Conceptual & Academic:
   - Original: "Language models make mistakes because they guess words instead of knowing facts."
   - Paraphrase: "Autoregressive models hallucinate because they optimize statistical token likelihood rather than deterministic factual epistemology."

4. Tooling & Keybindings (STRICT PRESERVATION):
   - Original: "Press Ctrl+Alt+W in any app to trigger the offline assistant."
   - Paraphrase: "Invoke the offline assistant from any active window using the Ctrl+Alt+W global shortcut."

CRITICAL DIRECTIVES:
- Preserve all keyboard shortcuts, code snippets, API paths, and technical acronyms (LLM, GGUF, WASM, CPU, RAM) exactly as written.
- Employ sophisticated, nuanced, and evocative vocabulary without lapsing into convoluted or archaic syntax.
- Output ONLY the final rewritten text. Do NOT provide preamble, quotes, pleasantries, commentary, or alternatives.`;

const PROMPT_HUMANIZE = `You are an elite literary essayist and conversational stylist.
Your objective is to transform stiff, robotic, synthetic, or academic prose into authentic, engaging, and dynamic human writing.

CORE COMPETENCIES & DOMAIN EXAMPLES:

1. De-clichéing AI Formulations:
   - Original: "It is important to note that the intricate tapestry of modern technology serves as a testament to progress."
   - Humanized: "Modern tech isn't just a collection of flashy tools; it fundamentally reshapes how we get through the day."

2. Conversational Precision:
   - Original: "Individuals must exercise caution regarding the veracity of online assertions."
   - Humanized: "You have to take what you read online with a grain of salt—fact-checking is half the battle now."

3. Explaining Complex Concepts Naturally:
   - Original: "The implementation utilizes quantized neural weights to mitigate excessive memory consumption."
   - Humanized: "By compressing the model's weights down to 4-bit chunks, we keep it nimble enough to run without hogging your laptop's RAM."

CRITICAL DIRECTIVES:
- Banish formulaic AI tropes ("delve", "tapestry", "in conclusion", "testament", "beacon", "it goes without saying").
- Use varied sentence lengths (burstiness), dynamic rhythm, and idiomatic flow that feels distinctly authored by a perceptive human.
- Preserve all shortcuts, technical acronyms, and proper nouns without alteration.
- Output ONLY the final rewritten text. Zero pleasantries or surrounding notes.`;

function extractWordDiffs(original, corrected) {
  if (!original || !corrected) return [];
  const origTokens = original.split(/\s+/).filter(Boolean);
  const corrTokens = corrected.split(/\s+/).filter(Boolean);

  const lints = [];
  let i = 0, j = 0;

  while (i < origTokens.length && j < corrTokens.length) {
    const o = origTokens[i];
    const c = corrTokens[j];

    if (o === c) {
      i++; j++;
      continue;
    }

    const oClean = o.replace(/^[^\w]+|[^\w]+$/g, '');
    const cClean = c.replace(/^[^\w]+|[^\w]+$/g, '');

    // Case 1: Same base word (differ by punctuation or capitalization)
    if (oClean && cClean && oClean.toLowerCase() === cClean.toLowerCase()) {
      if (oClean === cClean && o !== c) {
        lints.push({
          problemText: o,
          suggestions: [c],
          kind: 'Punctuation',
          message: `Update punctuation: '${o}' to '${c}'`
        });
      } else if (oClean !== cClean) {
        lints.push({
          problemText: o,
          suggestions: [c],
          kind: 'Capitalization',
          message: `Change case of '${o}' to '${c}'`
        });
      }
      i++; j++;
    } else {
      // Lookahead 1 word
      if (i + 1 < origTokens.length && origTokens[i + 1] === c) {
        lints.push({
          problemText: o,
          suggestions: [''],
          kind: 'Grammar',
          message: `Remove redundant word '${o}'`
        });
        i++;
      } else if (j + 1 < corrTokens.length && corrTokens[j + 1] === o) {
        lints.push({
          problemText: o,
          suggestions: [c + ' ' + o],
          kind: 'Grammar',
          message: `Insert '${c}'`
        });
        j++;
      } else {
        lints.push({
          problemText: oClean || o,
          suggestions: [cClean || c],
          kind: 'Spelling',
          message: `Correct '${oClean || o}' to '${cClean || c}'`
        });
        i++; j++;
      }
    }
  }

  // Trailing removals in original text
  while (i < origTokens.length) {
    lints.push({
      problemText: origTokens[i],
      suggestions: [''],
      kind: 'Grammar',
      message: `Remove '${origTokens[i]}'`
    });
    i++;
  }

  // Trailing additions in corrected text
  while (j < corrTokens.length) {
    lints.push({
      problemText: origTokens[origTokens.length - 1] || '',
      suggestions: [corrTokens[j]],
      kind: 'Grammar',
      message: `Append '${corrTokens[j]}'`
    });
    j++;
  }

  const seen = new Set();
  return lints.filter(l => {
    const key = `${l.problemText}::${l.suggestions[0]}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).slice(0, 15);
}

// ==========================================
// 4. HTTP Server & Request Handling
// ==========================================
const harper = new HarperManager();
const llama = new LlamaManager();

harper.init().catch(err => {
  console.warn('[Harper] Background initialization deferred:', err.message);
});

function sendJson(res, statusCode, data) {
  if (res.headersSent) return;
  res.writeHead(statusCode, {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type'
  });
  res.end(JSON.stringify(data));
}

function parseJsonBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let length = 0;
    const MAX_SIZE = 2 * 1024 * 1024;

    const onData = chunk => {
      chunks.push(chunk);
      length += chunk.length;
      if (length > MAX_SIZE) {
        cleanup();
        req.destroy();
        const err = new Error('Payload too large (maximum 2MB)');
        err.statusCode = 413;
        reject(err);
      }
    };

    const onEnd = () => {
      cleanup();
      try {
        const raw = Buffer.concat(chunks).toString('utf-8');
        resolve(raw.trim() ? JSON.parse(raw) : {});
      } catch (err) {
        err.statusCode = 400;
        reject(err);
      }
    };

    const onError = err => {
      cleanup();
      reject(err);
    };

    function cleanup() {
      req.removeListener('data', onData);
      req.removeListener('end', onEnd);
      req.removeListener('error', onError);
    }

    req.on('data', onData);
    req.on('end', onEnd);
    req.on('error', onError);
  });
}

const server = http.createServer(async (req, res) => {
  if (req.method === 'OPTIONS') {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type'
    });
    res.end();
    return;
  }

  const host = req.headers.host || `127.0.0.1:${PORT}`;
  let pathname;
  try {
    const url = new URL(req.url, `http://${host}`);
    pathname = url.pathname;
  } catch (err) {
    return sendJson(res, 400, { error: 'Invalid URL' });
  }

  try {
    if (req.method === 'GET' && (pathname === '/health' || pathname === '/status')) {
      return sendJson(res, 200, {
        status: 'ok',
        harperReady: harper.ready,
        llm: llama.getStatus()
      });
    }

    if (req.method === 'POST' && pathname === '/unload') {
      llama.unload();
      return sendJson(res, 200, { success: true, message: 'Model unloaded from RAM' });
    }

    if (req.method === 'POST' && pathname === '/shutdown') {
      sendJson(res, 200, { success: true, message: 'Shutting down engine service' });
      setImmediate(gracefulShutdown);
      return;
    }

    if (req.method === 'POST' && pathname === '/check') {
      const { text } = await parseJsonBody(req);
      if (!text || !text.trim()) {
        return sendJson(res, 200, { text: '', lints: [], correctedText: '' });
      }

      // Try LLM check first if model exists, fallback to Harper WASM
      if (fs.existsSync(LLAMA_EXE) && cachedModelFileExists) {
        try {
          const corrected = await llama.generate(PROMPT_GRAMMAR, text);
          const lints = extractWordDiffs(text, corrected);
          return sendJson(res, 200, { text, correctedText: corrected, lints, engine: 'llama' });
        } catch (err) {
          console.warn('[Server] LLM check failed, using Harper fallback:', err.message);
        }
      }

      try {
        const result = await harper.check(text);
        return sendJson(res, 200, { ...result, engine: 'harper' });
      } catch (hErr) {
        console.error('[Server] Both LLM and Harper failed:', hErr);
        return sendJson(res, 503, { error: 'Grammar checking service currently unavailable' });
      }
    }

    if (req.method === 'POST' && pathname === '/paraphrase') {
      const { text } = await parseJsonBody(req);
      if (!text || !text.trim()) {
        return sendJson(res, 400, { error: 'Text is required for paraphrase' });
      }
      const rewritten = await llama.generate(PROMPT_PARAPHRASE, text);
      return sendJson(res, 200, { result: rewritten, original: text });
    }

    if (req.method === 'POST' && pathname === '/humanize') {
      const { text } = await parseJsonBody(req);
      if (!text || !text.trim()) {
        return sendJson(res, 400, { error: 'Text is required for humanize' });
      }
      const rewritten = await llama.generate(PROMPT_HUMANIZE, text);
      return sendJson(res, 200, { result: rewritten, original: text });
    }

    if (req.method === 'POST' && pathname === '/correct-all') {
      const { text, mode } = await parseJsonBody(req);
      if (!text || !text.trim()) {
        return sendJson(res, 400, { error: 'Text is required' });
      }

      let grammarResult;
      try {
        grammarResult = await harper.check(text);
      } catch (hErr) {
        console.warn('[Server] Harper failed in correct-all, attempting LLM grammar fix:', hErr.message);
        try {
          const corrected = await llama.generate(PROMPT_GRAMMAR, text);
          grammarResult = {
            text,
            correctedText: corrected,
            lints: extractWordDiffs(text, corrected)
          };
        } catch (llmErr) {
          throw new Error('All grammar engines failed: ' + llmErr.message);
        }
      }

      let finalResult = grammarResult.correctedText;
      if (mode === 'paraphrase') {
        finalResult = await llama.generate(PROMPT_PARAPHRASE, grammarResult.correctedText);
      } else if (mode === 'humanize') {
        finalResult = await llama.generate(PROMPT_HUMANIZE, grammarResult.correctedText);
      }

      return sendJson(res, 200, {
        result: finalResult,
        grammarOnly: grammarResult.correctedText,
        lints: grammarResult.lints,
        original: text,
        mode: mode || 'grammar'
      });
    }

    sendJson(res, 404, { error: `Endpoint not found: ${pathname}` });
  } catch (err) {
    const statusCode = err.statusCode || 500;
    if (statusCode >= 500) {
      console.error(`[Server] Error processing ${req.method} ${pathname}:`, err);
    }
    sendJson(res, statusCode, { error: err.message || 'Internal Server Error' });
  }
});

let isShuttingDown = false;
function gracefulShutdown() {
  if (isShuttingDown) return;
  isShuttingDown = true;
  console.log('[Engine] Graceful shutdown initiated...');
  try {
    llama.unload();
  } catch (e) {}

  server.close(() => {
    console.log('[Engine] HTTP server closed.');
    process.exit(0);
  });
  setTimeout(() => process.exit(0), 1500);
}

process.on('SIGINT', gracefulShutdown);
process.on('SIGTERM', gracefulShutdown);
process.on('exit', () => {
  try {
    llama.unload();
  } catch (e) {}
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`[Engine] Words Service listening on http://127.0.0.1:${PORT}`);
});
