/*
 * Storyteller browser snippet.
 *
 * Loads inert. Nothing is recorded until the site calls storyteller.start().
 * Typed input is always masked. [data-no-record] subtrees are never captured.
 */
import { record } from "@rrweb/record";
import type { eventWithTime } from "@rrweb/types";

type Facts = Record<string, string | number | boolean>;

interface InitOptions {
  endpoint: string; // e.g. "https://example.com/storyteller"
  siteKey: string;
  flushIntervalMs?: number; // default 5000
  flushAtEvents?: number; // default 200
  idleTimeoutMinutes?: number; // default 10; must match service config
  maskAllText?: boolean; // default false
  maskTextSelector?: string; // extra selector for text masking
  debug?: boolean;
  // Dev mode: don't send anywhere; collect in memory. storyteller.dump() returns the recording.
  dumpOnly?: boolean;
}

interface State {
  opts: InitOptions | null;
  stopFn: (() => void) | null;
  buffer: eventWithTime[];
  dump: eventWithTime[];
  timer: number | null;
  visitorId: string;
  visitId: string;
  userId: string | null;
  recordingAllowed: { value: boolean; checkedAt: number } | null;
  seq: number;
}

const LS_VISITOR = "st_vid";
const LS_OPTOUT = "st_optout";
const SS_VISIT = "st_visit";
const RECORDING_CACHE_MS = 5 * 60 * 1000;

const state: State = {
  opts: null,
  stopFn: null,
  buffer: [],
  dump: [],
  timer: null,
  visitorId: "",
  visitId: "",
  userId: null,
  recordingAllowed: null,
  seq: 0,
};

function uuid(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

function log(...args: unknown[]) {
  if (state.opts?.debug) console.log("[storyteller]", ...args);
}

function optedOut(): boolean {
  try {
    if (localStorage.getItem(LS_OPTOUT) === "1") return true;
  } catch {}
  const nav = navigator as Navigator & { globalPrivacyControl?: boolean };
  return nav.globalPrivacyControl === true;
}

function getVisitorId(): string {
  try {
    let id = localStorage.getItem(LS_VISITOR);
    if (!id) {
      id = uuid();
      localStorage.setItem(LS_VISITOR, id);
    }
    return id;
  } catch {
    return uuid();
  }
}

function getVisitId(idleMs: number): string {
  try {
    const raw = sessionStorage.getItem(SS_VISIT);
    if (raw) {
      const { id, last } = JSON.parse(raw);
      if (Date.now() - last < idleMs) return id;
    }
  } catch {}
  return uuid();
}

function touchVisit() {
  try {
    sessionStorage.setItem(SS_VISIT, JSON.stringify({ id: state.visitId, last: Date.now() }));
  } catch {}
}

/* Custom events use rrweb's "custom" event type (5) so they ride along in the same stream. */
function custom(tag: string, payload: unknown) {
  const ev = { type: 5, data: { tag, payload }, timestamp: Date.now() } as unknown as eventWithTime;
  push(ev);
}

function push(ev: eventWithTime) {
  state.buffer.push(ev);
  if (state.opts?.dumpOnly) state.dump.push(ev);
  touchVisit();
  if (state.buffer.length >= (state.opts?.flushAtEvents ?? 200)) flush(false);
}

async function checkRecordingAllowed(): Promise<boolean> {
  const cached = state.recordingAllowed;
  if (cached && Date.now() - cached.checkedAt < RECORDING_CACHE_MS) return cached.value;
  if (state.opts?.dumpOnly) return true;
  try {
    const res = await fetch(`${state.opts!.endpoint}/recording`, { credentials: "omit" });
    const body = await res.json();
    const value = !!body.enabled;
    state.recordingAllowed = { value, checkedAt: Date.now() };
    return value;
  } catch (e) {
    log("recording check failed; staying off", e);
    return false;
  }
}

function flush(useBeacon: boolean) {
  if (!state.opts || state.buffer.length === 0) return;
  const events = state.buffer;
  state.buffer = [];
  if (state.opts.dumpOnly) return;
  const payload = JSON.stringify({
    siteKey: state.opts.siteKey,
    visitorId: state.visitorId,
    visitId: state.visitId,
    userId: state.userId,
    seq: state.seq++,
    events,
  });
  const url = `${state.opts.endpoint}/events`;
  try {
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: payload,
      keepalive: true,
      credentials: "omit",
    }).catch((e) => log("flush failed", e));
  } catch (e) {
    if (useBeacon && navigator.sendBeacon) navigator.sendBeacon(url, new Blob([payload], { type: "application/json" }));
  }
}

