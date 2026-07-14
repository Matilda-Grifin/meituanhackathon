import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  GatewayBrowserClient,
  GatewayRequestError,
  type GatewayEventFrame,
  type GatewayHelloOk,
} from "openclaw-ws";
import "./App.css";
import { LocationConsentModal } from "./LocationConsent";
import {
  reconcileChatRows,
  lastUserTextInRows,
  getChatEventState,
  rowsStableSignature,
  type ChatRow,
} from "./chatHistoryMerge";
import {
  extractUserVisibleTextFromMessage,
  hasStoredLocationConsent,
  isLocationContextMessage,
  isLocationContextOnlyMessage,
  loadStoredLocationSnapshot,
  locationSnapshotKey,
  mergeLocationPrefix,
  resolveUserLocationTimed,
  shouldInjectLocationPrefix,
  storeLocationConsent,
  storeLocationSnapshot,
  type ResolvedLocation,
} from "./location";
import {
  cancelItineraryImageJob,
  formatItineraryImageMarkdown,
  findLongestPlanText,
  hasVisibleUserAfterRowIndex,
  isCompleteItineraryPlan,
  planTextFingerprint,
  requestItineraryImage,
  rowsHasItineraryImage,
  shouldAllowItineraryImageForRows,
  toolEventUsedSearchPlaces,
} from "./itineraryImage";
import {
  appendPersistedItineraryImage,
  clearPersistedItineraryImage,
  persistItineraryImageRow,
  sessionHasPersistedItineraryImage,
} from "./itineraryImageStorage";
import { notifyHarnessUserMessage, requestHarnessRepair } from "./harnessClient";
import { BubbleMarkdown } from "./BubbleMarkdown";
import { MarkdownErrorBoundary } from "./MarkdownErrorBoundary";
import { StreamingPlainText } from "./StreamingPlainText";
import { StreamingMarkdown } from "./StreamingMarkdown";
import { shouldStreamMarkdown } from "./streamMarkdown";
import {
  isWarmupMessage,
  type WarmupState,
} from "./sessionWarmup";
import { IntakeCard } from "./IntakeCard";
import {
  extractIntakeOnlyText,
  mergeIntakeBlocks,
  parseIntakeSurvey,
  parseQuestionBlocks,
  hasIntakeQuestions,
  type IntakeBlock,
} from "./intakeParse";
import {
  isEmptyAssistantPlaceholder,
  stripLeadingAssistantPlaceholders,
} from "./assistantPlaceholders";
import {
  extractRunId,
  extractPinnedSkipIntakeEntryAck,
  isAckMessage,
  isIntakeQuestionText,
  isPlanMessage,
  isSkipIntakeEntryAck,
  liveStreamDisplayText,
  indexOfFirstVisibleUser,
  isVisibleUserRow,
  presentChatRows,
  shouldEarlyFlushAck,
} from "./presentChatRows";
import {
  appendProcessStep,
  appendToolProgressStep,
  appendToolStepsFromPayload,
  filterIntakePhaseToolSteps,
  historyDataUsedSearchPlaces,
  labelForTool,
  type ProcessStep,
} from "./toolProgress";
import { mapFriendlyProgress } from "./friendlyProgress";
import { useSessionPois } from "./hooks/useSessionPois";
import { ThinkingBubble } from "./components/ThinkingBubble";
import { HistoryDrawer } from "./components/HistoryDrawer";
import { MobileHeader } from "./components/MobileHeader";
import { PlanMessageBody } from "./components/PlanMessageBody";
import { RouteMapPreview } from "./components/RouteMap";
import { FollowUpChips } from "./components/FollowUpChips";
import { MobileNotice } from "./components/MobileNotice";

async function waitUntil(
  timeoutMs: number,
  fn: () => boolean,
  stepMs = 150,
): Promise<boolean> {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    if (fn()) return true;
    await new Promise((r) => window.setTimeout(r, stepMs));
  }
  return fn();
}

/** HTTP 非安全上下文中 `crypto.randomUUID()` 会抛错，否则点击 Send 会在 try 之前静默失败 */
function newIdempotencyKey(): string {
  try {
    const c = globalThis.crypto;
    if (c && typeof c.randomUUID === "function") return c.randomUUID();
  } catch {
    // SecurityError 等
  }
  return `k-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 14)}`;
}

function normalizeWsUrl(raw: string): string {
  const t = raw.trim();
  if (!t) return "";
  if (t.startsWith("http://")) return "ws://" + t.slice("http://".length);
  if (t.startsWith("https://")) return "wss://" + t.slice("https://".length);
  return t;
}

/** 安全上下文（HTTPS 或非 localhost 的加密源）下浏览器会拦截 ws://，WebSocket 往往直接异常关闭 (1006)。 */
function insecureWsFromSecurePage(wsUrlRaw: string): boolean {
  if (typeof window === "undefined" || !window.isSecureContext) return false;
  const u = normalizeWsUrl(wsUrlRaw).toLowerCase();
  return u.startsWith("ws://");
}

function messageBodyText(m: Record<string, unknown>): string {
  const c = m.content;
  if (typeof c === "string") return c;
  if (Array.isArray(c)) {
    return c
      .map((block) => {
        if (!block || typeof block !== "object") return "";
        const b = block as Record<string, unknown>;
        const typ = typeof b.type === "string" ? b.type : "";
        if (
          typ === "tool_result" ||
          typ === "tool_use" ||
          typ === "function_call" ||
          typ === "function_call_output"
        ) {
          const inner =
            (typeof b.text === "string" && b.text) ||
            (typeof b.content === "string" && b.content) ||
            (typeof b.output === "string" && b.output) ||
            "";
          if (inner.trim().startsWith("{") || inner.includes('"tool"')) {
            return formatToolTranscriptText(/^toolresult/i.test(inner.trim()) ? inner : `toolResult\n${inner}`);
          }
          return formatToolTranscriptText(`toolResult\n${JSON.stringify(b)}`);
        }
        return typeof b.text === "string" ? b.text : "";
      })
      .filter(Boolean)
      .join("\n\n");
  }
  if (c && typeof c === "object") {
    const o = c as Record<string, unknown>;
    if (typeof o.text === "string") return o.text;
  }
  return "";
}

/** 去掉 assistant 里误插入的 toolResult JSON、裸 toolresult 行、Tool xxx not found 等 */
function stripAssistantToolNoise(text: string): string {
  let s = text.replace(/\n+toolresult\s*\{[\s\S]*?\}\s*/gi, "\n");
  s = s.replace(/^\s*toolresult\s*\{[\s\S]*?\}\s*/gim, "\n");
  s = s.replace(/^\s*toolresult\s*$/gim, "");
  s = s.replace(/^\s*Tool\s+[\w_]+\s+not\s+found\.?\s*$/gim, "");
  s = s.replace(/\n*\{[\s\S]*?"city_display"[\s\S]*?"forecast_days"[\s\S]*?\}\s*/gi, "\n");
  return s.replace(/\n{3,}/g, "\n\n").trimEnd();
}

/** 对话区不展示 tool / toolresult 原始 JSON（进展见底部任务框） */
function isRawToolPayloadText(text: string): boolean {
  const t = text.trim();
  if (!t) return true;
  if (/^\s*toolresult\b/i.test(t)) return true;
  if (t.startsWith("{") && /"forecast_days"|"weather_code"|"city_display"|lifecare__/i.test(t)) {
    return true;
  }
  if (/^【.+】/.test(t) && /已完成|调用失败|工具不可用/.test(t)) return true;
  const stripped = stripAssistantToolNoise(t);
  return stripped.length < 12 && t.length > 48;
}

function isHiddenChatRow(role: string, text: string): boolean {
  const rl = String(role).toLowerCase();
  if (rl === "user" && isLocationContextOnlyMessage(text)) return true;
  if (rl === "user" && isWarmupMessage(text)) return true;
  if (rl === "user" && isIntakeDisplayHiddenUserRow(text)) return true;
  if (rl === "tool" || rl === "toolresult") return true;
  if (isRawToolPayloadText(text)) return true;
  if (rl === "assistant" && isNoiseAssistantBubble(stripAssistantToolNoise(text))) return true;
  if (rl === "assistant" && isLocationBootstrapGreeting(text)) return true;
  if (rl === "assistant" && isSkipIntakeEntryAck(text)) return false;
  if (rl === "assistant" && isAckMessage(text) && !isPlanMessage(text)) return true;
  return false;
}

