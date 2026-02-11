/**
 * Console hook: intercepts console.log/warn/error/info/debug in Steam's frontend
 * and forwards entries to the Python backend via callPluginMethod.
 *
 * NOT installed automatically — only when console log streaming is enabled
 * by the Hub requesting it. Uses a local buffer + flush interval to avoid
 * flooding the IPC channel.
 */

import { call } from "@decky/api";

type LogLevel = "log" | "warn" | "error" | "info" | "debug";

interface StyledSegment {
  text: string;
  css?: string;
}

interface BufferedEntry {
  level: string;
  text: string;
  segments?: StyledSegment[];
}

const originalMethods: Partial<Record<LogLevel, (...args: unknown[]) => void>> = {};

let installed = false;
let sending = false; // re-entrancy guard
let flushTimer: ReturnType<typeof setInterval> | null = null;

const buffer: BufferedEntry[] = [];
const MAX_BUFFER = 100;
const FLUSH_INTERVAL_MS = 500;

/**
 * Parse console args that may contain %c format directives.
 * Returns plain text and optional styled segments.
 *
 * Example: console.log("%c Decky %c Router", "color: red", "color: blue")
 * -> { text: " Decky  Router", segments: [{text:" Decky ",css:"color: red"},{text:" Router",css:"color: blue"}] }
 */
function parseConsoleArgs(args: unknown[]): { text: string; segments?: StyledSegment[] } {
  if (args.length === 0) return { text: "" };

  const first = args[0];
  if (typeof first !== "string" || !first.includes("%c")) {
    // No %c formatting, produce plain text
    const text = args
      .map((arg) => {
        if (typeof arg === "string") return arg;
        try { return JSON.stringify(arg); } catch { return String(arg); }
      })
      .join(" ");
    return { text };
  }

  // Split by %c to get text parts, consume CSS args in order
  const parts = first.split("%c");
  const segments: StyledSegment[] = [];
  let cssArgIdx = 1; // CSS args start at index 1

  for (let i = 0; i < parts.length; i++) {
    const partText = parts[i];
    if (i === 0 && partText === "") continue; // leading empty before first %c
    if (i === 0) {
      // Text before the first %c — no CSS
      segments.push({ text: partText });
    } else {
      const css = cssArgIdx < args.length && typeof args[cssArgIdx] === "string"
        ? (args[cssArgIdx] as string)
        : "";
      cssArgIdx++;
      segments.push({ text: partText, css: css || undefined });
    }
  }

  // Append any remaining non-CSS args as plain text
  for (let i = cssArgIdx; i < args.length; i++) {
    const arg = args[i];
    const s = typeof arg === "string" ? arg : (() => { try { return JSON.stringify(arg); } catch { return String(arg); } })();
    if (s) segments.push({ text: " " + s });
  }

  const plainText = segments.map((s) => s.text).join("");
  return { text: plainText, segments };
}

/**
 * Install the console hook. Overrides console methods to forward to backend.
 * The original methods are preserved and still called.
 */
export function installConsoleHook(): void {
  if (installed) return;

  const levels: LogLevel[] = ["log", "warn", "error", "info", "debug"];

  for (const level of levels) {
    originalMethods[level] = console[level].bind(console);
    console[level] = (...args: unknown[]) => {
      // Always call the original method first
      originalMethods[level]!(...args);

      // Skip if we're inside a send call (prevent infinite recursion)
      if (sending) return;

      const parsed = parseConsoleArgs(args);
      if (!parsed.text) return;

      // Buffer locally instead of sending immediately
      if (buffer.length >= MAX_BUFFER) {
        buffer.shift();
      }
      buffer.push({ level, text: parsed.text, segments: parsed.segments });
    };
  }

  // Start flush timer
  flushTimer = setInterval(flushBuffer, FLUSH_INTERVAL_MS);

  installed = true;
}

/**
 * Remove the console hook and restore original methods.
 */
export function removeConsoleHook(): void {
  if (!installed) return;

  if (flushTimer !== null) {
    clearInterval(flushTimer);
    flushTimer = null;
  }

  for (const [level, original] of Object.entries(originalMethods)) {
    if (original) {
      (console as unknown as Record<string, unknown>)[level] = original;
    }
  }

  buffer.length = 0;
  installed = false;
}

/**
 * Flush buffered entries to Python backend in a single batch.
 */
function flushBuffer(): void {
  if (buffer.length === 0 || sending) return;

  // Take all entries and clear buffer
  const batch = buffer.splice(0, buffer.length);

  sending = true;
  const promises = batch.map((entry) =>
    call<[string, string, string, number, string], void>(
      "add_console_log",
      entry.level,
      entry.text,
      "",
      0,
      entry.segments ? JSON.stringify(entry.segments) : ""
    ).catch(() => {
      // Silently ignore to avoid loops
    })
  );

  Promise.all(promises).finally(() => {
    sending = false;
  });
}