function patchHistory() {
  const emit = () => custom("url", { href: location.href, title: document.title });
  const wrap = (name: "pushState" | "replaceState") => {
    const orig = history[name];
    history[name] = function (this: History, ...args: unknown[]) {
      const r = (orig as Function).apply(this, args);
      emit();
      return r;
    } as typeof history.pushState;
  };
  wrap("pushState");
  wrap("replaceState");
  window.addEventListener("popstate", emit);
}

let patched = false;

export function init(opts: InitOptions) {
  state.opts = { flushIntervalMs: 5000, flushAtEvents: 200, idleTimeoutMinutes: 10, ...opts };
  state.visitorId = getVisitorId();
  state.visitId = getVisitId(state.opts.idleTimeoutMinutes! * 60 * 1000);
  log("init", { visitorId: state.visitorId, visitId: state.visitId });
}

export async function start(): Promise<boolean> {
  if (!state.opts) throw new Error("storyteller.init() first");
  if (state.stopFn) return true;
  if (optedOut()) {
    log("opted out; not recording");
    return false;
  }
  if (!(await checkRecordingAllowed())) {
    log("recording disabled by service");
    return false;
  }
  if (!patched) {
    patchHistory();
    patched = true;
  }
  const o = state.opts;
  state.stopFn =
    record({
      emit: (ev) => push(ev),
      maskAllInputs: true,
      maskTextSelector: o.maskAllText ? "*" : o.maskTextSelector,
      blockSelector: "[data-no-record]",
      sampling: { mousemove: 50, scroll: 150, input: "last" },
      checkoutEveryNms: 60_000,
      recordCanvas: false,
      collectFonts: false,
    }) ?? null;

  custom("visit_meta", {
    href: location.href,
    referrer: document.referrer,
    userAgent: navigator.userAgent,
    language: navigator.language,
    viewport: [window.innerWidth, window.innerHeight],
    userId: state.userId,
  });

  document.addEventListener("visibilitychange", () => custom("visibility", { state: document.visibilityState }));
  window.addEventListener("error", (e) => custom("js_error", { message: String(e.message).slice(0, 300) }));
  window.addEventListener("pagehide", () => {
    custom("pagehide", {});
    flush(true);
  });
  state.timer = window.setInterval(() => flush(false), o.flushIntervalMs);
  log("recording started");
  return true;
}

export function stop() {
  if (state.stopFn) {
    state.stopFn();
    state.stopFn = null;
  }
  if (state.timer) {
    clearInterval(state.timer);
    state.timer = null;
  }
  state.buffer = [];
  log("recording stopped");
}

/** Mark the visit as finished now (e.g. after logout). Flushes and ends the visit id. */
export function end() {
  custom("visit_end", {});
  flush(false);
  stop();
  try {
    sessionStorage.removeItem(SS_VISIT);
  } catch {}
}

export function identify(userId: string, facts?: Facts) {
  state.userId = userId;
  custom("identify", { userId, facts: facts ?? {} });
}

export function optOut() {
  try {
    localStorage.setItem(LS_OPTOUT, "1");
  } catch {}
  stop();
}

export function optIn() {
  try {
    localStorage.removeItem(LS_OPTOUT);
  } catch {}
}

/** Dev helper: returns everything recorded so far (dumpOnly mode) as a recording file. */
export function dump() {
  return {
    visitorId: state.visitorId,
    visitId: state.visitId,
    userId: state.userId,
    events: state.dump,
  };
}

export function ids() {
  return { visitorId: state.visitorId, visitId: state.visitId, userId: state.userId };
}

const api = { init, start, stop, end, identify, optOut, optIn, dump, ids };
declare global {
  interface Window {
    storyteller: typeof api;
  }
}
if (typeof window !== "undefined") window.storyteller = api;
export default api;