/** 把网关 tool / toolResult 行收成人类可读短卡片（不展示整段 JSON） */
function formatToolTranscriptText(raw: string): string {
  const t = raw.trim();
  if (!t) return "";
  if (/^tool\s+/i.test(t) && /not\s+found/i.test(t)) {
    return `【工具不可用】\n${t.replace(/\s+/g, " ").slice(0, 360)}`;
  }
  if (/^toolresult\s*$/i.test(t)) return "【工具返回】（空）";
  const m = t.match(/^toolresult\s*(\{[\s\S]*)$/i);
  let jsonStr = t;
  if (m) jsonStr = m[1]!;
  else if (t.startsWith("{")) jsonStr = t;
  try {
    const j = JSON.parse(jsonStr) as Record<string, unknown>;
    const tool = String(j.tool ?? j.name ?? "工具");
    const status = String(j.status ?? "");
    const err = typeof j.error === "string" ? j.error : "";
    const dur = typeof j.durationMs === "number" ? ` · ${j.durationMs}ms` : "";
    if (status === "error" || err) {
      const one = err.replace(/\s+/g, " ").slice(0, 320);
      return `【${tool}】调用失败${dur}\n${one}`;
    }
    return `【${tool}】已完成${dur || " · 已返回"}`;
  } catch {
    return t.length > 480 ? `${t.slice(0, 480)}…` : t;
  }
}

/** 从 WebSocket 事件 payload 中提取工具名（用于时序记录） */
function extractToolName(payload: unknown): string | null {
  if (!payload || typeof payload !== "object") return null;
  const p = payload as Record<string, unknown>;
  const name = p.tool || p.toolName || p.name || p.tool_name;
  if (typeof name === "string" && name.trim()) return name.trim();
  const fn = p.function as Record<string, unknown> | undefined;
  if (fn && typeof fn.name === "string" && fn.name.trim()) return fn.name.trim();
  const text = typeof p.text === "string" ? p.text : "";
  const mcpMatch = text.match(/lifecare_(\w+)/);
  if (mcpMatch) return `lifecare_${mcpMatch[1]}`;
  return null;
}

/** 后台 chat.history 等进展，不在「任务进展 · 工具调用」展示 — 见 toolProgress.isHiddenProcessStepMsg */

function appendToolTimeline(
  prev: ProcessStep[],
  evt: GatewayEventFrame,
  seenTools: Set<string>,
): ProcessStep[] {
  const ev = evt.event;
  if (ev === "tick" || ev === "presence" || ev === "health") return prev;
  const next = appendToolStepsFromPayload(prev, evt.payload, seenTools);
  if (next.length > prev.length) return next;
  let msg = extractProcessHintFromPayload(evt.payload, ev);
  if (!msg) {
    const raw = JSON.stringify(evt.payload ?? "");
    if (/exec|bash|process/i.test(ev + raw)) {
      msg = "命令行 / exec 步骤";
    } else if (/session\.tool|tool\.|invoke/i.test(ev)) {
      msg = `工具事件：${ev}`;
    }
  }
  if (!msg) return prev;
  return appendToolProgressStep(prev, msg, seenTools);
}

function shouldSkipHistoryMessage(m: Record<string, unknown>, text: string, role: string): boolean {
  if (m.display === false) return true;
  const customType = typeof m.customType === "string" ? m.customType : "";
  if (customType.includes("runtime-context") || customType === "openclaw.runtime-context") return true;
  const rlow = String(role).toLowerCase();
  if (rlow === "user" && isLocationContextOnlyMessage(text)) return true;
  if (rlow === "user" && isWarmupMessage(text)) return true;
  if (/Sender \(untrusted metadata\)/i.test(text) && /webchat-ui/i.test(text)) return true;
  if (rlow === "user" && /^Conversation info \(untrusted metadata\)/i.test(text)) return true;
  return false;
}

function extractHistoryRows(data: unknown): { sessionKey?: string; rows: ChatRow[] } {
  if (!data || typeof data !== "object") return { rows: [] };
  const root = data as Record<string, unknown>;
  const sessionKey =
    typeof root.sessionKey === "string"
      ? root.sessionKey
      : typeof root.sessionId === "string"
        ? root.sessionId
        : undefined;
  const rawList =
    (Array.isArray(root.messages) && root.messages) ||
    (Array.isArray(root.entries) && root.entries) ||
    (Array.isArray(root.history) && root.history) ||
    (Array.isArray(root.items) && root.items) ||
    [];

  const rows: ChatRow[] = [];
  let i = 0;
  for (const raw of rawList) {
    if (!raw || typeof raw !== "object") continue;
    const wrap = raw as Record<string, unknown>;
    const m =
      wrap.message && typeof wrap.message === "object" && typeof (wrap.message as Record<string, unknown>).role === "string"
        ? (wrap.message as Record<string, unknown>)
        : wrap;
    const role =
      (typeof m.role === "string" && m.role) ||
      (typeof m.kind === "string" && m.kind) ||
      (typeof m.type === "string" && m.type) ||
      "unknown";
    const body = messageBodyText(m);
    let text =
      body ||
      (typeof m.text === "string" && m.text) ||
      (typeof m.body === "string" && m.body) ||
      (m.message && typeof m.message === "object"
        ? String((m.message as Record<string, unknown>).content ?? "")
        : "");
    if (!text.trim()) {
      const r = String(role).toLowerCase();
      if (r === "assistant") continue;
      text = JSON.stringify(m).slice(0, 800);
    } else if (typeof m.errorMessage === "string" && m.errorMessage.trim()) {
      text = `${text}\n\n——\n⚠ ${m.errorMessage}`;
    }
    const rlow = String(role).toLowerCase();
    if (shouldSkipHistoryMessage(m, text, role)) continue;
    if (rlow === "tool" || rlow === "toolresult") continue;
    const looksToolTranscript =
      /^\s*toolresult\b/i.test(text) ||
      (/^tool\s+/i.test(text.trim()) && /not\s+found/i.test(text));
    if (looksToolTranscript) continue;
    if (rlow === "assistant") {
      if (isEmptyAssistantPlaceholder(text)) continue;
      text = stripLeadingAssistantPlaceholders(stripAssistantToolNoise(text));
      if (isEmptyAssistantPlaceholder(text)) continue;
      if (isRawToolPayloadText(text)) continue;
      if (isLocationBootstrapGreeting(text)) continue;
    }
    rows.push({ role, text, id: `h-${i++}` });
  }
  return { sessionKey, rows };
}

function contentBlocksToText(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  const parts: string[] = [];
  for (const block of content) {
    if (!block || typeof block !== "object") continue;
    const b = block as Record<string, unknown>;
    const t = typeof b.text === "string" ? b.text : "";
    const typ = typeof b.type === "string" ? b.type : "";
    if (t && (typ === "text" || typ === "" || typ === "output_text")) parts.push(t);
  }
  return parts.join("");
}

function extractTextFromChatEvent(payload: unknown): string | null {
  if (payload == null) return null;
  if (typeof payload === "string") return payload;
  if (typeof payload !== "object") return String(payload);
  const p = payload as Record<string, unknown>;
  const direct =
    (typeof p.text === "string" && p.text) ||
    (typeof p.delta === "string" && p.delta) ||
    (typeof p.chunk === "string" && p.chunk);
  if (direct) return direct;
  const delta = p.delta;
  if (delta && typeof delta === "object") {
    const d = delta as Record<string, unknown>;
    if (typeof d.text === "string") return d.text;
    const dc = d.content;
    const fromDelta = contentBlocksToText(dc);
    if (fromDelta) return fromDelta;
  }
  const msg = p.message;
  if (msg && typeof msg === "object") {
    const m = msg as Record<string, unknown>;
    const c = m.content;
    if (typeof c === "string") return c;
    const fromBlocks = contentBlocksToText(c);
    if (fromBlocks) return fromBlocks;
  }
  return null;
}

/**
 * 合并流式正文：网关常发「累积全文」（piece 以当前 prev 为前缀），若一律 += 会叠成「你好你好…」。
 * 真增量（piece 不以 prev 开头）则按最大重叠边界拼接。
 */
function mergeStreamText(prev: string, piece: string): string {
  const p = piece;
  if (!p) return prev;
  if (!prev) return p;
  if (p.startsWith(prev)) return p;
  if (prev.startsWith(p)) return prev;
  const max = Math.min(prev.length, p.length, 16_384);
  for (let k = max; k > 0; k--) {
    if (prev.slice(-k) === p.slice(0, k)) return prev + p.slice(k);
  }
  return prev + p;
}

/** 位置预注入 / 连接后抢先问候、旧会话 follow-up，不应出现在补槽白面板前 */
function isLocationBootstrapGreeting(text: string): boolean {
  const t = text.trim();
  if (!t || t.length > 520) return false;
  if (isPlanMessage(t) || isIntakeQuestionText(t)) return false;
  if (/刚才已经为你规划好了/.test(t)) return true;
  if (/^你好[呀啊！!]?/.test(t) && /出行管家|本地生活|规划管家/.test(t)) return true;
  if (/^你好！我是你的/.test(t) && /管家|规划/.test(t)) return true;
  if (/很高兴为你服务/.test(t) && /周边逛逛|去其他城市|聊聊天/.test(t)) return true;
  if (/我是你的「本地生活出行管家」/.test(t)) return true;
  if (/如果有出行计划，随时告诉我/.test(t)) return true;
  return false;
}

function hasPlanAfterAnchor(rows: ChatRow[], anchorIdx: number): boolean {
  for (let i = rows.length - 1; i > anchorIdx; i--) {
    const r = rows[i]!;
    if (String(r.role).toLowerCase() === "assistant" && isPlanMessage(r.text)) return true;
  }
  return false;
}

function extractSessionKeyFromPayload(payload: unknown): string | null {
  if (!payload || typeof payload !== "object") return null;
  const scan = (obj: Record<string, unknown>): string | null => {
    for (const key of ["sessionKey", "sessionId", "key", "canonicalKey"]) {
      const v = obj[key];
      if (typeof v === "string" && v.trim()) return v.trim();
    }
    return null;
  };
  const p = payload as Record<string, unknown>;
  const direct = scan(p);
  if (direct) return direct;
  if (p.data && typeof p.data === "object") {
    const nested = scan(p.data as Record<string, unknown>);
    if (nested) return nested;
  }
  if (p.message && typeof p.message === "object") {
    const nested = scan(p.message as Record<string, unknown>);
    if (nested) return nested;
  }
  return null;
}

function eventMatchesActiveSession(payload: unknown, activeSk: string): boolean {
  if (!activeSk) return true;
  const evtSk = extractSessionKeyFromPayload(payload);
  if (!evtSk) return true;
  return evtSk === activeSk;
}

function isNoiseAssistantBubble(text: string): boolean {
  if (isEmptyAssistantPlaceholder(text)) return true;
  const t = text.trim();
  if (!t) return true;
  if (isLocationBootstrapGreeting(t)) return true;
  if (/^（无正文\s*·\s*stop:\s*toolUse）$/i.test(t)) return true;
  if (/^assistant\s*$/i.test(t)) return true;
  return false;
}

function isIntakeQuestionBubble(text: string): boolean {
  const intakeOnly = extractIntakeOnlyText(text);
  return hasIntakeQuestions(intakeOnly);
}

type IntakeSubmittedSnapshot = {
  blocks: IntakeBlock[];
  selections: Record<number, string>;
  custom: Record<number, string>;
  followUp: Record<number, string>;
};

/** 当前轮次：最后一条可见、非「选择题答案」的用户消息 */
function findCurrentTurnAnchorIdx(rows: ChatRow[]): number {
  for (let i = rows.length - 1; i >= 0; i--) {
    const r = rows[i]!;
    if (!isVisibleUserRow(r)) continue;
    if (isIntakeSubmissionText(r.text)) continue;
    return i;
  }
  return -1;
}

/** 问卷卡片锚点：本趟规划的首条可见用户消息（Agent 选择题回复此句） */
function findIntakeCardAnchorUserId(rows: ChatRow[]): string | null {
  let startIdx = 0;
  for (let i = rows.length - 1; i >= 0; i--) {
    const r = rows[i]!;
    if (String(r.role).toLowerCase() === "assistant" && isPlanMessage(r.text)) {
      startIdx = i + 1;
      break;
    }
  }
  for (let i = startIdx; i < rows.length; i++) {
    const r = rows[i]!;
    if (!isVisibleUserRow(r)) continue;
    if (isIntakeSubmissionText(r.text)) continue;
    return r.id;
  }
  return null;
}

/** 仅在本轮 anchor 之后、下一条新用户消息之前查找槽位提交 */
function findIntakeSubmissionInTurn(
  rows: ChatRow[],
  anchorIdx: number,
): { submissionIdx: number; assistantIdx: number } | null {
  let nextTurnUserIdx = rows.length;
  for (let i = anchorIdx + 1; i < rows.length; i++) {
    const r = rows[i]!;
    if (!isVisibleUserRow(r)) continue;
    if (!isIntakeSubmissionText(r.text)) {
      nextTurnUserIdx = i;
      break;
    }
  }
  for (let i = anchorIdx + 1; i < nextTurnUserIdx; i++) {
    const r = rows[i]!;
    if (String(r.role).toLowerCase() !== "user" || !isIntakeSubmissionText(r.text)) continue;
    for (let j = i - 1; j > anchorIdx; j--) {
      const a = rows[j]!;
      if (String(a.role).toLowerCase() !== "assistant") continue;
      if (parseQuestionBlocks(extractIntakeOnlyText(a.text)).length > 0) {
        return { submissionIdx: i, assistantIdx: j };
      }
    }
    if (/^全部用默认/.test(r.text.trim())) {
      return { submissionIdx: i, assistantIdx: -1 };
    }
  }
  return null;
}

function buildTurnSubmittedIntake(rows: ChatRow[], anchorIdx: number): IntakeSubmittedSnapshot | null {
  const hit = findIntakeSubmissionInTurn(rows, anchorIdx);
  if (!hit) return null;
  const u = rows[hit.submissionIdx]!;
  if (/^全部用默认/.test(u.text.trim())) {
    return null;
  }
  if (hit.assistantIdx < 0) return null;
  const a = rows[hit.assistantIdx]!;
  const blocks = parseQuestionBlocks(extractIntakeOnlyText(a.text));
  if (!blocks.length) return null;
  const { selections, custom, followUp } = parseIntakeSubmissionSelections(u.text);
  return { blocks, selections, custom, followUp };
}

/** 口语跳过：首条 user → intake assistant → 第二条可见 user（非选择题答案） */
function buildFreetextSkippedIntake(rows: ChatRow[], anchorIdx: number): IntakeSubmittedSnapshot | null {
  let intakeAssistantIdx = -1;
  for (let i = anchorIdx + 1; i < rows.length; i++) {
    const r = rows[i]!;
    if (isVisibleUserRow(r) && !isIntakeSubmissionText(r.text)) {
      if (intakeAssistantIdx < 0) return null;
      const blocks = parseQuestionBlocks(extractIntakeOnlyText(rows[intakeAssistantIdx]!.text));
      if (!blocks.length) return null;
      return { blocks, selections: {}, custom: {}, followUp: {} };
    }
    if (String(r.role).toLowerCase() === "assistant") {
      const intakeOnly = extractIntakeOnlyText(stripLeadingAssistantPlaceholders(r.text));
      if (parseQuestionBlocks(intakeOnly).length > 0) {
        intakeAssistantIdx = i;
      }
    }
  }
  return null;
}

function buildTurnIntakeSnapshot(rows: ChatRow[], anchorIdx: number): IntakeSubmittedSnapshot | null {
  return buildTurnSubmittedIntake(rows, anchorIdx) ?? buildFreetextSkippedIntake(rows, anchorIdx);
}

function isIntakeSubmissionText(text: string): boolean {
  return /^选择题答案：/.test(text.trim()) || /^全部用默认/.test(text.trim());
}

/** B 阶段及追问轮：不在对话区 early flush ack（进展条已承载），避免闪一下后消失 */
function shouldSkipEarlyFlushAckForPlanPhase(
  rows: ChatRow[],
  pendingUser: string | null,
  opts: {
    toolStarted: boolean;
    hadSearch: boolean;
    historyHadSearch: boolean;
    intakeViaFreetext?: boolean;
  },
): boolean {
  if (opts.toolStarted || opts.hadSearch || opts.historyHadSearch) return true;
  if (opts.intakeViaFreetext) return true;
  if (pendingUser && isIntakeSubmissionText(pendingUser)) return true;
  return rows.some(
    (r) => String(r.role).toLowerCase() === "user" && isIntakeSubmissionText(r.text),
  );
}

/** 槽位提交/API 载荷用户行：不在对话区单独展示（保留在 intake 卡片内） */
function isIntakeDisplayHiddenUserRow(text: string): boolean {
  const t = text.trim();
  return isIntakeSubmissionText(t) || /^已选：/.test(t);
}

function findSessionPlanningIntake(
  rows: ChatRow[],
): { anchorId: string; snapshot: IntakeSubmittedSnapshot } | null {
  let found: { anchorId: string; snapshot: IntakeSubmittedSnapshot } | null = null;
  for (let i = 0; i < rows.length; i++) {
    const r = rows[i]!;
    if (!isVisibleUserRow(r) || isIntakeSubmissionText(r.text)) continue;
    const snap = buildTurnIntakeSnapshot(rows, i);
    if (snap) found = { anchorId: r.id, snapshot: snap };
  }
  return found;
}

function sessionHasDeliveredPlan(rows: ChatRow[]): boolean {
  return rows.some(
    (r) => String(r.role).toLowerCase() === "assistant" && isPlanMessage(r.text),
  );
}

function hasPlanBeforeAnchor(rows: ChatRow[], anchorIdx: number): boolean {
  for (let i = 0; i < anchorIdx; i++) {
    const r = rows[i]!;
    if (String(r.role).toLowerCase() === "assistant" && isPlanMessage(r.text)) return true;
  }
  return false;
}

function intakeBlocksFingerprint(blocks: IntakeBlock[]): string {
  return blocks.map((b) => `${b.n}:${b.title}`).join("|");
}

function findLatestIntakeTextAfterAnchor(
  rows: ChatRow[],
  anchorIdx: number,
  streaming: string,
): string {
  const live = streaming.trim();
  if (live) {
    const liveIntake = extractIntakeOnlyText(live);
    if (parseQuestionBlocks(liveIntake).length > 0) return liveIntake;
  }
  for (let i = rows.length - 1; i > anchorIdx; i--) {
    const r = rows[i]!;
    if (String(r.role).toLowerCase() !== "assistant") continue;
    const intakeOnly = extractIntakeOnlyText(r.text);
    if (parseQuestionBlocks(intakeOnly).length > 0) return intakeOnly;
    break;
  }
  return "";
}

function extractAgentStreamHint(payload: unknown): string | null {
  if (!payload || typeof payload !== "object") return null;
  const p = payload as Record<string, unknown>;
  const stream = typeof p.stream === "string" ? p.stream : "";
  const data = p.data && typeof p.data === "object" ? (p.data as Record<string, unknown>) : null;
  if (stream === "assistant") return null;
  if (stream === "lifecycle" && data) {
    const phase = String(data.phase ?? "");
    if (phase === "start") return "开始执行本轮任务";
    if (phase === "end") return null;
  }
  if (stream === "item" && data) {
    const name =
      (typeof data.tool === "string" && data.tool) ||
      (typeof data.name === "string" && data.name) ||
      (typeof data.toolName === "string" && data.toolName);
    if (name) return labelForTool(name);
    return null;
  }
  if ((stream === "tool" || stream === "tool_use" || stream === "tool-call") && data) {
    const name =
      (typeof data.tool === "string" && data.tool) ||
      (typeof data.name === "string" && data.name) ||
      (typeof data.toolName === "string" && data.toolName);
    if (name) return labelForTool(name);
  }
  const raw = JSON.stringify(data ?? p);
  if (/lifecare__/i.test(raw)) {
    const m = raw.match(/lifecare__[a-z0-9_]+/gi);
    if (m?.length) return `本地生活工具：${[...new Set(m.map((x) => x.toLowerCase()))].join("、")}`;
  }
  return null;
}

function extractProcessHintFromPayload(payload: unknown, eventName: string): string | null {
  if (eventName === "agent") return extractAgentStreamHint(payload);
  const raw = JSON.stringify(payload ?? "");
  if (!raw || raw === "{}") return null;
  if (/加载历史会话信息|加载该会话历史/i.test(raw)) return null;
  const lc = raw.toLowerCase();
  const lifecare = raw.match(/lifecare__[a-z0-9_]+/gi);
  if (lifecare?.length) {
    const uniq = [...new Set(lifecare.map((x) => x.toLowerCase()))];
    return `本地生活工具：${uniq.join("、")}`;
  }
  if (/web_search|searxng/i.test(raw)) {
    return "联网搜索（web_search）";
  }
  if (/get_weather|weather|天气/i.test(raw)) {
    return "查询天气";
  }
  if (/search_poi|poi|搜点/i.test(raw)) {
    return "搜索 POI / 地点";
  }
  if (/route|路线|导航/i.test(raw)) {
    return "规划路线";
  }
  if (/not\s+found/i.test(raw) && /lifecare/i.test(raw)) {
    return "lifecare 工具未挂载（需检查网关 MCP 配置）";
  }
  if (/toolresult|"status"\s*:\s*"error"/i.test(raw)) {
    return "工具返回结果";
  }
  if (/tool_use|function_call|"type"\s*:\s*"tool"/i.test(raw)) {
    return "模型发起工具调用";
  }
  if (/planning|plan_|补槽|intake|question/i.test(lc)) {
    return "Agent 规划 / 补槽";
  }
  if (/run\.start|run_start|"phase"\s*:\s*"start"/i.test(raw)) {
    return "开始执行本轮任务";
  }
  if (/run\.end|run_end|completed|finished/i.test(raw) && /run/i.test(eventName + raw)) {
    return null;
  }
  if (/thinking|reasoning|思考/i.test(raw)) {
    return "模型推理中…";
  }
  if (/exec|bash|shell/i.test(raw)) {
    return "执行命令 / 脚本";
  }
  if (/mcp/i.test(raw)) {
    return "MCP 工具链路";
  }
  return null;
}

function intakeAnswerComplete(
  blocks: IntakeBlock[],
  selections: Record<number, string>,
  custom: Record<number, string>,
  followUp: Record<number, string>,
): boolean {
  return blocks.every((b) => {
    const letter = selections[b.n];
    if (!letter) return false;
    const opt = b.options.find((o) => o.letter === letter);
    if (opt?.isOther) return Boolean((custom[b.n] ?? "").trim());
    if (opt?.followUp && !opt.followUp.optional) return Boolean((followUp[b.n] ?? "").trim());
    return true;
  });
}

function formatIntakeSubmission(
  blocks: IntakeBlock[],
  selections: Record<number, string>,
  custom: Record<number, string>,
  followUp: Record<number, string>,
): string {
  const parts = blocks
    .map((b) => {
      const letter = selections[b.n];
      if (!letter) return "";
      const opt = b.options.find((o) => o.letter === letter);
      const fu = (followUp[b.n] ?? "").trim();
      const extra = opt?.isOther ? (custom[b.n] ?? "").trim() : "";
      let line = `第${b.n}题选${letter}`;
      if (fu) line += `；子${b.n}：${fu}`;
      else if (extra) line += `：${extra}`;
      return line;
    })
    .filter(Boolean);
  return `选择题答案：${parts.join("；")}`;
}

function parseIntakeSubmissionSelections(text: string): {
  selections: Record<number, string>;
  custom: Record<number, string>;
  followUp: Record<number, string>;
} {
  const selections: Record<number, string> = {};
  const custom: Record<number, string> = {};
  const followUp: Record<number, string> = {};
  const body = text.trim().replace(/^选择题答案：/, "");
  for (const part of body.split(/[；;]/)) {
    const sub = part.trim().match(/^子(\d+)[：:](.+)$/i);
    if (sub) {
      followUp[parseInt(sub[1]!, 10)] = sub[2]!.trim();
      continue;
    }
    const m = part.trim().match(/^第(\d+)题选([A-F])(?:[：:](.+))?$/i);
    if (!m) continue;
    const n = parseInt(m[1]!, 10);
    selections[n] = m[2]!.toUpperCase();
    if (m[3]?.trim()) custom[n] = m[3].trim();
  }
  return { selections, custom, followUp };
}

/** 网关 chat 事件里可能出现的思考/推理增量（豆包等会走独立字段）。 */
function extractThinkingDelta(payload: unknown): string | null {
  if (payload == null || typeof payload !== "object") return null;
  const p = payload as Record<string, unknown>;
  const parts: string[] = [];
  const push = (s: unknown) => {
    if (typeof s === "string" && s.trim()) parts.push(s.trim());
  };
  push(p.thinking);
  const delta = p.delta;
  if (delta && typeof delta === "object") {
    const d = delta as Record<string, unknown>;
    push(d.thinking);
    push(d.reasoning);
  }
  const msg = p.message;
  if (msg && typeof msg === "object") {
    const c = (msg as Record<string, unknown>).content;
    if (Array.isArray(c)) {
      for (const block of c) {
        if (!block || typeof block !== "object") continue;
        const b = block as Record<string, unknown>;
        if (b.type === "thinking" && typeof b.thinking === "string") push(b.thinking);
      }
    }
  }
  if (!parts.length) return null;
  return parts.join("");
}

const THREADS_LS = "gw.chat.threads";
const ACTIVE_THREAD_LS = "gw.chat.activeThreadId";
const DEVICE_ID_LS = "gw.deviceId";
const TESTER_LABEL_LS = "gw.testerLabel";
/** 递增后下次打开会清空本机侧栏历史（仅 localStorage，不删服务器上其它 session） */
const STORAGE_SCHEMA_LS = "gw.storageSchema";
const STORAGE_SCHEMA_VERSION = 3;

function getOrCreateDeviceId(): string {
  try {
    let id = localStorage.getItem(DEVICE_ID_LS)?.trim();
    if (!id) {
      id = `dev-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
      localStorage.setItem(DEVICE_ID_LS, id);
    }
    return id;
  } catch {
    return "dev-anonymous";
  }
}

/** 评测者标识：URL ?tester=张三 写入 localStorage，eval 日志按此区分不同测试者 */
function resolveTesterLabel(): string | null {
  try {
    const fromUrl = new URLSearchParams(window.location.search).get("tester")?.trim();
    if (fromUrl) {
      localStorage.setItem(TESTER_LABEL_LS, fromUrl);
      return fromUrl;
    }
    return localStorage.getItem(TESTER_LABEL_LS)?.trim() || null;
  } catch {
    return null;
  }
}

function modelLabelForId(
  modelId: string | undefined,
  models: Array<{ id: string; label: string }>,
): string {
  if (!modelId) return "";
  return models.find((m) => m.id === modelId)?.label || modelId;
}

function migrateLocalChatStorage(): void {
  try {
    if (localStorage.getItem(STORAGE_SCHEMA_LS) === String(STORAGE_SCHEMA_VERSION)) return;
    localStorage.removeItem(THREADS_LS);
    localStorage.removeItem(ACTIVE_THREAD_LS);
    localStorage.removeItem("gw.session");
    localStorage.setItem(STORAGE_SCHEMA_LS, String(STORAGE_SCHEMA_VERSION));
  } catch {
    // ignore
  }
}

function clearLocalChatStorage(): void {
  localStorage.removeItem(THREADS_LS);
  localStorage.removeItem(ACTIVE_THREAD_LS);
  localStorage.removeItem("gw.session");
}

type ChatThread = {
  id: string;
  sessionKey: string;
  title: string;
  updatedAt: number;
  /** 新建会话时快照的全局 modelId */
  modelId?: string;
};

function loadThreads(): ChatThread[] {
  try {
    const raw = localStorage.getItem(THREADS_LS);
    if (!raw) return [];
    const arr = JSON.parse(raw) as unknown;
    if (!Array.isArray(arr)) return [];
    return arr
      .filter((x) => x && typeof x === "object")
      .map((x) => x as Record<string, unknown>)
      .filter((o) => typeof o.id === "string" && typeof o.sessionKey === "string")
      .map((o) => ({
        id: o.id as string,
        sessionKey: (o.sessionKey as string).trim(),
        title: typeof o.title === "string" ? o.title : "对话",
        updatedAt: typeof o.updatedAt === "number" ? o.updatedAt : Date.now(),
        modelId: typeof o.modelId === "string" ? o.modelId : undefined,
      }))
      .filter((t) => t.sessionKey.length > 0);
  } catch {
    return [];
  }
}

function saveThreads(threads: ChatThread[]) {
  localStorage.setItem(THREADS_LS, JSON.stringify(threads.slice(0, 80)));
}

function extractSessionKeyFromCreate(data: unknown): string | null {
  if (!data || typeof data !== "object") return null;
  const o = data as Record<string, unknown>;
  const inner = o.session && typeof o.session === "object" ? (o.session as Record<string, unknown>) : o;
  const k =
    (typeof inner.sessionKey === "string" && inner.sessionKey) ||
    (typeof inner.key === "string" && inner.key) ||
    (typeof o.sessionKey === "string" && o.sessionKey) ||
    (typeof o.key === "string" && o.key);
  return k && k.trim().length ? k.trim() : null;
}

function envStr(name: string): string {
  const v = (import.meta.env as Record<string, string | boolean | undefined>)[name];
  return typeof v === "string" ? v.trim() : "";
}

function hashToken(): string {
  const h = window.location.hash.trim();
  if (!h.startsWith("#token=")) return "";
  return decodeURIComponent(h.slice("#token=".length).replace(/^=/, ""));
}

/** 从 sessions.list（或同类）响应里猜默认会话 key */
function extractDefaultSessionKey(data: unknown): string | null {
  if (data == null) return null;
  if (typeof data === "string" && data.includes(":")) return data.trim();
  if (typeof data !== "object") return null;
  const o = data as Record<string, unknown>;
  const direct =
    (typeof o.defaultSessionKey === "string" && o.defaultSessionKey) ||
    (typeof o.sessionKey === "string" && o.sessionKey) ||
    (typeof o.activeSessionKey === "string" && o.activeSessionKey) ||
    (typeof o.dashboardSessionKey === "string" && o.dashboardSessionKey);
  if (direct) return direct;

  const defaults = o.defaults;
  if (defaults && typeof defaults === "object") {
    const d = defaults as Record<string, unknown>;
    const sk =
      (typeof d.sessionKey === "string" && d.sessionKey) ||
      (typeof d.mainSessionKey === "string" && d.mainSessionKey) ||
      (typeof d.activeKey === "string" && d.activeKey);
    if (typeof sk === "string" && sk.length > 0) return sk;
  }

  const arrays = [o.sessions, o.items, o.list, o.rows, o.entries];
  let best: { key: string; updatedAt: number } | null = null;
  for (const arr of arrays) {
    if (!Array.isArray(arr)) continue;
    for (const item of arr) {
      if (!item || typeof item !== "object") continue;
      const row = item as Record<string, unknown>;
      const k =
        (typeof row.sessionKey === "string" && row.sessionKey) ||
        (typeof row.key === "string" && row.key) ||
        (typeof row.id === "string" && row.id.startsWith("agent:") ? row.id : null);
      if (typeof k !== "string" || !k.length) continue;
      const updatedAt = typeof row.updatedAt === "number" ? row.updatedAt : 0;
      const kind = typeof row.kind === "string" ? row.kind : "";
      const score = updatedAt + (kind === "direct" ? 1e15 : kind === "group" ? 5e14 : 0);
      if (!best || score > best.updatedAt) best = { key: k, updatedAt: score };
    }
  }
  if (best) return best.key;

  const snap = o.snapshot;
  if (snap && typeof snap === "object") {
    const s = snap as Record<string, unknown>;
    const sk = s.sessionKey ?? s.mainSessionKey;
    if (typeof sk === "string") return sk;
  }
  return null;
}

const AGENT_SESSION_KEY_RE = /^agent:.+/;

function formatRpcError(e: unknown): string {
  if (e instanceof GatewayRequestError) {
    return `${e.gatewayCode}: ${e.message}`;
  }
  if (e instanceof Error) return e.message;
  return String(e);
}

/** 在 hello.snapshot 等嵌套 JSON 里找 `agent:x:y` 形式的 session key */
function deepFindAgentSessionKey(obj: unknown, depth = 0): string | null {
  if (depth > 14) return null;
  if (typeof obj === "string") {
    const t = obj.trim();
    if (AGENT_SESSION_KEY_RE.test(t)) return t;
    return null;
  }
  if (!obj || typeof obj !== "object") return null;
  if (Array.isArray(obj)) {
    for (const x of obj) {
      const f = deepFindAgentSessionKey(x, depth + 1);
      if (f) return f;
    }
    return null;
  }
  const record = obj as Record<string, unknown>;
  for (const k of ["sessionKey", "key", "mainSessionKey", "defaultSessionKey", "activeSessionKey", "canonicalKey"]) {
    const v = record[k];
    if (typeof v === "string" && (AGENT_SESSION_KEY_RE.test(v) || v === "global")) return v.trim();
  }
  for (const v of Object.values(record)) {
    const f = deepFindAgentSessionKey(v, depth + 1);
    if (f) return f;
  }
  return null;
}

function extractKeyFromResolvePayload(data: unknown): string | null {
  if (!data || typeof data !== "object") return null;
  const o = data as Record<string, unknown>;
  if (o.ok === true && typeof o.key === "string") return o.key;
  if (typeof o.key === "string" && (AGENT_SESSION_KEY_RE.test(o.key) || o.key === "global")) return o.key;
  return null;
}

/** 与网关 Control UI 一致的 dashboard 会话 key（webchat 下 sessions.create 常失败时仍可用） */
function newWebchatSessionKey(): string {
  let suffix: string;
  try {
    const c = globalThis.crypto;
    suffix =
      c && typeof c.randomUUID === "function"
        ? c.randomUUID().replace(/-/g, "")
        : `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 14)}`;
  } catch {
    suffix = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 14)}`;
  }
  return `agent:main:dashboard:${suffix.slice(0, 32)}`;
}

/**
 * 自动分配会话 key，不向用户弹窗。ECS 上 sessions.create 常失败，回退 resolve / 客户端生成 key。
 */
async function allocateWebchatSessionKey(
  client: GatewayBrowserClient,
  log: (s: string) => void,
  opts?: { label?: string; forkFrom?: string },
): Promise<string> {
  const label =
    opts?.label ??
    `webchat-${getOrCreateDeviceId().slice(0, 24)}-${new Date().toISOString().slice(0, 16)}`;

  try {
    const res = await client.request("sessions.create", { agentId: "main", label });
    const k = extractSessionKeyFromCreate(res);
    if (k) {
      log(`session: create → ${k.length > 52 ? `${k.slice(0, 48)}…` : k}`);
      return k;
    }
  } catch (e) {
    log(`session: create ${formatRpcError(e)}`);
  }

  const forkFrom = opts?.forkFrom?.trim();
  if (forkFrom) {
    try {
      const res2 = await client.request("sessions.fork", {
        key: forkFrom,
        label: `fork-${Date.now()}`,
      });
      const k = extractSessionKeyFromCreate(res2);
      if (k) {
        log(`session: fork → ${k.length > 52 ? `${k.slice(0, 48)}…` : k}`);
        return k;
      }
    } catch (e) {
      log(`session: fork ${formatRpcError(e)}`);
    }
  }

  for (let i = 0; i < 3; i++) {
    const key = newWebchatSessionKey();
    try {
      const r = await client.request("sessions.resolve", { key });
      const resolved = extractKeyFromResolvePayload(r) ?? key;
      try {
        await client.request("chat.history", { sessionKey: resolved, maxChars: 64 });
      } catch {
        // 新会话 history 为空或尚未物化属正常
      }
      log(`session: resolve → ${resolved.length > 52 ? `${resolved.slice(0, 48)}…` : resolved}`);
      return resolved;
    } catch (e) {
      log(`session: resolve ${formatRpcError(e)}`);
    }
  }

  const lazy = newWebchatSessionKey();
  log(`session: 客户端 sessionKey（首条消息时绑定）→ ${lazy.length > 52 ? `${lazy.slice(0, 48)}…` : lazy}`);
  return lazy;
}

/**
 * webchat 下 `sessions.list` 有时会因权限/策略失败；依次用 snapshot、list、resolve、chat.history 探测。
 */
async function pickSessionKeyAfterConnect(
  client: GatewayBrowserClient,
  hello: GatewayHelloOk | null,
  log: (s: string) => void,
  envDefaultKey?: string,
): Promise<string | null> {
  const probeKeys = [
    envDefaultKey?.trim(),
    envStr("VITE_DEFAULT_SESSION_KEY"),
    "agent:main:main",
    "global",
    "main",
  ].filter((k): k is string => Boolean(k && k.length > 0));
  const seen = new Set<string>();

  for (const pk of probeKeys) {
    if (seen.has(pk)) continue;
    seen.add(pk);
    try {
      await client.request("chat.history", { sessionKey: pk, maxChars: 4000 });
      log(`auto: chat.history probe ok (${pk.length > 48 ? `${pk.slice(0, 44)}…` : pk})`);
      return pk;
    } catch (e) {
      log(`auto: chat.history(${pk.length > 40 ? `${pk.slice(0, 36)}…` : pk}) ${formatRpcError(e)}`);
    }
  }

  if (hello?.snapshot != null) {
    const fromSnap = deepFindAgentSessionKey(hello.snapshot);
    if (fromSnap) {
      log(`auto: snapshot → ${fromSnap.length > 52 ? `${fromSnap.slice(0, 48)}…` : fromSnap}`);
      return fromSnap;
    }
  }

  try {
    const data = await client.request("sessions.list", { limit: 50 });
    const key = extractDefaultSessionKey(data);
    if (key) {
      log(`auto: sessions.list → ${key.length > 52 ? `${key.slice(0, 48)}…` : key}`);
      return key;
    }
    log(`auto: sessions.list ok but no key · keys=${Object.keys(data as object).join(",")}`);
  } catch (e) {
    log(`auto: sessions.list ${formatRpcError(e)}`);
  }

  for (const rk of ["main", "agent:main:main", "global"]) {
    try {
      const r = await client.request("sessions.resolve", { key: rk });
      const key = extractKeyFromResolvePayload(r);
      if (key) {
        log(`auto: sessions.resolve(${rk}) → ${key.length > 52 ? `${key.slice(0, 48)}…` : key}`);
        return key;
      }
    } catch (e) {
      log(`auto: sessions.resolve(${rk}) ${formatRpcError(e)}`);
    }
  }

  for (const pk of probeKeys) {
    if (seen.has(pk)) continue;
    seen.add(pk);
    try {
      await client.request("chat.history", { sessionKey: pk, maxChars: 4000 });
      log(`auto: chat.history retry ok (${pk.length > 48 ? `${pk.slice(0, 44)}…` : pk})`);
      return pk;
    } catch (e) {
      log(`auto: chat.history retry(${pk.length > 40 ? `${pk.slice(0, 36)}…` : pk}) ${formatRpcError(e)}`);
    }
  }

  return null;
}

/** App 壳：与页面同源 wss，走 8081 Nginx /ws/ 反代 */
function resolveGatewayUrlForShell(
  queryGateway: string | null | undefined,
  storedGateway: string | null | undefined,
  fromEnv: string,
): string {
  const q = queryGateway?.trim();
  if (q) return q;
  if (mobileShell && typeof window !== "undefined") {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}/ws/`;
  }
  return storedGateway?.trim() || fromEnv || "ws://127.0.0.1:18789";
}

/** 优先级：URL query > 上次会话 localStorage > Vite 默认（避免 env 固定 key 盖住侧栏里各条独立 session） */
function loadSettings() {
  const sp = new URLSearchParams(window.location.search);
  const fromEnvGateway = envStr("VITE_DEFAULT_GATEWAY_WS");
  const fromEnvToken = envStr("VITE_GATEWAY_TOKEN");
  const fromEnvSession = envStr("VITE_DEFAULT_SESSION_KEY");
  return {
    gatewayUrl: resolveGatewayUrlForShell(
      sp.get("gateway"),
      localStorage.getItem("gw.url"),
      fromEnvGateway,
    ),
    token:
      sp.get("token")?.trim() ||
      hashToken() ||
      localStorage.getItem("gw.token")?.trim() ||
      fromEnvToken ||
      "",
    sessionKey:
      sp.get("session")?.trim() ||
      localStorage.getItem("gw.session")?.trim() ||
      fromEnvSession ||
      "",
  };
}

const compactUi = import.meta.env.VITE_COMPACT_UI === "true";
const mobileShell = import.meta.env.VITE_APP_SHELL === "mobile";
const autoConnect = import.meta.env.VITE_AUTO_CONNECT === "true";
const showDebug = import.meta.env.VITE_SHOW_DEBUG === "true";

const TASK_ID_RE = /\b(T063_\d{3}|task_0\d{2})\b/i;

function parseTaskIdFromText(text: string): string | null {
  const m = text.match(TASK_ID_RE);
  if (!m) return null;
  const raw = m[1]!.toUpperCase();
  if (raw.startsWith("TASK_")) return `T063_${raw.slice(5)}`;
  return raw;
}

function stripEvalTaskTag(text: string): { text: string; taskId: string | null } {
  const taskId = parseTaskIdFromText(text);
  if (!taskId) return { text, taskId: null };
  const cleaned = text.replace(new RegExp(`\\[?${taskId}\\]?\\s*`, "i"), "").trim();
  return { text: cleaned || text, taskId };
}

function evalTaskIdFromUrl(): string | null {
  try {
    const q = new URLSearchParams(window.location.search).get("eval_task");
    return q ? parseTaskIdFromText(q) : null;
  } catch {
    return null;
  }
}

/** 紧凑模式：不向用户展示连接状态文案（避免「连接中」闪动）。 */
function userFacingStatus(raw: string, _connected: boolean): string {
  if (compactUi) return "";
  return raw;
}

export default function App() {
  const initial = useMemo(() => loadSettings(), []);
  const [gatewayUrl, setGatewayUrl] = useState(initial.gatewayUrl);
  const [token, setToken] = useState(initial.token);
  const [sessionKey, setSessionKey] = useState(initial.sessionKey);
  const [connected, setConnected] = useState(false);
  const [hello, setHello] = useState<GatewayHelloOk | null>(null);
  const [status, setStatus] = useState<string>("disconnected");
  const [log, setLog] = useState<string[]>([]);
  const [rows, setRows] = useState<ChatRow[]>([]);
  const [draft, setDraft] = useState("");
  /** Send 瞬间展示的用户气泡（防 history 刷新覆盖 rows 时对话区空白） */
  const [pendingUserDisplay, setPendingUserDisplay] = useState<{ id: string; text: string } | null>(
    null,
  );
  const [streaming, setStreaming] = useState("");
  const [toolSteps, setToolSteps] = useState<ProcessStep[]>([]);
  const [awaitingAgent, setAwaitingAgent] = useState(false);
  /** 用户发消息后至 chat.final：移动端进度条必须展示 */
  const [agentReplyPending, setAgentReplyPending] = useState(false);
  const [minThinkingUntil, setMinThinkingUntil] = useState(0);
  const [thinkingUiTick, setThinkingUiTick] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [intakeSelections, setIntakeSelections] = useState<Record<number, string>>({});
  const [intakeCustom, setIntakeCustom] = useState<Record<number, string>>({});
  const [intakeFollowUp, setIntakeFollowUp] = useState<Record<number, string>>({});
  const [frozenIntake, setFrozenIntake] = useState<IntakeBlock[] | null>(null);
  const [frozenIntakeIntro, setFrozenIntakeIntro] = useState("");
  const [intakeSubmitted, setIntakeSubmitted] = useState(false);
  const [intakeViaFreetext, setIntakeViaFreetext] = useState(false);
  const [submittedIntake, setSubmittedIntake] = useState<IntakeSubmittedSnapshot | null>(null);
  /** 整趟换纲后 Agent 再出选择题：解锁 intake，展示新问卷 */
  const [intakeUnlockedForNewTrip, setIntakeUnlockedForNewTrip] = useState(false);
  const [supersededIntake, setSupersededIntake] = useState<IntakeSubmittedSnapshot | null>(null);
  const intakeUnlockAppliedRef = useRef("");
  const [intakeAnchorUserId, setIntakeAnchorUserId] = useState<string | null>(null);
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string>("");
  const [historyDrawerOpen, setHistoryDrawerOpen] = useState(false);
  const [mobileNotice, setMobileNotice] = useState("");
  const lastAssistantRowId = useRef<string | null>(null);
  const clientRef = useRef<GatewayBrowserClient | null>(null);
  const connectedRef = useRef(false);
  const createThreadPromiseRef = useRef<Promise<void> | null>(null);
  const autoConnectDone = useRef(false);
  const autoReconnectTimerRef = useRef<number | null>(null);
  const connectInFlightRef = useRef(false);
  const wasEverConnectedRef = useRef(false);
  const [wasEverConnected, setWasEverConnected] = useState(false);
  const autoSessionTried = useRef(false);
  const historyLoadGen = useRef(0);
  const lastHistorySessionRef = useRef("");
  const rowsRef = useRef<ChatRow[]>([]);
  const streamingRef = useRef("");
  const hadSearchPlacesRef = useRef(false);
  const historyHadSearchRef = useRef(false);
  const seenToolsThisRunRef = useRef<Set<string>>(new Set());
  const ackFlushedThisRunRef = useRef(false);
  const ackTextThisRunRef = useRef("");
  const intakeViaFreetextRef = useRef(false);
  const skipIntakeAckIdRef = useRef<string | null>(null);
  const toolStartedThisRunRef = useRef(false);
  const tryEarlyFlushAckRef = useRef<() => void>(() => {});
  const itineraryImageAbortRef = useRef<AbortController | null>(null);
  const itineraryImageJobIdRef = useRef<string | null>(null);
  const lastImagePlanFpRef = useRef("");
  const imageGenSuppressedRef = useRef(false);
  const maybeStartItineraryImageRef = useRef<(planText: string) => void>(() => {});
  const tryTriggerItineraryImageFromRowsRef = useRef<() => void>(() => {});
  const cancelItineraryImageGenRef = useRef<(opts?: { userFollowUp?: boolean }) => void>(() => {});
  const softReconnectRef = useRef(false);
  const [imageGenPending, setImageGenPending] = useState(false);
  const imageGenPendingRef = useRef(false);
  const [ackFlushedTick, setAckFlushedTick] = useState(0);
  const optimisticUserRef = useRef<string | null>(null);
  const historyPollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const refreshHistoryRef = useRef<(opts?: { keepOnEmpty?: boolean; sessionKeyOverride?: string }) => Promise<void>>(
    async () => {},
  );
  const stopHistoryPollRef = useRef<() => void>(() => {});

  // ===== 时序评测：本轮计时 =====
  type TurnTiming = {
    sendTime: number;
    firstTextTime: number | null;
    firstToolTime: number | null;
    endTime: number | null;
    toolCalls: Array<{ name: string; startTime: number; endTime?: number; ok?: boolean; error?: string }>;
  };
  const turnTimingRef = useRef<TurnTiming | null>(null);
  const activeToolsRef = useRef<Map<string, number>>(new Map());
  const evalTurnIndexRef = useRef(0);
  const evalTaskIdRef = useRef<string | null>(evalTaskIdFromUrl());
  const intakeShownLoggedRef = useRef(false);
  const imageGenStartRef = useRef<number | null>(null);
  // ===== 时序评测结束 =====

  const streamScrollRef = useRef<HTMLDivElement | null>(null);
  const streamPinnedToBottomRef = useRef(true);
  const processLogRef = useRef<HTMLDivElement | null>(null);
  const threadsBootstrapped = useRef(false);
  const firstSessionCreating = useRef(false);
  const pendingNewThreadRef = useRef(false);
  const [creatingThread, setCreatingThread] = useState(false);
  const [locationConsent, setLocationConsent] = useState<"pending" | "granted" | "denied">(() =>
    hasStoredLocationConsent() ? "granted" : "pending",
  );
  const [resolvedLocation, setResolvedLocation] = useState<ResolvedLocation | null>(() =>
    hasStoredLocationConsent() ? loadStoredLocationSnapshot() : null,
  );
  const [locationBusy, setLocationBusy] = useState(false);
  const [locationError, setLocationError] = useState("");
  const [locationRefreshFailed, setLocationRefreshFailed] = useState(false);
  const lastInjectedLocationKeyRef = useRef<Map<string, string>>(new Map());
  const locationRefreshInFlightRef = useRef(false);
  const warmupInFlightRef = useRef(false);
  const warmupDoneSessions = useRef<Set<string>>(new Set());
  const warmupPromiseRef = useRef<Promise<void> | null>(null);
  const warmupResolveRef = useRef<(() => void) | null>(null);
  const warmupStateRef = useRef<WarmupState>("idle");
  const awaitingAgentRef = useRef(false);
  const sessionKeyRef = useRef("");
  const finishWarmupRunRef = useRef<(sk: string) => void>(() => {});
  const startSessionWarmupRef = useRef<() => void>(() => {});
  const ensureWarmupCompleteRef = useRef<(timeoutMs?: number) => Promise<void>>(async () => {});

  const appEnabled = locationConsent === "granted";
  const showLocationConsent = locationConsent === "pending";

  // ── Model selector state ──
  const [availableModels, setAvailableModels] = useState<Array<{ id: string; label: string }>>([]);
  const [currentModelId, setCurrentModelId] = useState("doubao-seed-2.0-code");
  const currentModelIdRef = useRef(currentModelId);
  const [modelSwitching, setModelSwitching] = useState(false);
  const [modelSwitchMsg, setModelSwitchMsg] = useState("");
  const [testerLabel, setTesterLabel] = useState<string | null>(() => resolveTesterLabel());
  const deviceIdRef = useRef(getOrCreateDeviceId());

  useEffect(() => {
    currentModelIdRef.current = currentModelId;
  }, [currentModelId]);

  useEffect(() => {
    setTesterLabel(resolveTesterLabel());
  }, []);

  const fetchModels = useCallback(async () => {
    try {
      const resp = await fetch("/api/models");
      const data = await resp.json();
      if (data.ok) {
        setAvailableModels(data.models || []);
        if (data.current) setCurrentModelId(data.current);
      }
    } catch { /* ignore on first load */ }
  }, []);

  const handleSwitchModel = useCallback(async (modelId: string) => {
    if (modelId === currentModelId || modelSwitching) return;
    const fromModelId = currentModelId;
    setModelSwitching(true);
    setModelSwitchMsg("");
    try {
      const resp = await fetch("/api/switch-model", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model_id: modelId }),
      });
      const data = await resp.json();
      if (data.ok) {
        setCurrentModelId(modelId);
        currentModelIdRef.current = modelId;
        setModelSwitchMsg(`已切换至 ${availableModels.find(m => m.id === modelId)?.label || modelId}`);
        setTimeout(() => setModelSwitchMsg(""), 3000);
        const sk = sessionKeyRef.current.trim();
        void fetch("/api/eval/event", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            event: "model_switch",
            sessionKey: sk || `meta:device:${deviceIdRef.current}`,
            recordedAt: Date.now(),
            modelId,
            deviceId: deviceIdRef.current,
            testerLabel,
            payload: { fromModelId, toModelId: modelId },
          }),
        }).catch(() => {});
      } else {
        setModelSwitchMsg(`切换失败: ${data.error || "未知错误"}`);
      }
    } catch (e: any) {
      setModelSwitchMsg(`切换失败: ${e.message || e}`);
    } finally {
      setModelSwitching(false);
    }
  }, [currentModelId, modelSwitching, availableModels, testerLabel]);

  useEffect(() => { fetchModels(); }, [fetchModels]);

  const pushLog = useCallback((line: string) => {
    setLog((prev) => [...prev.slice(-80), `${new Date().toISOString().slice(11, 23)} ${line}`]);
  }, []);

  const lastAssistantBubble = useMemo(() => {
    for (let i = rows.length - 1; i >= 0; i--) {
      const r = rows[i]!;
      if (String(r.role).toLowerCase() !== "assistant") continue;
      if (isNoiseAssistantBubble(r.text)) continue;
      return r;
    }
    return null;
  }, [rows]);

  const lastUserBubble = useMemo(() => {
    for (let i = rows.length - 1; i >= 0; i--) {
      const r = rows[i]!;
      if (String(r.role).toLowerCase() === "user") return r;
    }
    return null;
  }, [rows]);

  const lastUserIsIntakeSubmission = useMemo(
    () => isIntakeSubmissionText(lastUserBubble?.text ?? ""),
    [lastUserBubble],
  );

  /** 问卷解析：仅 intake 阶段；提交后不再解析 plan/ack（换纲解锁后除外） */
  const intakeParseText = useMemo(() => {
    if (!intakeUnlockedForNewTrip && (intakeSubmitted || lastUserIsIntakeSubmission || intakeViaFreetext)) {
      return "";
    }

    const live = streaming.trim();
    if (live) {
      const liveIntake = extractIntakeOnlyText(live);
      if (parseQuestionBlocks(liveIntake).length > 0) return liveIntake;
      // 流式前导语阶段尚无 A/B/C：继续从 rows 解析，避免整段空窗
    }

    const anchorUserIdx = findCurrentTurnAnchorIdx(rows);
    if (anchorUserIdx < 0) return "";

    for (let i = anchorUserIdx + 1; i < rows.length; i++) {
      const r = rows[i]!;
      if (String(r.role).toLowerCase() !== "assistant") continue;
      const t = stripLeadingAssistantPlaceholders(r.text);
      if (isEmptyAssistantPlaceholder(t)) continue;
      const intakeOnly = extractIntakeOnlyText(t);
      if (parseQuestionBlocks(intakeOnly).length > 0) return intakeOnly;
    }
    return "";
  }, [rows, streaming, intakeSubmitted, lastUserIsIntakeSubmission, intakeUnlockedForNewTrip, intakeViaFreetext]);

  const intakeSurvey = useMemo(() => {
    const t = intakeParseText;
    if (!t.trim()) return { intro: "", blocks: [] as IntakeBlock[] };
    return parseIntakeSurvey(t);
  }, [intakeParseText]);

  const intakeBlocks = intakeSurvey.blocks;
  const intakeIntro = intakeSurvey.intro;

  const currentTurnAnchorIdx = useMemo(() => findCurrentTurnAnchorIdx(rows), [rows]);
  const currentTurnAnchorId = useMemo(
    () => (currentTurnAnchorIdx >= 0 ? rows[currentTurnAnchorIdx]!.id : null),
    [rows, currentTurnAnchorIdx],
  );

  const turnSubmittedIntake = useMemo((): IntakeSubmittedSnapshot | null => {
    if (currentTurnAnchorIdx < 0) return null;
    const cardAnchorIdx = rows.findIndex(
      (r) => r.id === (intakeAnchorUserId ?? findIntakeCardAnchorUserId(rows)),
    );
    const anchorIdx = cardAnchorIdx >= 0 ? cardAnchorIdx : currentTurnAnchorIdx;
    return buildTurnIntakeSnapshot(rows, anchorIdx);
  }, [rows, currentTurnAnchorIdx, intakeAnchorUserId]);

  const sessionPlanningIntake = useMemo(() => findSessionPlanningIntake(rows), [rows]);

  /** 方案已交付后 Agent 再出新一轮选择题（整趟换纲）：解锁并展示新 IntakeCard */
  useEffect(() => {
    if (!sessionHasDeliveredPlan(rows)) return;
    const anchorIdx = findCurrentTurnAnchorIdx(rows);
    if (anchorIdx < 0) return;
    if (isIntakeSubmissionText(rows[anchorIdx]!.text)) return;
    if (!hasPlanBeforeAnchor(rows, anchorIdx)) return;

    const newIntakeText = findLatestIntakeTextAfterAnchor(rows, anchorIdx, streaming);
    if (!newIntakeText) return;
    const newBlocks = parseQuestionBlocks(newIntakeText);
    if (!newBlocks.length) return;

    const prior = findSessionPlanningIntake(rows)?.snapshot;
    if (!prior?.blocks.length) return;
    const newFp = intakeBlocksFingerprint(newBlocks);
    const oldFp = intakeBlocksFingerprint(prior.blocks);
    if (newFp === oldFp) return;

    const unlockKey = `${rows[anchorIdx]!.id}:${newFp}`;
    if (intakeUnlockAppliedRef.current === unlockKey) return;
    intakeUnlockAppliedRef.current = unlockKey;

    setSupersededIntake(prior);
    setIntakeUnlockedForNewTrip(true);
    setIntakeSubmitted(false);
    setIntakeViaFreetext(false);
    setSubmittedIntake(null);
    setIntakeSelections({});
    setIntakeCustom({});
    setIntakeFollowUp({});
    setFrozenIntake(newBlocks);
    if (newIntakeText) {
      const survey = parseIntakeSurvey(newIntakeText);
      if (survey.intro) setFrozenIntakeIntro(survey.intro);
    }
  }, [rows, streaming]);

  useEffect(() => {
    if (turnSubmittedIntake || lastUserIsIntakeSubmission || intakeSubmitted || intakeViaFreetext) return;
    if (currentTurnAnchorIdx < 0) {
      setFrozenIntake(null);
      setFrozenIntakeIntro("");
      return;
    }
    if (intakeBlocks.length > 0) {
      setFrozenIntake(intakeBlocks);
      if (intakeIntro) setFrozenIntakeIntro(intakeIntro);
    } else if (!streaming.trim()) {
      setFrozenIntake(null);
      setFrozenIntakeIntro("");
    }
  }, [
    intakeBlocks,
    intakeIntro,
    currentTurnAnchorIdx,
    streaming,
    lastUserIsIntakeSubmission,
    turnSubmittedIntake,
    intakeSubmitted,
    intakeViaFreetext,
  ]);

  const displayIntakeIntro = frozenIntakeIntro || intakeIntro;

  const persistedIntakeSnapshot =
    intakeUnlockedForNewTrip ? null : (sessionPlanningIntake?.snapshot ?? null);
  const effectiveSubmittedIntake =
    turnSubmittedIntake ??
    persistedIntakeSnapshot ??
    (intakeUnlockedForNewTrip ? null : intakeSubmitted ? submittedIntake : null);
  const intakeLocked = Boolean(effectiveSubmittedIntake) || lastUserIsIntakeSubmission;
  const intakeSkippedViaFreetext =
    intakeViaFreetext || (effectiveSubmittedIntake != null && turnSubmittedIntake == null && !lastUserIsIntakeSubmission);

  const displayIntakeBlocksResolved = useMemo(() => {
    if (intakeLocked && effectiveSubmittedIntake?.blocks.length) {
      return effectiveSubmittedIntake.blocks;
    }
    const merged = mergeIntakeBlocks(frozenIntake, intakeBlocks);
    return merged.length > 0 ? merged : [];
  }, [effectiveSubmittedIntake, frozenIntake, intakeBlocks, intakeLocked]);

  const intakeCardBlocks = displayIntakeBlocksResolved;

  const cardSelections =
    intakeLocked && effectiveSubmittedIntake ? effectiveSubmittedIntake.selections : intakeSelections;

  const showIntakeCard =
    connected &&
    indexOfFirstVisibleUser(rows) >= 0 &&
    (displayIntakeBlocksResolved.length > 0 ||
      (!intakeLocked && hasIntakeQuestions(intakeParseText)));

  /** 补槽未提交：隐藏过渡 assistant 气泡与工具进展（含 read/weather） */
  const intakePhasePending = useMemo(() => {
    if (intakeLocked || lastUserIsIntakeSubmission || intakeSkippedViaFreetext) return false;
    const anchorIdx = findCurrentTurnAnchorIdx(rows);
    if (anchorIdx < 0) return false;
    if (hasPlanAfterAnchor(rows, anchorIdx)) return false;
    if (displayIntakeBlocksResolved.length > 0) return true;
    if (hasIntakeQuestions(intakeParseText)) return true;
    // 用户已发规划首句、尚未出长文方案：一律只展示 IntakeCard（不必等 awaitingAgent）
    return true;
  }, [
    displayIntakeBlocksResolved.length,
    rows,
    intakeLocked,
    intakeParseText,
    lastUserIsIntakeSubmission,
    intakeSkippedViaFreetext,
  ]);

  useEffect(() => {
    awaitingAgentRef.current = awaitingAgent;
  }, [awaitingAgent]);

  useEffect(() => {
    sessionKeyRef.current = sessionKey.trim();
  }, [sessionKey]);

  const evalThreadMeta = useCallback(() => {
    const t = threads.find((x) => x.id === activeThreadId);
    const title = t?.title ?? "";
    const taskId = evalTaskIdRef.current ?? parseTaskIdFromText(title);
    return { threadTitle: title, taskId };
  }, [threads, activeThreadId]);

  const logEvalEvent = useCallback(
    async (event: string, payload: Record<string, unknown> = {}) => {
      const sk = sessionKeyRef.current.trim();
      if (!sk) return;
      const meta = evalThreadMeta();
      const thread = threads.find((x) => x.id === activeThreadId);
      const modelId =
        (typeof payload.modelId === "string" ? payload.modelId : undefined) ||
        thread?.modelId ||
        currentModelIdRef.current;
      const { modelId: _drop, ...restPayload } = payload;
      try {
        await fetch("/api/eval/event", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            event,
            sessionKey: sk,
            recordedAt: Date.now(),
            taskId: meta.taskId,
            threadTitle: meta.threadTitle,
            turnIndex: evalTurnIndexRef.current,
            modelId,
            deviceId: deviceIdRef.current,
            testerLabel,
            payload: { ...restPayload, modelId },
          }),
        });
      } catch {
        /* eval API 不可用时静默 */
      }
    },
    [activeThreadId, evalThreadMeta, testerLabel, threads],
  );

  const intakeSubmittedLoggedRef = useRef(false);
  const lastToolProgressCountRef = useRef(0);
  const loggedProcessStepIdsRef = useRef(new Set<string>());

  useEffect(() => {
    if (!showIntakeCard || intakeShownLoggedRef.current || displayIntakeBlocksResolved.length === 0) return;
    intakeShownLoggedRef.current = true;
    const tt = turnTimingRef.current;
    void logEvalEvent("intake_shown", {
      phase: "A",
      blockCount: displayIntakeBlocksResolved.length,
      ttftMs:
        tt && tt.firstTextTime != null ? tt.firstTextTime - tt.sendTime : undefined,
    });
  }, [showIntakeCard, displayIntakeBlocksResolved.length, logEvalEvent]);

  useEffect(() => {
    if (!intakeLocked || !lastUserIsIntakeSubmission || intakeSubmittedLoggedRef.current) return;
    intakeSubmittedLoggedRef.current = true;
    void logEvalEvent("intake_submitted", { phase: "B" });
  }, [intakeLocked, lastUserIsIntakeSubmission, logEvalEvent]);

  /** 任务进展区每一行（含「开始执行本轮任务」、生图、发送态）写入 eval 日志 */
  useEffect(() => {
    if (toolSteps.length === 0) {
      loggedProcessStepIdsRef.current.clear();
      return;
    }
    toolSteps.forEach((s, idx) => {
      if (loggedProcessStepIdsRef.current.has(s.id)) return;
      loggedProcessStepIdsRef.current.add(s.id);
      void logEvalEvent("process_step", {
        stepId: s.id,
        msg: s.msg,
        clock: s.clock,
        stepIndex: idx,
      });
    });
  }, [toolSteps, logEvalEvent]);

  useEffect(() => {
    if (!intakeLocked) {
      lastToolProgressCountRef.current = 0;
      return;
    }
    const lifecareSteps = toolSteps.filter((s) =>
      /天气|POI|路线|搜|规划|工具|加载|并行|MCP/i.test(s.msg),
    );
    if (lifecareSteps.length <= lastToolProgressCountRef.current) return;
    const step = lifecareSteps[lifecareSteps.length - 1]!;
    lastToolProgressCountRef.current = lifecareSteps.length;
    void logEvalEvent("tool_progress", {
      phase: "B",
      label: step.msg,
      stepCount: lifecareSteps.length,
    });
  }, [toolSteps, intakeLocked, logEvalEvent]);

  useEffect(() => {
    if (intakeSubmitted || intakeAnchorUserId) return;
    const anchorId = findIntakeCardAnchorUserId(rows);
    if (anchorId) setIntakeAnchorUserId(anchorId);
  }, [rows, intakeSubmitted, intakeAnchorUserId]);

  useEffect(() => {
    if (!currentTurnAnchorId) return;
    setIntakeSelections({});
    setIntakeCustom({});
    setIntakeFollowUp({});
  }, [currentTurnAnchorId]);

  useEffect(() => {
    if (turnSubmittedIntake) {
      setSubmittedIntake(turnSubmittedIntake);
      setIntakeSubmitted(true);
      setFrozenIntake(turnSubmittedIntake.blocks);
      const cardAnchorId = intakeAnchorUserId ?? findIntakeCardAnchorUserId(rows);
      const cardAnchorIdx = cardAnchorId ? rows.findIndex((r) => r.id === cardAnchorId) : -1;
      const anchorIdx = cardAnchorIdx >= 0 ? cardAnchorIdx : currentTurnAnchorIdx;
      if (anchorIdx >= 0 && !buildTurnSubmittedIntake(rows, anchorIdx)) {
        setIntakeViaFreetext(true);
      }
      return;
    }
    if (!awaitingAgent && !intakeViaFreetext) {
      setIntakeSubmitted(false);
      setSubmittedIntake(null);
    }
  }, [turnSubmittedIntake, awaitingAgent, intakeViaFreetext, rows, intakeAnchorUserId, currentTurnAnchorIdx]);

  const canSubmitIntake = intakeAnswerComplete(
    frozenIntake ?? intakeBlocks,
    intakeSelections,
    intakeCustom,
    intakeFollowUp,
  );

  /** 历史里已有同条 assistant 时隐藏 live，避免与 mergeStreamText + history 双写重复 */
  const showLiveBubble = useMemo(() => {
    const s = streaming.trim().replace(/\r\n/g, "\n");
    if (!s) return false;
    if (indexOfFirstVisibleUser(rows) < 0) return false;
    if (intakePhasePending) return false;
    if (isIntakeQuestionBubble(s)) return false;
    const last = rows[rows.length - 1];
    if (last && String(last.role).toLowerCase() === "user") return true;
    let lastAsst: ChatRow | undefined;
    for (let i = rows.length - 1; i >= 0; i--) {
      if (String(rows[i]!.role).toLowerCase() === "assistant") {
        lastAsst = rows[i];
        break;
      }
    }
    if (!lastAsst) return true;
    const t = lastAsst.text.trim().replace(/\r\n/g, "\n");
    if (t === s) return false;
    if (t.length >= s.length - 4 && s.length > 20 && t.startsWith(s)) return false;
    if (t.length > 400 && s.length > 400 && t.slice(0, 280) === s.slice(0, 280)) return false;
    return true;
  }, [rows, streaming, showIntakeCard, intakePhasePending]);

  useEffect(() => {
    connectedRef.current = connected;
  }, [connected]);

  useEffect(() => {
    rowsRef.current = rows;
    if (
      pendingUserDisplay &&
      rows.some(
        (r) =>
          isVisibleUserRow(r) &&
          (r.id === pendingUserDisplay.id ||
            extractUserVisibleTextFromMessage(r.text).trim() === pendingUserDisplay.text.trim()),
      )
    ) {
      setPendingUserDisplay(null);
    }
  }, [rows, pendingUserDisplay]);

  useEffect(() => {
    streamingRef.current = streaming;
  }, [streaming]);

  useEffect(() => {
    intakeViaFreetextRef.current = intakeViaFreetext;
  }, [intakeViaFreetext]);

  const tryPinSkipIntakeEntryAck = useCallback(() => {
    if (!intakeViaFreetextRef.current) return;
    const stream = streamingRef.current.trim();
    const split = extractPinnedSkipIntakeEntryAck(stream);
    if (!split) return;

    const id = skipIntakeAckIdRef.current ?? `a-skip-intake-ack-${Date.now().toString(36)}`;
    skipIntakeAckIdRef.current = id;

    setRows((prev) => {
      const existingIdx = prev.findIndex((r) => r.id === id);
      const row: ChatRow = { role: "assistant", text: split.ack, id };
      if (existingIdx >= 0) {
        if (prev[existingIdx]!.text === split.ack) return prev;
        const next = [...prev];
        next[existingIdx] = row;
        rowsRef.current = next;
        return next;
      }
      const next = [...prev, row];
      rowsRef.current = next;
      return next;
    });

    if (split.remainder) {
      streamingRef.current = split.remainder;
      setStreaming(split.remainder);
      return;
    }
    if (stream === split.ack || (split.ack.length > 40 && stream.startsWith(split.ack.slice(0, 40)))) {
      streamingRef.current = "";
      setStreaming("");
    }
  }, []);

  const tryPinSkipIntakeEntryAckRef = useRef<() => void>(() => {});
  useEffect(() => {
    tryPinSkipIntakeEntryAckRef.current = tryPinSkipIntakeEntryAck;
  }, [tryPinSkipIntakeEntryAck]);

  const tryEarlyFlushAck = useCallback(() => {
    if (ackFlushedThisRunRef.current) return;
    const stream = streamingRef.current.trim();
    if (!stream || isEmptyAssistantPlaceholder(stream) || isPlanMessage(stream)) return;
    if (!shouldEarlyFlushAck(stream)) return;
    // 行程规划场景：流式文本含选择题特征时不提前 flush ack，
    // 否则 ack 被 flush 后又被 intake 处理逻辑"吃掉"造成闪动
    if (isIntakeQuestionText(stream)) return;
    if (isSkipIntakeEntryAck(stream)) {
      tryPinSkipIntakeEntryAckRef.current();
      return;
    }
    // B 阶段 / 已提交过选择题 / 追问轮：ack 只走任务进展，不进对话区闪泡
    if (
      shouldSkipEarlyFlushAckForPlanPhase(rowsRef.current, optimisticUserRef.current, {
        toolStarted: toolStartedThisRunRef.current,
        hadSearch: hadSearchPlacesRef.current,
        historyHadSearch: historyHadSearchRef.current,
        intakeViaFreetext: intakeViaFreetextRef.current,
      })
    ) {
      return;
    }

    ackFlushedThisRunRef.current = true;
    ackTextThisRunRef.current = stream;
    setStreaming("");
    streamingRef.current = "";
    setAckFlushedTick((t) => t + 1);
  }, []);

  useEffect(() => {
    tryEarlyFlushAckRef.current = tryEarlyFlushAck;
  }, [tryEarlyFlushAck]);

  const displayRows = useMemo(() => presentChatRows(rows), [rows]);

  /** 用户首条可见消息前：不展示任务进展明细（预热等后台步骤对用户不可见） */
  const hasVisibleUserMessage = useMemo(() => indexOfFirstVisibleUser(rows) >= 0, [rows]);
  /** 选择题未提交阶段（IntakeCard 可交互） */
  const intakeActive =
    showIntakeCard && !intakeLocked && displayIntakeBlocksResolved.length > 0;
  /** 补槽 A 阶段：过滤 lifecare 主工具，保留带时间戳的高层进展 */
  const suppressToolProgress = intakePhasePending;
  const visibleToolSteps = useMemo(() => {
    if (!hasVisibleUserMessage) return [];
    if (suppressToolProgress) return filterIntakePhaseToolSteps(toolSteps);
    return toolSteps;
  }, [hasVisibleUserMessage, suppressToolProgress, toolSteps]);

  const sessionPoisRefreshKey = toolSteps.length + rows.length;
  const sessionPois = useSessionPois(sessionKey, sessionPoisRefreshKey);

  const lastUserText = useMemo(() => lastUserTextInRows(rows), [rows]);

  const isFollowUpTurn = useMemo(() => {
    let userCount = 0;
    for (const r of rows) {
      if (isVisibleUserRow(r) && !isIntakeSubmissionText(r.text)) userCount++;
    }
    return userCount > 1 || (!!pendingUserDisplay && userCount >= 1);
  }, [rows, pendingUserDisplay]);

  const lastVisibleAssistantRowId = useMemo(() => {
    for (let i = displayRows.length - 1; i >= 0; i--) {
      const r = displayRows[i]!;
      if (String(r.role).toLowerCase() === "assistant" && !isHiddenChatRow("assistant", r.text)) {
        return r.id;
      }
    }
    return "";
  }, [displayRows]);

  /** A 阶段已发 user、问卷尚未挂载：对话区展示加载态（避免 read 后 10～20s 全黑） */
  const showIntakeLoading = useMemo(
    () =>
      intakePhasePending &&
      !showIntakeCard &&
      !intakeSkippedViaFreetext &&
      !intakeLocked &&
      hasVisibleUserMessage &&
      (awaitingAgent || visibleToolSteps.length > 0),
    [
      intakePhasePending,
      showIntakeCard,
      intakeSkippedViaFreetext,
      intakeLocked,
      hasVisibleUserMessage,
      awaitingAgent,
      visibleToolSteps.length,
    ],
  );

  const friendlyThinking = useMemo(
    () =>
      mobileShell
        ? mapFriendlyProgress({
            visibleToolSteps,
            awaitingAgent,
            agentReplyPending,
            isFollowUpTurn,
            intakeActive,
            intakeLocked,
            intakePhasePending,
            showIntakeLoading,
            imageGenPending,
            connected,
            hasVisibleUserMessage,
            streaming: streaming.trim().length > 0,
            lastUserText: lastUserText ?? "",
            resolvedLocation,
          })
        : null,
    [
      visibleToolSteps,
      awaitingAgent,
      agentReplyPending,
      isFollowUpTurn,
      intakeActive,
      intakeLocked,
      intakePhasePending,
      showIntakeLoading,
      imageGenPending,
      connected,
      hasVisibleUserMessage,
      streaming,
      lastUserText,
      resolvedLocation,
    ],
  );

  const pinnedSkipIntakeAck = useMemo(() => {
    for (let i = rows.length - 1; i >= 0; i--) {
      const r = rows[i]!;
      if (String(r.role).toLowerCase() !== "assistant") continue;
      if (isSkipIntakeEntryAck(r.text)) return r.text.trim();
    }
    return "";
  }, [rows]);

  const liveStreamText = useMemo(
    () => {
      // 与 tryEarlyFlushAck 同一判定：B 阶段/追问轮纯 ack 不在对话区闪现
      const suppressAck = shouldSkipEarlyFlushAckForPlanPhase(
        rowsRef.current,
        optimisticUserRef.current,
        {
          toolStarted: toolStartedThisRunRef.current,
          hadSearch: hadSearchPlacesRef.current,
          historyHadSearch: historyHadSearchRef.current,
        },
      );
      return liveStreamDisplayText(
        streaming,
        ackTextThisRunRef.current,
        ackFlushedThisRunRef.current,
        pinnedSkipIntakeAck || undefined,
        suppressAck,
      );
    },
    [streaming, ackFlushedTick, pinnedSkipIntakeAck],
  );

  const formalContentStarted = useMemo(() => {
    if (Date.now() < minThinkingUntil) return false;
    if (showIntakeCard && displayIntakeBlocksResolved.length > 0 && !intakeLocked) return true;
    const st = streaming.trim();
    if (st && isIntakeQuestionBubble(st)) return true;
    if (!showLiveBubble) return false;
    const live = liveStreamText.trim();
    if (!live || isNoiseAssistantBubble(live) || isRawToolPayloadText(live)) return false;
    if (live.length < 48) return false;
    if (isPlanMessage(live)) return true;
    if (live.length >= 96) return true;
    return false;
  }, [
    minThinkingUntil,
    thinkingUiTick,
    showIntakeCard,
    displayIntakeBlocksResolved.length,
    intakeLocked,
    streaming,
    showLiveBubble,
    liveStreamText,
  ]);

  const thinkingDisplay = friendlyThinking ?? { main: "✍️ 攻略制定中…" };

  const wantMobileThinking = useMemo(
    () =>
      mobileShell &&
      !intakeActive &&
      !formalContentStarted &&
      (agentReplyPending ||
        showIntakeLoading ||
        imageGenPending ||
        awaitingAgent ||
        visibleToolSteps.length > 0),
    [
      mobileShell,
      intakeActive,
      formalContentStarted,
      agentReplyPending,
      showIntakeLoading,
      imageGenPending,
      awaitingAgent,
      visibleToolSteps.length,
    ],
  );

  useEffect(() => {
    if (!agentReplyPending) return;
    const wait = Math.max(0, minThinkingUntil - Date.now());
    const t = window.setTimeout(() => setThinkingUiTick((n) => n + 1), wait + 40);
    return () => window.clearTimeout(t);
  }, [agentReplyPending, minThinkingUntil]);

  useEffect(() => {
    const el = streamScrollRef.current;
    if (!el) return;
    const onScroll = () => {
      const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
      streamPinnedToBottomRef.current = distance < 96;
    };
    onScroll();
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    const el = streamScrollRef.current;
    if (!el || !streamPinnedToBottomRef.current) return;
    el.scrollTop = el.scrollHeight;
  }, [rows, streaming, showIntakeCard]);

  useEffect(() => {
    const el = processLogRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [toolSteps, awaitingAgent, hasVisibleUserMessage]);

  useEffect(() => {
    if (!awaitingAgent) return;
    const t = window.setTimeout(() => setAwaitingAgent(false), 120_000);
    return () => window.clearTimeout(t);
  }, [awaitingAgent]);

  useEffect(() => {
    if (!awaitingAgent || !lastUserBubble) return;
    if (intakeViaFreetextRef.current || intakeLocked) return;
    const userIdx = rows.findIndex((r) => r.id === lastUserBubble.id);
    if (userIdx < 0) return;
    for (let i = rows.length - 1; i > userIdx; i--) {
      const r = rows[i]!;
      if (String(r.role).toLowerCase() !== "assistant") continue;
      if (!isIntakeQuestionBubble(r.text) || r.text.length > 600) {
        setAwaitingAgent(false);
      }
      break;
    }
  }, [rows, awaitingAgent, lastUserBubble, intakeLocked]);

  useEffect(() => {
    if (threadsBootstrapped.current) return;
    threadsBootstrapped.current = true;
    migrateLocalChatStorage();
    getOrCreateDeviceId();
    const list = loadThreads();
    const savedActive = localStorage.getItem(ACTIVE_THREAD_LS) ?? "";
    if (!list.length) {
      setThreads([]);
      setActiveThreadId("");
      return;
    }
    setThreads(list);
    const pick = list.find((x) => x.id === savedActive) ?? list[0]!;
    if (pick) {
      setActiveThreadId(pick.id);
      localStorage.setItem(ACTIVE_THREAD_LS, pick.id);
      if (pick.sessionKey.trim()) {
        setSessionKey(pick.sessionKey);
        localStorage.setItem("gw.session", pick.sessionKey);
      }
    }
  }, [initial.sessionKey]);

  useEffect(() => {
    const id = lastAssistantBubble?.id ?? null;
    if (id !== lastAssistantRowId.current) {
      lastAssistantRowId.current = id;
      setIntakeSelections({});
    }
  }, [lastAssistantBubble?.id]);

  const stopHistoryPoll = useCallback(() => {
    if (historyPollTimerRef.current != null) {
      window.clearInterval(historyPollTimerRef.current);
      historyPollTimerRef.current = null;
    }
  }, []);

  /** 切线程 / 新建会话：abort + unsubscribe 旧 session，丢弃在途 history/WS */
  const detachInactiveSession = useCallback(
    async (oldSk: string) => {
      const sk = oldSk.trim();
      if (!sk) return;
      stopHistoryPoll();
      historyLoadGen.current += 1;
      cancelItineraryImageGenRef.current();
      turnTimingRef.current = null;
      optimisticUserRef.current = null;
      streamingRef.current = "";
      setStreaming("");
      const c = clientRef.current;
      if (!c?.connected) return;
      try {
        await c.request("chat.abort", { sessionKey: sk });
      } catch {
        /* ignore */
      }
      try {
        await c.request("sessions.messages.unsubscribe", { sessionKey: sk });
      } catch {
        /* ignore */
      }
    },
    [stopHistoryPoll],
  );

  const persistSettings = useCallback(() => {
    localStorage.setItem("gw.url", gatewayUrl);
    localStorage.setItem("gw.token", token);
    localStorage.setItem("gw.session", sessionKey);
  }, [gatewayUrl, token, sessionKey]);

  const stopClientOnly = useCallback(() => {
    stopHistoryPoll();
    clientRef.current?.stop();
    clientRef.current = null;
  }, [stopHistoryPoll]);

  const disconnect = useCallback(() => {
    if (autoReconnectTimerRef.current != null) {
      window.clearTimeout(autoReconnectTimerRef.current);
      autoReconnectTimerRef.current = null;
    }
    connectInFlightRef.current = false;
    stopClientOnly();
    setConnected(false);
    wasEverConnectedRef.current = false;
    setWasEverConnected(false);
    setHello(null);
    setToolSteps([]);
    setAwaitingAgent(false);
    setStreaming("");
    setStatus("disconnected");
    autoSessionTried.current = false;
    lastHistorySessionRef.current = "";
    historyLoadGen.current += 1;
  }, [stopClientOnly]);

  const refreshHistory = useCallback(
    async (opts?: { keepOnEmpty?: boolean; sessionKeyOverride?: string }) => {
      const c = clientRef.current;
      if (!c?.connected) {
        setStatus("not connected");
        return;
      }
      const sk = (opts?.sessionKeyOverride ?? sessionKey).trim();
      if (!sk) {
        setStatus("fill session key first (or use Discover)");
        return;
      }
      const loadGen = ++historyLoadGen.current;
      setHistoryLoading(true);
      try {
        const data = await c.request("chat.history", { sessionKey: sk });
        if (loadGen !== historyLoadGen.current) return;
        if (sessionKeyRef.current.trim() !== sk) return;
        if (historyDataUsedSearchPlaces(data)) {
          historyHadSearchRef.current = true;
          hadSearchPlacesRef.current = true;
        }
        const { sessionKey: skCanon, rows: serverRows } = extractHistoryRows(data);
        if (skCanon && skCanon !== sk) return;
        const pending = optimisticUserRef.current;
        setRows((prev) => {
          if (loadGen !== historyLoadGen.current) return prev;
          if (sessionKeyRef.current.trim() !== sk) return prev;
          const sameSession = sessionKeyRef.current.trim() === sk;
          const basePrev = sameSession ? prev : [];
          let merged = reconcileChatRows(basePrev, serverRows, { pendingUserText: pending });
          // ===== 时序评测：保留本地 timing 字段，不被 server 数据覆盖 =====
          if (basePrev.length > 0) {
            merged = merged.map((row) => {
              const prevRow = basePrev.find(
                (pr) => pr.id === row.id || (pr.role === row.role && pr.text === row.text),
              );
              if (prevRow && (prevRow.timestamp || prevRow.ttftMs || prevRow.durationMs)) {
                return {
                  ...row,
                  timestamp: prevRow.timestamp,
                  ttftMs: prevRow.ttftMs,
                  durationMs: prevRow.durationMs,
                  firstToolMs: prevRow.firstToolMs,
                  toolCalls: prevRow.toolCalls,
                };
              }
              return row;
            });
          }
          // ===== 时序评测结束 =====
          merged = appendPersistedItineraryImage(sk, merged);
          if (pending && serverRows.length > 0) {
            const lu = lastUserTextInRows(serverRows);
            if (lu != null && lu.trim() === pending.trim()) optimisticUserRef.current = null;
          }
          if (
            merged.length === prev.length &&
            rowsStableSignature(merged) === rowsStableSignature(prev)
          ) {
            return prev;
          }
          rowsRef.current = merged;
          const stream = streamingRef.current.trim();
          if (stream && merged.length > 0) {
            const last = merged[merged.length - 1]!;
            if (
              String(last.role).toLowerCase() === "assistant" &&
              last.text.length >= stream.length &&
              last.text.slice(0, stream.length) === stream
            ) {
              queueMicrotask(() => setStreaming(""));
            }
          }
          if (merged.length > 0) return merged;
          if (opts?.keepOnEmpty && prev.length > 0 && sameSession) {
            merged = reconcileChatRows(prev, [], { pendingUserText: pending });
            merged = appendPersistedItineraryImage(sk, merged);
            rowsRef.current = merged;
            return merged;
          }
          return merged;
        });
        lastHistorySessionRef.current = sk;
        if (skCanon && skCanon !== sk) setSessionKey(skCanon);
        if (serverRows.length > 0) setStatus(`history ok (${serverRows.length} rows)`);
        else if (opts?.keepOnEmpty) setStatus("history still syncing…");
        else setStatus("history ok (0 rows)");
      } catch (e) {
        if (loadGen === historyLoadGen.current) {
          setStatus(`chat.history failed: ${e instanceof Error ? e.message : String(e)}`);
        }
      } finally {
        if (loadGen === historyLoadGen.current) {
          setHistoryLoading(false);
          if (!awaitingAgentRef.current && !imageGenSuppressedRef.current) {
            window.setTimeout(() => tryTriggerItineraryImageFromRowsRef.current(), 80);
          }
        }
      }
    },
    [sessionKey],
  );

  useEffect(() => {
    refreshHistoryRef.current = refreshHistory;
  }, [refreshHistory]);

  useEffect(() => {
    stopHistoryPollRef.current = stopHistoryPoll;
  }, [stopHistoryPoll]);

  const maybeApplyHarnessToLastAssistant = useCallback(async () => {
    const sk = sessionKey.trim();
    if (!sk) return;
    const snapshot = rowsRef.current;
    for (let i = snapshot.length - 1; i >= 0; i--) {
      const r = snapshot[i]!;
      if (String(r.role).toLowerCase() !== "assistant") continue;
      if (hasVisibleUserAfterRowIndex(snapshot, i)) return;
      const repaired = await requestHarnessRepair(sk, r.text);
      if (!repaired || repaired.skipped || repaired.text === r.text) return;
      setRows((prev) => {
        const idx = prev.findIndex((x) => x.id === r.id);
        if (idx < 0) return prev;
        const next = [...prev];
        next[idx] = { ...next[idx]!, text: repaired.text };
        if (rowsStableSignature(next) === rowsStableSignature(prev)) return prev;
        rowsRef.current = next;
        return next;
      });
      return;
    }
  }, [sessionKey]);

  const flushStreamingIntoRows = useCallback(() => {
    const streamBuf = stripLeadingAssistantPlaceholders(streamingRef.current.trim());
    if (!streamBuf || isEmptyAssistantPlaceholder(streamBuf) || isLocationBootstrapGreeting(streamBuf)) return;
    setRows((prev) => {
      const last = prev[prev.length - 1];
      if (last && String(last.role).toLowerCase() === "assistant" && last.text === streamBuf) {
        return prev;
      }
      // ===== 时序评测：构建含 timing 的 assistant ChatRow =====
      const tt = turnTimingRef.current;
      const now = Date.now();
      const assistantRow: ChatRow = {
        role: "assistant",
        text: streamBuf,
        id: `a-flush-${now.toString(36)}`,
        timestamp: now,
        ...(tt
          ? {
              ttftMs: tt.firstTextTime != null ? tt.firstTextTime - tt.sendTime : undefined,
              durationMs: tt.endTime != null ? tt.endTime - tt.sendTime : undefined,
              firstToolMs: tt.firstToolTime != null ? tt.firstToolTime - tt.sendTime : undefined,
              toolCalls:
                tt.toolCalls.length > 0
                  ? tt.toolCalls.map((tc) => ({
                      name: tc.name,
                      durationMs: tc.endTime != null ? tc.endTime - tc.startTime : undefined,
                      ok: tc.ok,
                      error: tc.error,
                    }))
                  : undefined,
            }
          : {}),
      };
      const next = [...prev, assistantRow];
      // ===== 时序评测结束 =====
      rowsRef.current = next;
      return next;
    });
    setStreaming("");
    void maybeApplyHarnessToLastAssistant();
  }, [maybeApplyHarnessToLastAssistant]);

  const flushStreamingIntoRowsRef = useRef(flushStreamingIntoRows);
  useEffect(() => {
    flushStreamingIntoRowsRef.current = flushStreamingIntoRows;
  }, [flushStreamingIntoRows]);

  // ===== 时序评测：持久化本轮日志 =====
  async function persistTurnLog(sk: string, userRow: ChatRow, assistantRow: ChatRow) {
    const isIntake = hasIntakeQuestions(extractIntakeOnlyText(assistantRow.text));
    const phase = isIntake ? "A" : intakeLocked ? "B" : "other";
    try {
      await fetch("/api/eval/log", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sessionKey: sk,
          user: { text: userRow.text.slice(0, 2000), timestamp: userRow.timestamp },
          assistant: {
            text: assistantRow.text.slice(0, 2000),
            timestamp: assistantRow.timestamp,
            ttftMs: assistantRow.ttftMs,
            durationMs: assistantRow.durationMs,
            firstToolMs: assistantRow.firstToolMs,
            toolCalls: assistantRow.toolCalls,
          },
          recordedAt: Date.now(),
        }),
      });
    } catch {
      /* legacy endpoint */
    }
    void logEvalEvent("turn_complete", {
      phase,
      isIntakeQuestion: isIntake,
      isPlan: isPlanMessage(assistantRow.text),
      user: { text: userRow.text.slice(0, 500), timestamp: userRow.timestamp },
      assistant: {
        text: assistantRow.text.slice(0, 800),
        timestamp: assistantRow.timestamp,
        ttftMs: assistantRow.ttftMs,
        durationMs: assistantRow.durationMs,
        firstToolMs: assistantRow.firstToolMs,
        toolCalls: assistantRow.toolCalls,
      },
    });
  }
  // ===== 时序评测结束 =====

  const cancelItineraryImageGen = useCallback((opts?: { userFollowUp?: boolean }) => {
    itineraryImageAbortRef.current?.abort();
    itineraryImageAbortRef.current = null;
    const jobId = itineraryImageJobIdRef.current;
    itineraryImageJobIdRef.current = null;
    if (jobId) void cancelItineraryImageJob(jobId);
    if (opts?.userFollowUp) {
      imageGenSuppressedRef.current = true;
      const planText = findLongestPlanText(rowsRef.current, ackTextThisRunRef.current);
      if (planText) lastImagePlanFpRef.current = planTextFingerprint(planText);
      clearPersistedItineraryImage(sessionKeyRef.current.trim());
    }
    setImageGenPending(false);
  }, []);

  useEffect(() => {
    cancelItineraryImageGenRef.current = cancelItineraryImageGen;
  }, [cancelItineraryImageGen]);

  const maybeStartItineraryImage = useCallback(
    (planText: string) => {
      if (!appEnabled) return;
      if (imageGenSuppressedRef.current) return;
      if (awaitingAgentRef.current) return;
      if (indexOfFirstVisibleUser(rowsRef.current) < 0) return;
      if (!shouldAllowItineraryImageForRows(rowsRef.current)) return;
      const text = planText.trim();
      if (!text || isNoiseAssistantBubble(text)) return;
      if (!isCompleteItineraryPlan(text, hadSearchPlacesRef.current)) return;
      const fp = planTextFingerprint(text);
      if (fp === lastImagePlanFpRef.current) return;
      if (sessionHasPersistedItineraryImage(sessionKey.trim())) return;

      cancelItineraryImageGen();
      lastImagePlanFpRef.current = fp;
      const jobId = newIdempotencyKey();
      itineraryImageJobIdRef.current = jobId;
      const ac = new AbortController();
      itineraryImageAbortRef.current = ac;
      setImageGenPending(true);
      setToolSteps((p) => appendProcessStep(p, "正在绘制行程一览图（长文已就绪，约需 1 分钟）…"));
      imageGenStartRef.current = Date.now();
      void logEvalEvent("image_gen_start", { planChars: text.length });

      void (async () => {
        try {
          const result = await requestItineraryImage(text, jobId, ac.signal);
          if (ac.signal.aborted || (!result.ok && "cancelled" in result && result.cancelled)) {
            setToolSteps((p) => appendProcessStep(p, "行程图已取消（您开始了新对话）"));
            void logEvalEvent("image_gen_complete", { ok: false, cancelled: true });
            return;
          }
          if (!result.ok || !("image_url" in result)) {
            pushLog(
              `itinerary-image failed: ${"error" in result ? result.error : "unknown"}`,
            );
            void logEvalEvent("image_gen_complete", {
              ok: false,
              durationMs: imageGenStartRef.current ? Date.now() - imageGenStartRef.current : undefined,
            });
            return;
          }
          if (
            imageGenSuppressedRef.current ||
            !shouldAllowItineraryImageForRows(rowsRef.current)
          ) {
            void logEvalEvent("image_gen_complete", {
              ok: false,
              suppressed: true,
              durationMs: imageGenStartRef.current ? Date.now() - imageGenStartRef.current : undefined,
            });
            return;
          }
          const md = formatItineraryImageMarkdown(result.image_url);
          const imgRow: ChatRow = { role: "assistant", text: md, id: `a-img-${Date.now().toString(36)}` };
          persistItineraryImageRow(sessionKey.trim(), fp, imgRow);
          setRows((prev) => {
            if (!shouldAllowItineraryImageForRows(prev)) return prev;
            const last = prev[prev.length - 1];
            if (last && String(last.role).toLowerCase() === "assistant" && last.text === md) return prev;
            const next = [...prev, imgRow];
            rowsRef.current = next;
            return next;
          });
          setToolSteps((p) => appendProcessStep(p, "行程一览图已生成"));
          void logEvalEvent("image_gen_complete", {
            ok: true,
            durationMs: imageGenStartRef.current ? Date.now() - imageGenStartRef.current : undefined,
          });
        } catch (e) {
          if (ac.signal.aborted) {
            setToolSteps((p) => appendProcessStep(p, "行程图已取消（您开始了新对话）"));
            return;
          }
          pushLog(`itinerary-image request error: ${e instanceof Error ? e.message : String(e)}`);
        } finally {
          if (itineraryImageJobIdRef.current === jobId) {
            itineraryImageJobIdRef.current = null;
            itineraryImageAbortRef.current = null;
          }
          setImageGenPending(false);
        }
      })();
    },
    [appEnabled, cancelItineraryImageGen, logEvalEvent, pushLog, sessionKey],
  );

  useEffect(() => {
    maybeStartItineraryImageRef.current = maybeStartItineraryImage;
  }, [maybeStartItineraryImage]);

  useEffect(() => {
    imageGenPendingRef.current = imageGenPending;
  }, [imageGenPending]);

  const tryTriggerItineraryImageFromRows = useCallback(() => {
    if (!appEnabled) return;
    if (imageGenSuppressedRef.current) return;
    if (awaitingAgentRef.current) return;
    if (indexOfFirstVisibleUser(rowsRef.current) < 0) return;
    if (streamingRef.current.trim()) return;
    if (imageGenPendingRef.current || itineraryImageJobIdRef.current) return;
    if (!shouldAllowItineraryImageForRows(rowsRef.current)) return;
    const snapshot = rowsRef.current;
    if (rowsHasItineraryImage(snapshot)) return;
    if (sessionHasPersistedItineraryImage(sessionKey.trim())) return;
    const planText = findLongestPlanText(snapshot, ackTextThisRunRef.current);
    if (!planText) return;
    const hadSearch = hadSearchPlacesRef.current || historyHadSearchRef.current;
    if (!isCompleteItineraryPlan(planText, hadSearch)) return;
    maybeStartItineraryImageRef.current(planText);
  }, [appEnabled, sessionKey]);

  useEffect(() => {
    tryTriggerItineraryImageFromRowsRef.current = tryTriggerItineraryImageFromRows;
  }, [tryTriggerItineraryImageFromRows]);

  const startHistoryPoll = useCallback(() => {
    stopHistoryPoll();
    let ticks = 0;
    let stable = 0;
    let lastSig = "";
    historyPollTimerRef.current = window.setInterval(() => {
      void (async () => {
        ticks++;
        if (ticks > 55) {
          stopHistoryPoll();
          return;
        }
        await refreshHistory({ keepOnEmpty: true });
        const snapshot = rowsRef.current;
        const sig = snapshot.map((r) => `${r.role}:${r.text.length}`).join("|");
        if (sig === lastSig) stable++;
        else stable = 0;
        lastSig = sig;
        const last = snapshot[snapshot.length - 1];
        const lastRole = last ? String(last.role).toLowerCase() : "";
        if (
          !optimisticUserRef.current &&
          !streamingRef.current.trim() &&
          lastRole === "assistant" &&
          stable >= 2
        ) {
          stopHistoryPoll();
        }
      })();
    }, 700);
  }, [refreshHistory, stopHistoryPoll]);

  const discoverSessions = useCallback(async () => {
    const c = clientRef.current;
    if (!c?.connected) return;
    try {
      const key = await pickSessionKeyAfterConnect(c, hello, pushLog);
      if (key) {
        setSessionKey(key);
        localStorage.setItem("gw.session", key);
        let newActiveId: string | null = null;
        setThreads((prev) => {
          if (!activeThreadId && prev.length === 0) {
            const id = "t-" + Date.now().toString(36);
            newActiveId = id;
            const seed: ChatThread[] = [{ id, sessionKey: key, title: "对话 1", updatedAt: Date.now() }];
            saveThreads(seed);
            return seed;
          }
          if (!activeThreadId) return prev;
          const next = prev.map((t) =>
            t.id === activeThreadId ? { ...t, sessionKey: key, updatedAt: Date.now() } : t,
          );
          saveThreads(next);
          return next;
        });
        if (newActiveId) {
          setActiveThreadId(newActiveId);
          localStorage.setItem(ACTIVE_THREAD_LS, newActiveId);
        }
        setStatus(`picked session (${key.length > 40 ? `${key.slice(0, 36)}…` : key})`);
        void refreshHistory({ sessionKeyOverride: key });
      } else {
        setStatus(
          "Discover: 未解析到 session。可加 ?session=agent:… 或构建变量 VITE_DEFAULT_SESSION_KEY；开 VITE_SHOW_DEBUG 查看 auto: 日志",
        );
      }
    } catch (e) {
      setStatus(`Discover failed: ${formatRpcError(e)}`);
    }
  }, [activeThreadId, hello, pushLog, refreshHistory]);

  const connect = useCallback((softReconnect = false) => {
    if (connectInFlightRef.current) return;
    connectInFlightRef.current = true;
    if (autoReconnectTimerRef.current != null) {
      window.clearTimeout(autoReconnectTimerRef.current);
      autoReconnectTimerRef.current = null;
    }

    softReconnectRef.current = softReconnect;

    if (softReconnect) {
      stopClientOnly();
    } else {
      stopClientOnly();
      setConnected(false);
      setHello(null);
      setToolSteps([]);
      setAwaitingAgent(false);
      setAgentReplyPending(false);
      setStreaming("");
      autoSessionTried.current = false;
    }

    persistSettings();
    const ws = normalizeWsUrl(gatewayUrl);
    if (!ws) {
      connectInFlightRef.current = false;
      setStatus("invalid gateway url");
      return;
    }
    if (!token.trim()) {
      connectInFlightRef.current = false;
      setStatus("token required");
      return;
    }
    if (/REDACTED|__OPENCLAW/i.test(token)) {
      connectInFlightRef.current = false;
      setStatus(
        "Token 不能用手抄本里的占位符（如 __OPENCLAW_REDACTED__）。请在服务器执行 openclaw config get gateway.auth 复制真实 token。",
      );
      return;
    }

    setStatus(softReconnect ? "reconnecting…" : "connecting…");
    const client = new GatewayBrowserClient({
      url: ws,
      token: token.trim(),
      // 勿伪装 Control UI：公网 HTTP 下网关会要求「设备身份 + 安全上下文」，会报 1008。
      // WebChat 类客户端可用 token +（非安全上下文下的）降级握手，与官方 WebChat 文档一致。
      clientName: "webchat-ui",
      clientVersion: "gateway-chat-ui",
      mode: "webchat",
      onHello: (h) => {
        connectInFlightRef.current = false;
        wasEverConnectedRef.current = true;
        setWasEverConnected(true);
        setHello(h);
        connectedRef.current = true;
        setConnected(true);
        setStatus("connected");
        pushLog(`hello protocol=${h.protocol} server=${h.server?.version ?? "?"}`);
        if (softReconnectRef.current && sessionKey.trim()) {
          setToolSteps((p) => appendProcessStep(p, "连接已恢复，同步历史中…"));
          void refreshHistoryRef.current({ keepOnEmpty: true });
        }
        if (Array.isArray(h.auth?.scopes)) {
          pushLog(`hello scopes: ${h.auth!.scopes!.join(", ")}`);
        }
        if (h.snapshot && typeof h.snapshot === "object") {
          const snapKeys = Object.keys(h.snapshot as object).slice(0, 12).join(",");
          pushLog(`hello snapshot keys: ${snapKeys || "—"}`);
        }
      },
      onEvent: (evt: GatewayEventFrame) => {
        const activeSk = sessionKeyRef.current.trim();
        if (!eventMatchesActiveSession(evt.payload, activeSk)) return;
        const noteToolStart = (payload: unknown) => {
          const raw = JSON.stringify(payload ?? "");
          if (/lifecare__|tool|mcp/i.test(raw)) {
            toolStartedThisRunRef.current = true;
            // ===== 时序评测：记录工具调用 =====
            const tt = turnTimingRef.current;
            if (tt) {
              if (tt.firstToolTime === null) {
                tt.firstToolTime = Date.now();
              }
              const toolName = extractToolName(payload);
              if (toolName && !activeToolsRef.current.has(toolName)) {
                activeToolsRef.current.set(toolName, Date.now());
              }
            }
            // ===== 时序评测结束 =====
            queueMicrotask(() => {
              tryPinSkipIntakeEntryAckRef.current();
              tryEarlyFlushAckRef.current();
            });
          }
        };
        const appendStream = (payload: unknown) => {
          if (warmupInFlightRef.current) return;
          const piece = extractTextFromChatEvent(payload);
          const think = extractThinkingDelta(payload);
          if (think) {
            const t = think.trim();
            if (t.length > 0) {
              setToolSteps((p) => appendProcessStep(p, `[思考] ${t.slice(0, 160)}${t.length > 160 ? "…" : ""}`));
            }
          }
          if (piece) {
            // ===== 时序评测：首次收到 assistant 文本时记录 TTFT =====
            const tt = turnTimingRef.current;
            if (tt && tt.firstTextTime === null) {
              tt.firstTextTime = Date.now();
            }
            // ===== 时序评测结束 =====
            setStreaming((prev) => {
              let n = mergeStreamText(prev, piece);
              n = stripLeadingAssistantPlaceholders(n);
              if (isLocationBootstrapGreeting(n)) {
                streamingRef.current = "";
                return "";
              }
              streamingRef.current = n;
              return n;
            });
            queueMicrotask(() => {
              tryPinSkipIntakeEntryAckRef.current();
              tryEarlyFlushAckRef.current();
            });
          }
        };
        if (evt.event === "chat" || evt.event === "session.message") {
          if (!warmupInFlightRef.current) {
            noteToolStart(evt.payload);
            setToolSteps((p) => appendToolTimeline(p, evt, seenToolsThisRunRef.current));
            if (toolEventUsedSearchPlaces(evt.payload)) {
              hadSearchPlacesRef.current = true;
            }
          }
          extractRunId(evt.payload);
          const chatState = getChatEventState(evt.payload);
          if (chatState === "final" || chatState === "aborted" || chatState === "error") {
            if (warmupInFlightRef.current) {
              finishWarmupRunRef.current(sessionKey.trim());
              stopHistoryPollRef.current();
              void refreshHistoryRef.current({ keepOnEmpty: true });
              return;
            }
            // ===== 时序评测：记录本轮结束时间 =====
            const tt = turnTimingRef.current;
            if (tt && tt.endTime === null) {
              tt.endTime = Date.now();
              // 结算所有未完成的工具调用
              for (const [name, startTime] of activeToolsRef.current.entries()) {
                tt.toolCalls.push({ name, startTime, endTime: Date.now() });
              }
            }
            // ===== 时序评测结束 =====
            flushStreamingIntoRowsRef.current();
            if (chatState === "final") {
              window.setTimeout(() => {
                const snap = rowsRef.current;
                for (let i = snap.length - 1; i >= 0; i--) {
                  const r = snap[i]!;
                  if (String(r.role).toLowerCase() !== "assistant") continue;
                  if (isPlanMessage(r.text) && shouldAllowItineraryImageForRows(snap)) {
                    imageGenSuppressedRef.current = false;
                  }
                  break;
                }
                if (!awaitingAgentRef.current && !imageGenSuppressedRef.current) {
                  tryTriggerItineraryImageFromRowsRef.current();
                }
              }, 80);
            }
            toolStartedThisRunRef.current = false;
            setAckFlushedTick((t) => t + 1);
            setAwaitingAgent(false);
            setAgentReplyPending(false);
            stopHistoryPollRef.current();
            void refreshHistoryRef.current({ keepOnEmpty: true });
            // ===== 时序评测：延迟持久化，等 rows 更新完成 =====
            if (tt) {
              const sk = sessionKey.trim();
              window.setTimeout(() => {
                const snapshot = rowsRef.current;
                let lastUser: ChatRow | undefined;
                let lastAssistant: ChatRow | undefined;
                for (let i = snapshot.length - 1; i >= 0; i--) {
                  const r = snapshot[i]!;
                  if (!lastAssistant && String(r.role).toLowerCase() === "assistant") lastAssistant = r;
                  if (!lastUser && String(r.role).toLowerCase() === "user") { lastUser = r; break; }
                }
                if (lastUser && lastAssistant) {
                  void persistTurnLog(sk, lastUser, lastAssistant);
                }
                turnTimingRef.current = null;
              }, 200);
            }
            // ===== 时序评测结束 =====
            return;
          }
          appendStream(evt.payload);
          return;
        }
        if (evt.event === "agent") {
          if (!warmupInFlightRef.current) {
            noteToolStart(evt.payload);
            setToolSteps((p) => appendToolTimeline(p, evt, seenToolsThisRunRef.current));
            if (toolEventUsedSearchPlaces(evt.payload)) {
              hadSearchPlacesRef.current = true;
            }
          }
          if (warmupInFlightRef.current && evt.payload && typeof evt.payload === "object") {
            const p = evt.payload as Record<string, unknown>;
            const stream = typeof p.stream === "string" ? p.stream : "";
            const data = p.data && typeof p.data === "object" ? (p.data as Record<string, unknown>) : null;
            if (stream === "lifecycle" && data && String(data.phase ?? "") === "end") {
              finishWarmupRunRef.current(sessionKey.trim());
              return;
            }
          }
          appendStream(evt.payload);
          return;
        }
        if (evt.event === "tick" || evt.event === "presence" || evt.event === "health") return;
        noteToolStart(evt.payload);
        if (toolEventUsedSearchPlaces(evt.payload)) {
          hadSearchPlacesRef.current = true;
        }
        setToolSteps((p) => appendToolTimeline(p, evt, seenToolsThisRunRef.current));
        pushLog(`event ${evt.event} ${JSON.stringify(evt.payload ?? "").slice(0, 400)}`);
      },
      onClose: ({ code, reason, error }) => {
        connectInFlightRef.current = false;
        connectedRef.current = false;
        const extra = error ? ` ${error.code}: ${error.message}` : "";
        const mixed =
          code === 1006 && insecureWsFromSecurePage(ws)
            ? " · 若本页是 HTTPS：浏览器会拦截 ws://（混合内容），请改用 http://… 打开本页，或为 18789 配 wss 反代"
            : "";
        const raw = `closed ${code} ${reason}${extra}${mixed}`;
        pushLog(`close ${raw}`);
        if (compactUi && autoConnect && appEnabled) {
          setConnected(false);
          setHello(null);
          setStatus(mobileShell && !wasEverConnectedRef.current ? "disconnected" : "disconnected");
          if (autoReconnectTimerRef.current == null) {
            autoReconnectTimerRef.current = window.setTimeout(() => {
              autoReconnectTimerRef.current = null;
              connect(true);
            }, 2500);
          }
        } else {
          setConnected(false);
          setHello(null);
          setStatus(raw);
        }
      },
    });
    clientRef.current = client;
    client.start();
  }, [appEnabled, gatewayUrl, persistSettings, pushLog, sessionKey, stopClientOnly, token]);

  useEffect(() => {
    if (!connected || sessionKey.trim()) {
      if (!connected) autoSessionTried.current = false;
      return;
    }
    if (!hello) return;
    if (!envStr("VITE_DEFAULT_SESSION_KEY")) {
      return;
    }
    if (autoSessionTried.current) return;
    const c = clientRef.current;
    if (!c?.connected) return;
    autoSessionTried.current = true;

    let cancelled = false;
    void (async () => {
      try {
        const key = await pickSessionKeyAfterConnect(c, hello, pushLog);
        if (cancelled) return;
        if (key) {
          setSessionKey(key);
          localStorage.setItem("gw.session", key);
          pushLog(`auto: picked sessionKey=${key.length > 56 ? `${key.slice(0, 52)}…` : key}`);
          try {
            const hist = await c.request("chat.history", { sessionKey: key });
            if (cancelled) return;
            const { sessionKey: sk, rows: next } = extractHistoryRows(hist);
            setRows(next);
            if (sk && sk !== key) setSessionKey(sk);
            setStatus(`ready · ${next.length} history rows`);
          } catch (he) {
            setStatus(`connected · session ok, history: ${formatRpcError(he)}`);
          }
        } else {
          setStatus(
            import.meta.env.VITE_COMPACT_UI === "true"
              ? "connected · 未能自动推断 session（URL 加 ?session=… 或设置 VITE_DEFAULT_SESSION_KEY；亦可点 Discover；开 VITE_SHOW_DEBUG 看 auto: 日志）"
              : "connected · could not resolve session key (see debug log)",
          );
        }
      } catch (e) {
        pushLog(`auto: pickSession ${formatRpcError(e)}`);
        setStatus(`connected · auto session: ${formatRpcError(e)}`);
      }
    })();
    return () => {
      cancelled = true;
      autoSessionTried.current = false;
    };
  }, [connected, sessionKey, hello, pushLog]);

  const logLocationTiming = useCallback(
    (prefix: string, timing: { totalMs: number; ipMs: number; browserMs: number; regeoMs: number; secureContext: boolean }) => {
      pushLog(
        `${prefix}: ${timing.totalMs}ms (ip ${timing.ipMs}ms, geo ${timing.browserMs}ms, regeo ${timing.regeoMs}ms, https=${timing.secureContext})`,
      );
    },
    [pushLog],
  );

  const applyResolvedLocation = useCallback(
    (loc: ResolvedLocation, timingLabel: string, timing?: Parameters<typeof logLocationTiming>[1]) => {
      setResolvedLocation(loc);
      storeLocationSnapshot(loc);
      setLocationRefreshFailed(false);
      setLocationError("");
      if (timing) logLocationTiming(`${timingLabel} ${loc.summary} (${loc.source})`, timing);
      else pushLog(`${timingLabel} ${loc.summary} (${loc.source})`);
    },
    [logLocationTiming, pushLog],
  );

  const refreshUserLocation = useCallback(
    async (opts?: { silent?: boolean }): Promise<ResolvedLocation | null> => {
      if (locationRefreshInFlightRef.current) return null;
      locationRefreshInFlightRef.current = true;
      if (!opts?.silent) setLocationBusy(true);
      try {
        const { loc, timing } = await resolveUserLocationTimed();
        if (loc) {
          applyResolvedLocation(loc, opts?.silent ? "location refresh" : "location", timing);
          return loc;
        }
        setLocationRefreshFailed(true);
        if (!opts?.silent) {
          pushLog("location: resolve returned empty (check HTTPS + 定位权限 + /api/client-context)");
        }
        return null;
      } catch (e) {
        setLocationRefreshFailed(true);
        if (!opts?.silent) {
          pushLog(`location refresh error: ${e instanceof Error ? e.message : String(e)}`);
        }
        return null;
      } finally {
        locationRefreshInFlightRef.current = false;
        if (!opts?.silent) setLocationBusy(false);
      }
    },
    [applyResolvedLocation, pushLog],
  );

  const handleLocationAgree = useCallback(async () => {
    setLocationBusy(true);
    setLocationError("");
    // 先授权并触发 autoConnect，定位在后台拉取（与 Web 端一致，不阻塞 Gateway 握手）
    storeLocationConsent();
    setLocationConsent("granted");
    try {
      const loc = await refreshUserLocation();
      if (!loc) {
        setLocationError("未能获取位置（规划仍可继续，稍后可重试）。");
      }
    } catch (e) {
      setLocationError(e instanceof Error ? e.message : String(e));
    } finally {
      setLocationBusy(false);
    }
  }, [refreshUserLocation]);

  const handleLocationDeny = useCallback(() => {
    setLocationConsent("denied");
    setLocationError("");
    disconnect();
  }, [disconnect]);

  const markWarmupDone = useCallback((sk: string) => {
    if (!sk) return;
    warmupDoneSessions.current.add(sk);
    warmupStateRef.current = "done";
    warmupInFlightRef.current = false;
    warmupPromiseRef.current = null;
    warmupResolveRef.current?.();
    warmupResolveRef.current = null;
  }, []);

  const startSessionWarmup = useCallback(async () => {
    const sk = sessionKey.trim();
    if (!sk || !appEnabled) return;
    markWarmupDone(sk);
  }, [appEnabled, markWarmupDone, sessionKey]);

  const ensureWarmupComplete = useCallback(async () => {
    const sk = sessionKey.trim();
    if (!sk || warmupDoneSessions.current.has(sk)) return;
    markWarmupDone(sk);
  }, [markWarmupDone, sessionKey]);

  useEffect(() => {
    startSessionWarmupRef.current = () => void startSessionWarmup();
    ensureWarmupCompleteRef.current = ensureWarmupComplete;
  }, [ensureWarmupComplete, startSessionWarmup]);

  useEffect(() => {
    finishWarmupRunRef.current = (sk) => markWarmupDone(sk);
  }, [markWarmupDone]);

  useEffect(() => {
    const sk = sessionKey.trim();
    warmupInFlightRef.current = false;
    warmupPromiseRef.current = null;
    warmupResolveRef.current?.();
    warmupResolveRef.current = null;
    warmupStateRef.current = sk && warmupDoneSessions.current.has(sk) ? "done" : "idle";
    if (sk && appEnabled && connected) {
      void startSessionWarmup();
    }
  }, [appEnabled, connected, sessionKey, startSessionWarmup]);

  useEffect(() => {
    if (!autoConnect) return;
    if (!appEnabled) return;
    if (autoConnectDone.current) return;
    const ws = normalizeWsUrl(gatewayUrl);
    if (!ws || !token.trim()) return;
    if (insecureWsFromSecurePage(ws)) {
      autoConnectDone.current = true;
      setStatus(
        "已取消自动连接：当前为 HTTPS 安全页，浏览器会拦截 ws://（混合内容）。请用 http://公网IP:端口 打开本页，或将网关暴露为 wss:// 与页面同源。",
      );
      return;
    }
    autoConnectDone.current = true;
    const t = window.setTimeout(() => connect(), 0);
    return () => window.clearTimeout(t);
  }, [connect, gatewayUrl, token, appEnabled]);

  const sendMessage = useCallback(
    async (
      text: string,
      opts?: {
        displayText?: string;
        hideVisibleUser?: boolean;
        intakeSkipped?: boolean;
        userAlreadyShown?: boolean;
      },
    ) => {
      const c = clientRef.current;
      let msg = text.trim();
      let userVisible = (opts?.displayText ?? msg).trim();
      if (!appEnabled || !c?.connected || !msg) return;
      if (isLocationContextMessage(msg)) return;
      if (isWarmupMessage(msg)) return;
      const sk = sessionKeyRef.current.trim();
      if (!sk) {
        setStatus("session key required");
        return;
      }
      if (!opts?.hideVisibleUser) {
        const tagged = stripEvalTaskTag(msg);
        if (tagged.taskId) {
          evalTaskIdRef.current = tagged.taskId;
          msg = tagged.text;
          userVisible = stripEvalTaskTag(userVisible).text;
          setThreads((prev) => {
            const next = prev.map((t) =>
              t.id === activeThreadId ? { ...t, title: tagged.taskId!, updatedAt: Date.now() } : t,
            );
            saveThreads(next);
            return next;
          });
        }
      }
      evalTurnIndexRef.current += 1;
      if (evalTurnIndexRef.current === 1) {
        void logEvalEvent("session_start", {
          taskId: evalTaskIdRef.current,
          modelId: currentModelIdRef.current,
        });
      }
      cancelItineraryImageGenRef.current({ userFollowUp: true });
      hadSearchPlacesRef.current = false;
      historyHadSearchRef.current = false;
      seenToolsThisRunRef.current = new Set();
      ackFlushedThisRunRef.current = false;
      ackTextThisRunRef.current = "";
      if (opts?.intakeSkipped) {
        skipIntakeAckIdRef.current = `a-skip-intake-ack-${Date.now().toString(36)}`;
      } else {
        skipIntakeAckIdRef.current = null;
      }
      toolStartedThisRunRef.current = false;
      // ===== 时序评测：记录本轮开始时间 =====
      const sendTime = Date.now();
      turnTimingRef.current = {
        sendTime,
        firstTextTime: null,
        firstToolTime: null,
        endTime: null,
        toolCalls: [],
      };
      activeToolsRef.current = new Map();
      // ===== 时序评测结束 =====
      setAckFlushedTick((t) => t + 1);
      const idem = newIdempotencyKey();

      if (
        !opts?.hideVisibleUser &&
        appEnabled &&
        resolvedLocation &&
        shouldInjectLocationPrefix(resolvedLocation, sk, lastInjectedLocationKeyRef.current)
      ) {
        msg = mergeLocationPrefix(resolvedLocation, msg);
      }

      optimisticUserRef.current = msg;
      if (!opts?.hideVisibleUser && !opts?.userAlreadyShown) {
        const userRow: ChatRow = {
          role: "user",
          text: userVisible,
          id: `u-${idem}`,
          timestamp: sendTime,
        };
        setPendingUserDisplay({ id: userRow.id, text: userVisible });
        setRows((r) => {
          const next = [...r, userRow];
          rowsRef.current = next;
          return next;
        });
      }
      setStreaming("");
      setAwaitingAgent(true);
      setAgentReplyPending(true);
      setMinThinkingUntil(Date.now() + 750);
      setThinkingUiTick((n) => n + 1);
      setToolSteps(() =>
        appendProcessStep(
          [],
          isIntakeSubmissionText(msg)
            ? "正在提交选项…"
            : "正在发送，Agent 将生成选择题或方案…",
        ),
      );
      setStatus("sending…");

      const streamBuf = streamingRef.current.trim();
      if (streamBuf) {
        setRows((prev) => {
          const last = prev[prev.length - 1];
          if (last && String(last.role).toLowerCase() === "assistant" && last.text === streamBuf) {
            return prev;
          }
          return [...prev, { role: "assistant", text: streamBuf, id: `a-flush-${idem}` }];
        });
      }

      setToolSteps((p) =>
        appendProcessStep(
          p,
          isIntakeSubmissionText(msg)
            ? "已提交选项，Agent 正在规划路线并调用工具…"
            : "消息已发送，Agent 正在回复（补槽 / 调工具 / 生成方案）…",
        ),
      );
      void logEvalEvent("user_sent", {
        text: userVisible.slice(0, 500),
        timestamp: sendTime,
        hidden: !!opts?.hideVisibleUser,
        isIntakeSubmission: isIntakeSubmissionText(msg),
      });
      try {
        const ack = await c.request("chat.send", {
          sessionKey: sk,
          message: msg,
          idempotencyKey: idem,
        });
        pushLog(`chat.send ack → ${JSON.stringify(ack)}`);
        if (
          !opts?.hideVisibleUser &&
          resolvedLocation &&
          isLocationContextMessage(msg)
        ) {
          lastInjectedLocationKeyRef.current.set(sk, locationSnapshotKey(resolvedLocation));
        }
        void notifyHarnessUserMessage(sk, msg, {
          intakeSkipped: !!opts?.intakeSkipped,
        });
        setStatus("connected · sent");
        setThreads((prev) => {
          if (!activeThreadId) return prev;
          const next = prev.map((t) => {
            if (t.id !== activeThreadId) return t;
            // 标题取「可见用户首句」(userVisible 在合并位置前缀之前生成)，
            // 不能用 msg：msg 可能已被 mergeLocationPrefix 前置「[位置上下文]…」。
            // 隐藏注入 / 选择题提交载荷不参与命名。
            const short = userVisible.replace(/\s+/g, " ").slice(0, 28);
            const isDefault = t.title === "新对话" || /^对话 \d+$/.test(t.title);
            const useShort =
              isDefault && !!short && !opts?.hideVisibleUser && !isIntakeSubmissionText(msg);
            return { ...t, title: useShort ? short : t.title, updatedAt: Date.now() };
          });
          saveThreads(next);
          return next;
        });
        startHistoryPoll();
      } catch (e) {
        setAwaitingAgent(false);
        setAgentReplyPending(false);
        const err = `发送失败：${formatRpcError(e)}`;
        setStatus(err);
        if (mobileShell) setMobileNotice(err);
      }
    },
    [
      activeThreadId,
      appEnabled,
      logEvalEvent,
      pushLog,
      resolvedLocation,
      sessionKey,
      startHistoryPoll,
    ],
  );

  const clearIntakeUi = useCallback(() => {
    setIntakeSelections({});
    setIntakeCustom({});
    setIntakeFollowUp({});
    setFrozenIntake(null);
    setFrozenIntakeIntro("");
    setIntakeSubmitted(false);
    setIntakeViaFreetext(false);
    setSubmittedIntake(null);
    setIntakeUnlockedForNewTrip(false);
    setSupersededIntake(null);
    intakeUnlockAppliedRef.current = "";
    setIntakeAnchorUserId(null);
  }, []);

  const lockIntakeSnapshot = useCallback(
    (snapshot: IntakeSubmittedSnapshot, viaFreetext: boolean) => {
      setSubmittedIntake(snapshot);
      setFrozenIntake(snapshot.blocks);
      setIntakeSelections(snapshot.selections);
      setIntakeCustom(snapshot.custom);
      setIntakeFollowUp(snapshot.followUp);
      setIntakeSubmitted(true);
      setIntakeViaFreetext(viaFreetext);
      setIntakeUnlockedForNewTrip(false);
      setSupersededIntake(null);
      setIntakeAnchorUserId((prev) => {
        if (prev) return prev;
        for (let i = rows.length - 1; i >= 0; i--) {
          const r = rows[i]!;
          if (String(r.role).toLowerCase() === "user" && !isIntakeSubmissionText(r.text)) return r.id;
        }
        return prev;
      });
    },
    [rows],
  );

  const sendDefaultIntake = useCallback(async () => {
    const blocks = frozenIntake ?? intakeBlocks;
    if (blocks.length) {
      lockIntakeSnapshot(
        {
          blocks,
          selections: { ...intakeSelections },
          custom: { ...intakeCustom },
          followUp: { ...intakeFollowUp },
        },
        false,
      );
    } else {
      setIntakeSubmitted(true);
      setIntakeViaFreetext(false);
      setIntakeUnlockedForNewTrip(false);
      setSupersededIntake(null);
    }
    await sendMessage("全部用默认（城市默认坐标、半天、2成人、不忌口、地铁+打车）", { hideVisibleUser: true });
  }, [
    frozenIntake,
    intakeBlocks,
    intakeCustom,
    intakeFollowUp,
    intakeSelections,
    lockIntakeSnapshot,
    sendMessage,
  ]);

  const submitIntakeChoices = useCallback(async () => {
    const blocks = frozenIntake ?? intakeBlocks;
    if (!intakeAnswerComplete(blocks, intakeSelections, intakeCustom, intakeFollowUp)) return;
    const selections = { ...intakeSelections };
    const custom = { ...intakeCustom };
    const followUp = { ...intakeFollowUp };
    const apiText = formatIntakeSubmission(blocks, selections, custom, followUp);
    lockIntakeSnapshot({ blocks, selections, custom, followUp }, false);
    await sendMessage(apiText, { hideVisibleUser: true });
  }, [frozenIntake, intakeBlocks, intakeCustom, intakeFollowUp, intakeSelections, lockIntakeSnapshot, sendMessage]);

  const abort = useCallback(async () => {
    const c = clientRef.current;
    if (!c?.connected || !sessionKey.trim()) return;
    try {
      await c.request("chat.abort", { sessionKey: sessionKey.trim() });
      setStatus("aborted");
    } catch (e) {
      setStatus(`chat.abort failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  }, [sessionKey]);

  const switchThread = useCallback(
    (threadId: string) => {
      const t = threads.find((x) => x.id === threadId);
      if (!t) return;
      if (threadId === activeThreadId && !historyLoading) return;
      const oldSk = sessionKey.trim();
      if (oldSk && oldSk !== t.sessionKey) {
        void detachInactiveSession(oldSk);
      }
      stopHistoryPoll();
      historyLoadGen.current += 1;
      lastHistorySessionRef.current = "";
      setStreaming("");
      setAwaitingAgent(false);
      setAgentReplyPending(false);
      setToolSteps([]);
      warmupInFlightRef.current = false;
      warmupPromiseRef.current = null;
      warmupResolveRef.current?.();
      warmupResolveRef.current = null;
      warmupStateRef.current = "idle";
      clearIntakeUi();
      optimisticUserRef.current = null;
      setPendingUserDisplay(null);
      rowsRef.current = [];
      imageGenSuppressedRef.current = false;
      lastImagePlanFpRef.current = "";
      setActiveThreadId(threadId);
      localStorage.setItem(ACTIVE_THREAD_LS, threadId);
      localStorage.setItem("gw.session", t.sessionKey);
      setSessionKey(t.sessionKey);
      setRows([]);
    },
    [activeThreadId, clearIntakeUi, detachInactiveSession, historyLoading, sessionKey, threads, stopHistoryPoll],
  );

  const createNewThread = useCallback(
    async (opts?: { preserveChat?: boolean }) => {
      if (createThreadPromiseRef.current) {
        return createThreadPromiseRef.current;
      }

      const run = async () => {
        const c = clientRef.current;
        if (!c?.connected) {
          pendingNewThreadRef.current = true;
          setStatus("连接中，连接成功后将自动新建对话…");
          connect();
          const linked = await waitUntil(12000, () => connectedRef.current && !!clientRef.current?.connected);
          if (!linked) return;
        }
        pendingNewThreadRef.current = false;
        setCreatingThread(true);
        const oldSk = sessionKey.trim();
        if (oldSk) {
          await detachInactiveSession(oldSk);
        }
        stopHistoryPoll();
        setStreaming("");
        if (!opts?.preserveChat && !rowsRef.current.some((r) => isVisibleUserRow(r))) {
          optimisticUserRef.current = null;
          setPendingUserDisplay(null);
          clearIntakeUi();
          rowsRef.current = [];
          setRows([]);
        }
        warmupInFlightRef.current = false;
        warmupPromiseRef.current = null;
        warmupResolveRef.current?.();
        warmupResolveRef.current = null;
        warmupStateRef.current = "idle";
        try {
          const client = clientRef.current;
          if (!client?.connected) return;
          const newKey = await allocateWebchatSessionKey(client, pushLog, {
            label: `webchat-${getOrCreateDeviceId().slice(0, 24)}-${new Date().toISOString().slice(0, 16)}`,
          });
          const id = "t-" + Date.now().toString(36);
          const snapModelId = currentModelIdRef.current;
          const nt: ChatThread = {
            id,
            sessionKey: newKey,
            title: "新对话",
            updatedAt: Date.now(),
            modelId: snapModelId,
          };
          historyLoadGen.current += 1;
          lastHistorySessionRef.current = "";
          setThreads((prev) => {
            const merged = [...prev, nt];
            saveThreads(merged);
            return merged;
          });
          setActiveThreadId(id);
          localStorage.setItem(ACTIVE_THREAD_LS, id);
          localStorage.setItem("gw.session", newKey);
          setSessionKey(newKey);
          sessionKeyRef.current = newKey.trim();
          if (!opts?.preserveChat) {
            setRows([]);
            rowsRef.current = [];
          }
          evalTurnIndexRef.current = 0;
          intakeShownLoggedRef.current = false;
          intakeSubmittedLoggedRef.current = false;
          lastToolProgressCountRef.current = 0;
          imageGenStartRef.current = null;
          imageGenSuppressedRef.current = false;
          lastImagePlanFpRef.current = "";
          setStatus("已新建对话");
          void logEvalEvent("session_start", {
            taskId: evalTaskIdRef.current,
            newThread: true,
            modelId: snapModelId,
          });
        } catch (e) {
          pushLog(`createNewThread ${formatRpcError(e)}`);
          setStatus(`新建对话失败：${formatRpcError(e)}`);
          if (mobileShell) setMobileNotice(`新建对话失败：${formatRpcError(e)}`);
        } finally {
          setCreatingThread(false);
        }
      };

      const p = run();
      createThreadPromiseRef.current = p;
      try {
        await p;
      } finally {
        if (createThreadPromiseRef.current === p) {
          createThreadPromiseRef.current = null;
        }
      }
    },
    [clearIntakeUi, connect, detachInactiveSession, logEvalEvent, mobileShell, pushLog, sessionKey, stopHistoryPoll],
  );

  const ensureGatewayConnected = useCallback(async (): Promise<boolean> => {
    if (connectedRef.current && clientRef.current?.connected) return true;
    if (!connectInFlightRef.current) connect();
    let ok = await waitUntil(12000, () => connectedRef.current && !!clientRef.current?.connected);
    if (ok) return true;
    connectInFlightRef.current = false;
    if (autoReconnectTimerRef.current != null) {
      window.clearTimeout(autoReconnectTimerRef.current);
      autoReconnectTimerRef.current = null;
    }
    connect();
    ok = await waitUntil(8000, () => connectedRef.current && !!clientRef.current?.connected);
    return ok;
  }, [connect]);

  const sendUserText = useCallback(
    async (rawText: string) => {
      const text = rawText.trim();
      if (!text || !appEnabled) return;

      const bumpNotice = (msg: string) => {
        setStatus(msg);
        if (mobileShell) setMobileNotice(msg);
      };

      const idem = newIdempotencyKey();
      const userId = `u-${idem}`;
      const userVisible = text;

      setPendingUserDisplay({ id: userId, text: userVisible });
      setRows((r) => {
        const next: ChatRow[] = [
          ...r,
          { role: "user", text: userVisible, id: userId, timestamp: Date.now() },
        ];
        rowsRef.current = next;
        return next;
      });

      if (!connectedRef.current || !clientRef.current?.connected) {
        bumpNotice("正在连接服务器…");
        const linked = await ensureGatewayConnected();
        if (!linked) {
          bumpNotice("连接失败，请刷新页面后重试");
          return;
        }
      }

      let sk = sessionKeyRef.current.trim();
      if (!sk) {
        bumpNotice("正在创建对话…");
        await createNewThread({ preserveChat: true });
        await waitUntil(15000, () => !!sessionKeyRef.current.trim());
        sk = sessionKeyRef.current.trim();
        if (!sk) {
          bumpNotice("会话未就绪，请稍后再试");
          return;
        }
      }

      if (mobileShell) setMobileNotice("");

      const blocks = frozenIntake ?? intakeBlocks;
      const intakeOpen =
        !intakeLocked &&
        blocks.length > 0 &&
        !intakeAnswerComplete(blocks, intakeSelections, intakeCustom, intakeFollowUp);
      if (intakeOpen) {
        lockIntakeSnapshot({ blocks, selections: {}, custom: {}, followUp: {} }, true);
        await sendMessage(text, {
          intakeSkipped: true,
          userAlreadyShown: true,
          displayText: userVisible,
        });
        return;
      }
      await sendMessage(text, { userAlreadyShown: true, displayText: userVisible });
    },
    [
      appEnabled,
      createNewThread,
      ensureGatewayConnected,
      frozenIntake,
      intakeBlocks,
      intakeCustom,
      intakeFollowUp,
      intakeLocked,
      intakeSelections,
      lockIntakeSnapshot,
      mobileShell,
      sendMessage,
    ],
  );

  const send = useCallback(async () => {
    const text = draft.trim();
    if (!text || !appEnabled) return;
    setDraft("");
    await sendUserText(text);
  }, [appEnabled, draft, sendUserText]);

  const clearAllLocalHistory = useCallback(() => {
    stopHistoryPoll();
    historyLoadGen.current += 1;
    lastHistorySessionRef.current = "";
    clearLocalChatStorage();
    clearIntakeUi();
    setThreads([]);
    setActiveThreadId("");
    setPendingUserDisplay(null);
    setRows([]);
    setSessionKey("");
    setStreaming("");
    setToolSteps([]);
    setAwaitingAgent(false);
    optimisticUserRef.current = null;
    if (clientRef.current?.connected) {
      void createNewThread();
    } else {
      setStatus("已清空本机记录，连接后将自动新建专属会话");
    }
  }, [clearIntakeUi, createNewThread, stopHistoryPoll]);

  useEffect(() => {
    if (!connected || !hello) return;
    if (pendingNewThreadRef.current) {
      pendingNewThreadRef.current = false;
      void createNewThread();
      return;
    }
    if (threads.length > 0 || sessionKey.trim()) return;
    if (firstSessionCreating.current) return;
    firstSessionCreating.current = true;
    void createNewThread({ preserveChat: rowsRef.current.some((r) => isVisibleUserRow(r)) }).finally(() => {
      firstSessionCreating.current = false;
    });
  }, [connected, hello, threads.length, sessionKey, createNewThread]);

  useEffect(() => {
    if (!connected || !sessionKey.trim()) return;
    const c = clientRef.current;
    if (!c?.connected) return;
    const sk = sessionKey.trim();
    void c.request("sessions.messages.subscribe", { sessionKey: sk }).catch((e) => {
      pushLog(`sessions.messages.subscribe ${formatRpcError(e)}`);
    });
    return () => {
      const cur = clientRef.current;
      if (cur?.connected) {
        void cur.request("sessions.messages.unsubscribe", { sessionKey: sk }).catch(() => {});
      }
    };
  }, [connected, sessionKey, pushLog]);

  useEffect(() => {
    if (!connected) return;
    if (!hello || !sessionKey.trim()) return;
    const sk = sessionKey.trim();
    if (lastHistorySessionRef.current === sk && rowsRef.current.length > 0) return;
    void refreshHistory({ sessionKeyOverride: sk });
  }, [connected, hello, sessionKey, refreshHistory]);

  useEffect(() => {
    if (!mobileShell || !appEnabled) return;
    if (connected) {
      setMobileNotice((m) => (m === "正在连接…" || m === "正在连接服务器…" ? "" : m));
      return;
    }
    if (status === "connecting…" || status === "reconnecting…") {
      setMobileNotice("正在连接…");
    }
  }, [mobileShell, appEnabled, connected, status]);

  useEffect(() => () => disconnect(), [disconnect]);

  const displayStatus = userFacingStatus(status, connected);
  const uiLocked = !appEnabled;
  const draftReady = draft.trim().length > 0;
  const canSendDraft = draftReady && appEnabled && connected && !creatingThread;

  const cardAnchorUserId = useMemo(
    () => sessionPlanningIntake?.anchorId ?? intakeAnchorUserId ?? findIntakeCardAnchorUserId(rows),
    [intakeAnchorUserId, rows, sessionPlanningIntake],
  );

  const intakeCardEl =
    showIntakeCard && intakeCardBlocks.length > 0 ? (
      <div className="bubble role-assistant intake-bubble-shell">
        {supersededIntake ? (
          <p className="intake-superseded-hint">上一轮选择（已作废）· 请回答下方新问卷</p>
        ) : null}
        <IntakeCard
          intro={displayIntakeIntro}
          blocks={intakeCardBlocks}
          selections={cardSelections}
          custom={intakeLocked && effectiveSubmittedIntake ? effectiveSubmittedIntake.custom : intakeCustom}
          followUp={intakeLocked && effectiveSubmittedIntake ? effectiveSubmittedIntake.followUp ?? {} : intakeFollowUp}
          locked={intakeLocked}
          grayAllOptions={intakeLocked && intakeViaFreetext}
          lockedHint={
            intakeLocked && intakeViaFreetext
              ? "问卷已锁定；您的回复见下方对话气泡"
              : undefined
          }
          showDefault={/全部用默认/.test(intakeParseText)}
          canSubmit={canSubmitIntake}
          uiLocked={uiLocked}
          onSelect={(n, letter) => {
            setIntakeSelections((prev) => ({ ...prev, [n]: letter }));
          }}
          onCustomChange={(n, value) => setIntakeCustom((prev) => ({ ...prev, [n]: value }))}
          onFollowUpChange={(n, value) => setIntakeFollowUp((prev) => ({ ...prev, [n]: value }))}
          onSubmit={() => void submitIntakeChoices()}
          onDefault={() => void sendDefaultIntake()}
        />
      </div>
    ) : null;

  const initialLocationRefreshDone = useRef(false);
  useEffect(() => {
    if (locationConsent !== "granted") return;
    if (initialLocationRefreshDone.current) return;
    initialLocationRefreshDone.current = true;
    void refreshUserLocation({ silent: Boolean(loadStoredLocationSnapshot()) });
  }, [locationConsent, refreshUserLocation]);

  useEffect(() => {
    if (!appEnabled || !connected || resolvedLocation) return;
    void refreshUserLocation({ silent: false });
  }, [appEnabled, connected, resolvedLocation, refreshUserLocation]);

  return (
    <div className={mobileShell ? "app-mobile-viewport" : undefined}>
    <div
      className={`app${compactUi ? " compact-mode" : ""}${mobileShell ? " app-mobile" : ""}${uiLocked ? " app-locked" : ""}`}
    >
      <LocationConsentModal
        open={showLocationConsent}
        busy={locationBusy}
        error={locationError}
        onAgree={() => void handleLocationAgree()}
        onDeny={handleLocationDeny}
      />
      {locationConsent === "denied" ? (
        <div className="location-denied-banner" role="alert">
          您未同意位置授权，本页功能已停用。请刷新页面后点击「同意」以继续使用。
        </div>
      ) : null}
      {mobileShell ? <MobileHeader onMenu={() => setHistoryDrawerOpen(true)} /> : null}
      {mobileShell ? (
        <HistoryDrawer
          open={historyDrawerOpen}
          threads={threads}
          activeThreadId={activeThreadId}
          creatingThread={creatingThread}
          uiLocked={uiLocked}
          onClose={() => setHistoryDrawerOpen(false)}
          onSelect={(id) => {
            setHistoryDrawerOpen(false);
            void switchThread(id);
          }}
          onNew={() => {
            setHistoryDrawerOpen(false);
            void createNewThread();
          }}
          onClear={() => {
            if (window.confirm("清空本机侧栏记录并新建专属会话？其他设备上的记录不受影响。")) {
              setHistoryDrawerOpen(false);
              void clearAllLocalHistory();
            }
          }}
        />
      ) : null}
      {!mobileShell ? (
      <header className="header">
        <h1>{compactUi ? "美团本地生活 · 出行管家" : "Gateway chat (custom layout)"}</h1>
        {appEnabled ? (
          locationBusy && !resolvedLocation ? (
            <p className="location-hint">正在获取位置…</p>
          ) : resolvedLocation ? (
            <p
              className="location-hint"
              title={
                resolvedLocation.source === "ip"
                  ? "公网 IP 定位可能偏差；问卷选 D 可更正"
                  : "浏览器 GPS + 逆地理，问卷中仍可更正"
              }
            >
              当前位置推测：{resolvedLocation.summary}
              {locationBusy ? <span className="location-hint-tag"> · 更新中</span> : null}
              {resolvedLocation.source === "ip" ? (
                <span className="location-hint-tag"> · IP 推测（热点/4G 可能不准）</span>
              ) : (
                <span className="location-hint-tag"> · 浏览器定位</span>
              )}
            </p>
          ) : locationRefreshFailed ? (
            <p className="location-hint location-hint-warn">
              未能获取位置，
              <button type="button" className="location-retry-link" onClick={() => void refreshUserLocation()}>
                点击重试
              </button>
            </p>
          ) : (
            <p className="location-hint">正在获取位置…</p>
          )
        ) : null}
        {!compactUi ? (
          <p className="sub">
            Uses <code>openclaw-ws</code> as <strong>webchat-ui</strong> (not Control UI) so{" "}
            <code>http://公网IP</code> + <code>ws://</code> works without HTTPS. Layout: edit{" "}
            <code>App.css</code>.
          </p>
        ) : null}
        {insecureWsFromSecurePage(gatewayUrl) ? (
          <p className="mixed-content-warn" role="alert">
            当前页面为 <strong>HTTPS</strong>，浏览器会阻止连接 <strong>ws://</strong>（混合内容），表现为{" "}
            <code>closed 1006</code>。请改用 <strong>http://</strong>
            同一主机打开本页，或为网关配置 <strong>wss://</strong>（如 Nginx/Caddy 反代 18789）。
          </p>
        ) : null}
        {compactUi && appEnabled && !mobileShell ? (
          <div className="model-selector">
            <select
              className="model-select"
              value={currentModelId}
              disabled={modelSwitching}
              onChange={(e) => handleSwitchModel(e.target.value)}
              title={modelSwitching ? "切换中…" : "切换 Agent LLM 模型"}
            >
              {availableModels.length === 0 ? (
                <option value="">加载中…</option>
              ) : (
                availableModels.map((m) => (
                  <option key={m.id} value={m.id}>{m.label}</option>
                ))
              )}
            </select>
            {modelSwitching ? <span className="model-switch-indicator">⏳</span> : null}
            {modelSwitchMsg ? <span className="model-switch-msg">{modelSwitchMsg}</span> : null}
          </div>
        ) : null}
      </header>
      ) : null}

      <div className="main-layout">
        {!mobileShell ? (
        <aside className="sidebar" aria-label="历史对话">
          <div className="sidebar-head">
            <span className="sidebar-title">历史对话</span>
            <div className="sidebar-head-actions">
              <button
                type="button"
                className="sidebar-new"
                onClick={() => void createNewThread()}
                disabled={creatingThread || uiLocked}
                title={connected ? "新建独立会话" : "将先连接网关，再自动新建对话"}
              >
                ＋ 新对话
              </button>
              <button
                type="button"
                className="sidebar-clear ghost"
                disabled={uiLocked}
                onClick={() => {
                  if (window.confirm("清空本机侧栏记录并新建专属会话？其他设备上的记录不受影响。")) {
                    void clearAllLocalHistory();
                  }
                }}
              >
                清空
              </button>
            </div>
          </div>
          {!compactUi ? (
            <p className="sidebar-hint">每个会话对应网关里独立的 <code>sessionKey</code>，记忆互不串线。</p>
          ) : null}
          <ul className="thread-list">
            {threads
              .slice()
              .sort((a, b) => b.updatedAt - a.updatedAt)
              .map((t) => (
                <li key={t.id}>
                  <button
                    type="button"
                    className={`thread-item${t.id === activeThreadId ? " active" : ""}`}
                    disabled={uiLocked}
                    onClick={() => switchThread(t.id)}
                    title={t.sessionKey}
                  >
                    <span className="thread-title">{t.title || "未命名"}</span>
                    {!compactUi ? (
                      <span className="thread-sub">
                        {t.modelId
                          ? `${modelLabelForId(t.modelId, availableModels) || t.modelId} · `
                          : ""}
                        {t.sessionKey.length > 36 ? `${t.sessionKey.slice(0, 32)}…` : t.sessionKey}
                      </span>
                    ) : t.modelId ? (
                      <span className="thread-sub">{modelLabelForId(t.modelId, availableModels) || t.modelId}</span>
                    ) : null}
                  </button>
                </li>
              ))}
          </ul>
        </aside>
        ) : null}

        <div className="main-col">
      {/* 开发调试面板：仅桌面非 compact；App 壳/评委模式隐藏 */}
      {!mobileShell && !compactUi ? (
        <section className="panel">
            <label>
              Gateway WebSocket URL
              <input
                value={gatewayUrl}
                onChange={(e) => setGatewayUrl(e.target.value)}
                placeholder="ws://127.0.0.1:18789 or wss://host:443"
                spellCheck={false}
              />
            </label>
            <label>
              Token（须为服务器上真实 gateway token，不能填文档里的 REDACTED 占位符）
              <input
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="在服务器: openclaw config get gateway.auth"
                autoComplete="off"
              />
            </label>
            <label>
              Session key
              <input
                value={sessionKey}
                onChange={(e) => setSessionKey(e.target.value)}
                placeholder="e.g. from Control UI / sessions.list"
                spellCheck={false}
              />
            </label>
          <div className="row">
            <button type="button" onClick={() => connect()}>
              Connect
            </button>
            <button type="button" className="ghost" onClick={disconnect}>
              Disconnect
            </button>
            <button type="button" onClick={() => void refreshHistory()} disabled={!connected}>
              Load history
            </button>
            <button type="button" className="ghost" onClick={discoverSessions} disabled={!connected}>
              Discover sessions
            </button>
            <button type="button" className="danger" onClick={abort} disabled={!connected}>
              Stop run
            </button>
          </div>
          <p className="status">
            <strong>{status}</strong>
            {connected && hello && (
              <span className="meta">
                {" "}
                · protocol {hello.protocol} · {hello.server?.version ?? "?"}
              </span>
            )}
          </p>
        </section>
      ) : !mobileShell && compactUi && displayStatus ? (
        <p className="compact-connecting" role="status">
          {displayStatus}
        </p>
      ) : null}

      <main className="chat">
        <div className="stream" ref={streamScrollRef}>
          {(() => {
            type StreamItem =
              | { kind: "bubble"; key: string; node: ReactNode }
              | { kind: "intake-card"; key: string; node: ReactNode }
              | { kind: "pending-user"; key: string; node: ReactNode }
              | { kind: "thinking"; key: string; node: ReactNode }
              | { kind: "extras"; key: string; node: ReactNode };

            const items: StreamItem[] = [];
            let cardInserted = false;
            let lastUserBubbleKey: string | null = null;

            const pushIntakeCard = () => {
              if (!intakeCardEl || cardInserted) return;
              items.push({ kind: "intake-card", key: "intake-card", node: intakeCardEl });
              cardInserted = true;
            };

            for (const r of displayRows) {
              const rl = String(r.role).toLowerCase();
              if (isHiddenChatRow(rl, r.text)) continue;
              if (rl === "assistant" && isNoiseAssistantBubble(r.text)) continue;
              if (rl === "assistant" && isIntakeQuestionBubble(r.text)) continue;
              if (
                rl === "assistant" &&
                intakePhasePending &&
                !hasIntakeQuestions(extractIntakeOnlyText(r.text))
              ) {
                continue;
              }

              const userBubbleText =
                rl === "user" ? extractUserVisibleTextFromMessage(r.text) : r.text;
              if (rl === "user" && !userBubbleText.trim()) continue;
              if (rl === "user") lastUserBubbleKey = r.id;

              const isPlan = rl === "assistant" && isPlanMessage(r.text);

              items.push({
                kind: "bubble",
                key: r.id,
                node: (
                  <div className={`bubble-row ${rl === "user" ? "bubble-row-user" : "bubble-row-assistant"}`}>
                    <div
                      className={`bubble role-${rl}${mobileShell && isPlan ? " bubble-plan" : ""}`}
                    >
                      {!mobileShell && rl !== "user" ? <div className="role">{rl}</div> : null}
                      <MarkdownErrorBoundary text={userBubbleText}>
                        {mobileShell && isPlan ? (
                          <PlanMessageBody
                            text={userBubbleText}
                            pois={sessionPois}
                            userLocation={resolvedLocation}
                          />
                        ) : (
                          <BubbleMarkdown text={userBubbleText} />
                        )}
                      </MarkdownErrorBoundary>
                    </div>
                  </div>
                ),
              });

              if (mobileShell && isPlan) {
                items.push({
                  kind: "extras",
                  key: `${r.id}-map`,
                  node: (
                    <RouteMapPreview
                      pois={sessionPois}
                      userLng={resolvedLocation?.lng}
                      userLat={resolvedLocation?.lat}
                    />
                  ),
                });
              }

              // 兜底：方案检测没命中，但会话里已有带坐标 POI，仍挂出地图
              if (
                mobileShell &&
                !isPlan &&
                rl === "assistant" &&
                r.id === lastVisibleAssistantRowId &&
                sessionPois.some((p) => p.location) &&
                userBubbleText.trim().length >= 400
              ) {
                items.push({
                  kind: "extras",
                  key: `${r.id}-map-fallback`,
                  node: (
                    <RouteMapPreview
                      pois={sessionPois}
                      userLng={resolvedLocation?.lng}
                      userLat={resolvedLocation?.lat}
                    />
                  ),
                });
              }

              if (
                mobileShell &&
                rl === "assistant" &&
                r.id === lastVisibleAssistantRowId &&
                !awaitingAgent &&
                !intakeActive
              ) {
                items.push({
                  kind: "extras",
                  key: `${r.id}-chips`,
                  node: (
                    <FollowUpChips
                      disabled={uiLocked || !connected}
                      onPick={(text) => void sendUserText(text)}
                    />
                  ),
                });
              }

              if (rl === "user" && cardAnchorUserId != null && cardAnchorUserId === r.id) {
                pushIntakeCard();
              }
            }

            if (intakeCardEl && !cardInserted) {
              const anchorBubbleIdx = items.findIndex(
                (it) => it.kind === "bubble" && it.key === cardAnchorUserId,
              );
              const cardItem: StreamItem = { kind: "intake-card", key: "intake-card", node: intakeCardEl };
              if (anchorBubbleIdx >= 0) {
                items.splice(anchorBubbleIdx + 1, 0, cardItem);
              } else {
                items.push(cardItem);
              }
              cardInserted = true;
            }

            if (
              pendingUserDisplay &&
              !displayRows.some((r) => r.id === pendingUserDisplay.id)
            ) {
              lastUserBubbleKey = pendingUserDisplay.id;
              items.push({
                kind: "pending-user",
                key: pendingUserDisplay.id,
                node: (
                  <div className="bubble-row bubble-row-user">
                    <div className="bubble role-user">
                      <MarkdownErrorBoundary text={pendingUserDisplay.text}>
                        <BubbleMarkdown text={pendingUserDisplay.text} />
                      </MarkdownErrorBoundary>
                    </div>
                  </div>
                ),
              });
            }

            if (wantMobileThinking) {
              const thinkingItem: StreamItem = {
                kind: "thinking",
                key: "thinking-live",
                node: (
                  <div className="bubble-row bubble-row-assistant">
                    <ThinkingBubble
                      main={thinkingDisplay.main}
                      sub={thinkingDisplay.sub}
                      visible={wantMobileThinking}
                    />
                  </div>
                ),
              };
              let insertAt = items.length;
              if (cardInserted && intakeLocked) {
                const cardIdx = items.findIndex((it) => it.kind === "intake-card");
                if (cardIdx >= 0) insertAt = cardIdx + 1;
              } else if (lastUserBubbleKey) {
                const userIdx = items.findIndex(
                  (it) =>
                    (it.kind === "bubble" || it.kind === "pending-user") &&
                    it.key === lastUserBubbleKey,
                );
                if (userIdx >= 0) insertAt = userIdx + 1;
              }
              items.splice(insertAt, 0, thinkingItem);
            }

            if (mobileShell && items.length === 0) {
              return (
                <div className="chat-welcome" key="welcome">
                  <img
                    className="chat-welcome-icon"
                    src="/xiaoxing-logo.png"
                    alt=""
                    width={120}
                    height={120}
                    decoding="async"
                  />
                  <p className="chat-welcome-text">
                    <span className="chat-welcome-line">你好，我是小星</span>
                    <span className="chat-welcome-line">你的AI路线规划伙伴</span>
                  </p>
                </div>
              );
            }

            return items.map((it) => <Fragment key={it.key}>{it.node}</Fragment>);
          })()}
          {showLiveBubble &&
          liveStreamText.trim() &&
          !isNoiseAssistantBubble(liveStreamText) &&
          !isRawToolPayloadText(liveStreamText) ? (
            <div
              className={`bubble-row bubble-row-assistant`}
            >
              <div
                className={`bubble role-assistant streaming${
                  mobileShell && !intakePhasePending && !isIntakeQuestionBubble(liveStreamText)
                    ? " bubble-plan"
                    : ""
                }`}
              >
              {!mobileShell ? <div className="role">live</div> : null}
              <MarkdownErrorBoundary text={liveStreamText}>
                {mobileShell && isPlanMessage(liveStreamText) ? (
                  <PlanMessageBody
                    text={liveStreamText}
                    pois={sessionPois}
                    userLocation={resolvedLocation}
                  />
                ) : shouldStreamMarkdown(liveStreamText) ? (
                  <StreamingMarkdown text={liveStreamText} />
                ) : (
                  <StreamingPlainText text={liveStreamText} />
                )}
              </MarkdownErrorBoundary>
              </div>
            </div>
          ) : null}
          {showIntakeLoading && !mobileShell ? (
            <div className="bubble role-assistant typing-bubble" aria-live="polite">
              <div className="role">assistant</div>
              <p className="typing-line">
                正在生成选择题
                <span className="typing-dots">
                  <span>.</span>
                  <span>.</span>
                  <span>.</span>
                </span>
                {visibleToolSteps.some((s) => /加载行程规划指引/.test(s.msg))
                  ? "（已加载规划指引，稍候）"
                  : null}
              </p>
            </div>
          ) : null}
        </div>
        <div className="composer">
          {mobileShell ? <MobileNotice message={mobileNotice} /> : null}
          {appEnabled && wasEverConnected && !mobileShell ? (
            <div className="process-log" ref={processLogRef} aria-label="任务进展与工具调用">
              <div className="process-log-title">任务进展 · 工具调用</div>
              {!connected ? (
                <p className="process-log-status">网络重连中，请稍候再发送…</p>
              ) : suppressToolProgress && awaitingAgent && visibleToolSteps.length === 0 ? (
                <p className="process-log-status">正在生成选择题…</p>
              ) : awaitingAgent && visibleToolSteps.length === 0 ? (
                <p className="process-log-status">处理中（补槽 / 调工具 / 生成方案）…</p>
              ) : intakeActive && visibleToolSteps.length === 0 ? (
                <p className="process-log-status">请先完成上方选择题，提交后 Agent 将调用工具进行规划</p>
              ) : imageGenPending && hasVisibleUserMessage ? (
                <p className="process-log-status">长文已就绪，正在绘制行程一览图…</p>
              ) : visibleToolSteps.length === 0 ? (
                <p className="process-log-empty">发送消息后，Agent 补槽、规划与 MCP 工具调用会实时显示在此</p>
              ) : null}
              {visibleToolSteps.map((s) => (
                <div key={s.id} className="process-log-row">
                  <span className="process-log-clock">{s.clock}</span>
                  <span className="process-log-msg">{s.msg}</span>
                </div>
              ))}
            </div>
          ) : null}
          {showIntakeCard && !intakeLocked && displayIntakeBlocksResolved.length > 0 ? (
            <p className="intake-composer-hint">
              在下方输入口语回复后 Enter 发送；发送后问卷全部置灰，您的句子会像首句一样显示在右侧，Agent 随即开始规划。
            </p>
          ) : null}
          <div className={`composer-input-row${mobileShell ? " composer-mobile" : ""}`}>
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={mobileShell ? 1 : 3}
              placeholder={
                mobileShell
                  ? showIntakeCard && !intakeLocked
                    ? "用口语回答即可，如：我们3个人，地铁出行…"
                    : "跟我说说你想去哪？"
                  : showIntakeCard && !intakeLocked
                    ? "用口语回答即可，如：我们3个人，地铁出行，不忌口…"
                    : "Enter 发送，Shift+Enter 换行"
              }
              disabled={uiLocked}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send();
                }
              }}
            />
            <button
              type="button"
              className={`send${mobileShell && draftReady ? " send-ready" : ""}${canSendDraft ? " send-active" : ""}`}
              onClick={() => void send()}
              disabled={!canSendDraft}
              title={
                !connected
                  ? "连接中…"
                  : creatingThread
                    ? "初始化会话…"
                    : !draftReady
                      ? "请输入内容"
                      : undefined
              }
            >
              {mobileShell ? "发送" : "Send"}
            </button>
          </div>
          {mobileShell ? <p className="ai-disclaimer">内容由 AI 生成</p> : null}
        </div>
      </main>

      {showDebug ? (
        <section className="log">
          <h2>Debug log</h2>
          <pre>{log.join("\n") || "…"}</pre>
        </section>
      ) : null}
        </div>
      </div>

    </div>
    </div>
  );
}
