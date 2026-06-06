import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  type ChatRow,
} from "./chatHistoryMerge";
import {
  formatLocationContextMessage,
  hasStoredLocationConsent,
  isLocationContextMessage,
  loadStoredLocationSnapshot,
  LOCATION_INJECT_WAIT_MS,
  resolveUserLocationTimed,
  storeLocationConsent,
  storeLocationSnapshot,
  type ResolvedLocation,
} from "./location";
import {
  cancelItineraryImageJob,
  formatItineraryImageMarkdown,
  findLongestPlanText,
  isCompleteItineraryPlan,
  planTextFingerprint,
  requestItineraryImage,
  rowsHasItineraryImage,
  toolEventUsedSearchPlaces,
} from "./itineraryImage";
import {
  appendPersistedItineraryImage,
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
  shouldStartWarmup,
  WARMUP_MESSAGE,
  WARMUP_TIMEOUT_MS,
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
  isAckMessage,
  isPlanMessage,
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
  historyDataUsedSearchPlaces,
  labelForTool,
  type ProcessStep,
} from "./toolProgress";

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
  if (rl === "user" && isLocationContextMessage(text)) return true;
  if (rl === "user" && isWarmupMessage(text)) return true;
  if (rl === "user" && isIntakeDisplayHiddenUserRow(text)) return true;
  if (rl === "tool" || rl === "toolresult") return true;
  if (isRawToolPayloadText(text)) return true;
  if (rl === "assistant" && isNoiseAssistantBubble(stripAssistantToolNoise(text))) return true;
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
  if (rlow === "user" && isLocationContextMessage(text)) return true;
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

function isNoiseAssistantBubble(text: string): boolean {
  if (isEmptyAssistantPlaceholder(text)) return true;
  const t = text.trim();
  if (!t) return true;
  if (/^（无正文\s*·\s*stop:\s*toolUse）$/i.test(t)) return true;
  if (/^assistant\s*$/i.test(t)) return true;
  return false;
}

function isIntakeQuestionBubble(text: string): boolean {
  const intakeOnly = extractIntakeOnlyText(text);
  return hasIntakeQuestions(intakeOnly) && text.trim() === intakeOnly;
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

function findIntakeAnchorUserId(rows: ChatRow[]): string | null {
  const idx = findCurrentTurnAnchorIdx(rows);
  return idx >= 0 ? rows[idx]!.id : null;
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

function isIntakeSubmissionText(text: string): boolean {
  return /^选择题答案：/.test(text.trim()) || /^全部用默认/.test(text.trim());
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
    const snap = buildTurnSubmittedIntake(rows, i);
    if (snap) found = { anchorId: r.id, snapshot: snap };
  }
  return found;
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

/** 优先级：URL query > 上次会话 localStorage > Vite 默认（避免 env 固定 key 盖住侧栏里各条独立 session） */
function loadSettings() {
  const sp = new URLSearchParams(window.location.search);
  const fromEnvGateway = envStr("VITE_DEFAULT_GATEWAY_WS");
  const fromEnvToken = envStr("VITE_GATEWAY_TOKEN");
  const fromEnvSession = envStr("VITE_DEFAULT_SESSION_KEY");
  return {
    gatewayUrl:
      sp.get("gateway")?.trim() ||
      localStorage.getItem("gw.url")?.trim() ||
      fromEnvGateway ||
      "ws://127.0.0.1:18789",
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
const autoConnect = import.meta.env.VITE_AUTO_CONNECT === "true";
const showDebug = import.meta.env.VITE_SHOW_DEBUG === "true";

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
  const [streaming, setStreaming] = useState("");
  const [toolSteps, setToolSteps] = useState<ProcessStep[]>([]);
  const [awaitingAgent, setAwaitingAgent] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [intakeSelections, setIntakeSelections] = useState<Record<number, string>>({});
  const [intakeCustom, setIntakeCustom] = useState<Record<number, string>>({});
  const [intakeFollowUp, setIntakeFollowUp] = useState<Record<number, string>>({});
  const [frozenIntake, setFrozenIntake] = useState<IntakeBlock[] | null>(null);
  const [frozenIntakeIntro, setFrozenIntakeIntro] = useState("");
  const [intakeFocusQ, setIntakeFocusQ] = useState<number | null>(null);
  const [intakeSubmitted, setIntakeSubmitted] = useState(false);
  const [submittedIntake, setSubmittedIntake] = useState<IntakeSubmittedSnapshot | null>(null);
  const [intakeAnchorUserId, setIntakeAnchorUserId] = useState<string | null>(null);
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string>("");
  const lastAssistantRowId = useRef<string | null>(null);
  const clientRef = useRef<GatewayBrowserClient | null>(null);
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
  const toolStartedThisRunRef = useRef(false);
  const tryEarlyFlushAckRef = useRef<() => void>(() => {});
  const itineraryImageAbortRef = useRef<AbortController | null>(null);
  const itineraryImageJobIdRef = useRef<string | null>(null);
  const lastImagePlanFpRef = useRef("");
  const maybeStartItineraryImageRef = useRef<(planText: string) => void>(() => {});
  const tryTriggerItineraryImageFromRowsRef = useRef<() => void>(() => {});
  const cancelItineraryImageGenRef = useRef<() => void>(() => {});
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
  const locationInjectedSessions = useRef<Set<string>>(new Set());
  const locationInjectInFlightRef = useRef<Map<string, Promise<boolean>>>(new Map());
  const locationRefreshInFlightRef = useRef(false);
  const warmupInFlightRef = useRef(false);
  const warmupDoneSessions = useRef<Set<string>>(new Set());
  const warmupPromiseRef = useRef<Promise<void> | null>(null);
  const warmupResolveRef = useRef<(() => void) | null>(null);
  const warmupStateRef = useRef<WarmupState>("idle");
  const finishWarmupRunRef = useRef<(sk: string) => void>(() => {});
  const startSessionWarmupRef = useRef<() => void>(() => {});
  const ensureWarmupCompleteRef = useRef<(timeoutMs?: number) => Promise<void>>(async () => {});

  const appEnabled = locationConsent === "granted";
  const showLocationConsent = locationConsent === "pending";

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

  /** 问卷解析：仅 intake 阶段；提交后不再解析 plan/ack */
  const intakeParseText = useMemo(() => {
    if (intakeSubmitted || lastUserIsIntakeSubmission) return "";

    const live = streaming.trim();
    if (live) {
      const liveIntake = extractIntakeOnlyText(live);
      if (parseQuestionBlocks(liveIntake).length > 0) return liveIntake;
      return "";
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
  }, [rows, streaming, intakeSubmitted, lastUserIsIntakeSubmission]);

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
    return buildTurnSubmittedIntake(rows, currentTurnAnchorIdx);
  }, [rows, currentTurnAnchorIdx]);

  const sessionPlanningIntake = useMemo(() => findSessionPlanningIntake(rows), [rows]);

  useEffect(() => {
    if (turnSubmittedIntake || lastUserIsIntakeSubmission) return;
    if (currentTurnAnchorIdx < 0) {
      setFrozenIntake(null);
      setFrozenIntakeIntro("");
      setIntakeFocusQ(null);
      return;
    }
    if (intakeBlocks.length > 0) {
      setFrozenIntake(intakeBlocks);
      if (intakeIntro) setFrozenIntakeIntro(intakeIntro);
    } else if (!streaming.trim()) {
      setFrozenIntake(null);
      setFrozenIntakeIntro("");
      setIntakeFocusQ(null);
    }
  }, [
    intakeBlocks,
    intakeIntro,
    currentTurnAnchorIdx,
    streaming,
    lastUserIsIntakeSubmission,
    turnSubmittedIntake,
  ]);

  const displayIntakeIntro = frozenIntakeIntro || intakeIntro;

  const persistedIntakeSnapshot = sessionPlanningIntake?.snapshot ?? null;
  const effectiveSubmittedIntake =
    turnSubmittedIntake ?? persistedIntakeSnapshot ?? (intakeSubmitted ? submittedIntake : null);
  const intakeLocked = Boolean(effectiveSubmittedIntake) || lastUserIsIntakeSubmission;

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

  useEffect(() => {
    const anchorId = findIntakeAnchorUserId(rows);
    if (anchorId) setIntakeAnchorUserId(anchorId);
    else setIntakeAnchorUserId(null);
  }, [rows]);

  useEffect(() => {
    if (!currentTurnAnchorId) return;
    setIntakeSelections({});
    setIntakeCustom({});
    setIntakeFollowUp({});
    setIntakeFocusQ(null);
  }, [currentTurnAnchorId]);

  useEffect(() => {
    if (turnSubmittedIntake) {
      setSubmittedIntake(turnSubmittedIntake);
      setIntakeSubmitted(true);
      setFrozenIntake(turnSubmittedIntake.blocks);
      return;
    }
    if (!awaitingAgent) {
      setIntakeSubmitted(false);
      setSubmittedIntake(null);
    }
  }, [turnSubmittedIntake, awaitingAgent]);

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
  }, [rows, streaming, showIntakeCard]);

  useEffect(() => {
    rowsRef.current = rows;
  }, [rows]);

  useEffect(() => {
    streamingRef.current = streaming;
  }, [streaming]);

  const tryEarlyFlushAck = useCallback(() => {
    if (ackFlushedThisRunRef.current) return;
    const stream = streamingRef.current.trim();
    if (!stream || isEmptyAssistantPlaceholder(stream) || isPlanMessage(stream)) return;
    if (!shouldEarlyFlushAck(stream)) return;

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
  const visibleToolSteps = hasVisibleUserMessage ? toolSteps : [];

  const liveStreamText = useMemo(
    () =>
      liveStreamDisplayText(
        streaming,
        ackTextThisRunRef.current,
        ackFlushedThisRunRef.current,
      ),
    [streaming, ackFlushedTick],
  );

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
    const live = streaming.trim();
    if (live.length > 12 && !isIntakeQuestionBubble(live)) {
      setAwaitingAgent(false);
    }
  }, [rows, streaming, awaitingAgent, lastUserBubble]);

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
        if (historyDataUsedSearchPlaces(data)) {
          historyHadSearchRef.current = true;
          hadSearchPlacesRef.current = true;
        }
        const { sessionKey: skCanon, rows: serverRows } = extractHistoryRows(data);
        const pending = optimisticUserRef.current;
        setRows((prev) => {
          if (loadGen !== historyLoadGen.current) return prev;
          const sameSession = lastHistorySessionRef.current === sk;
          const basePrev = sameSession ? prev : [];
          let merged = reconcileChatRows(basePrev, serverRows, { pendingUserText: pending });
          merged = appendPersistedItineraryImage(sk, merged);
          if (pending && serverRows.length > 0) {
            const lu = lastUserTextInRows(serverRows);
            if (lu != null && lu.trim() === pending.trim()) optimisticUserRef.current = null;
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
          window.setTimeout(() => tryTriggerItineraryImageFromRowsRef.current(), 80);
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
      const repaired = await requestHarnessRepair(sk, r.text);
      if (!repaired || repaired.skipped || repaired.text === r.text) return;
      setRows((prev) => {
        const idx = prev.findIndex((x) => x.id === r.id);
        if (idx < 0) return prev;
        const next = [...prev];
        next[idx] = { ...next[idx]!, text: repaired.text };
        rowsRef.current = next;
        return next;
      });
      return;
    }
  }, [sessionKey]);

  const flushStreamingIntoRows = useCallback(() => {
    const streamBuf = stripLeadingAssistantPlaceholders(streamingRef.current.trim());
    if (!streamBuf || isEmptyAssistantPlaceholder(streamBuf)) return;
    setRows((prev) => {
      const last = prev[prev.length - 1];
      if (last && String(last.role).toLowerCase() === "assistant" && last.text === streamBuf) {
        return prev;
      }
      const next = [...prev, { role: "assistant", text: streamBuf, id: `a-flush-${Date.now().toString(36)}` }];
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

  const cancelItineraryImageGen = useCallback(() => {
    itineraryImageAbortRef.current?.abort();
    itineraryImageAbortRef.current = null;
    const jobId = itineraryImageJobIdRef.current;
    itineraryImageJobIdRef.current = null;
    if (jobId) void cancelItineraryImageJob(jobId);
    setImageGenPending(false);
  }, []);

  useEffect(() => {
    cancelItineraryImageGenRef.current = cancelItineraryImageGen;
  }, [cancelItineraryImageGen]);

  const maybeStartItineraryImage = useCallback(
    (planText: string) => {
      if (!appEnabled) return;
      if (indexOfFirstVisibleUser(rowsRef.current) < 0) return;
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

      void (async () => {
        try {
          const result = await requestItineraryImage(text, jobId, ac.signal);
          if (ac.signal.aborted || (!result.ok && "cancelled" in result && result.cancelled)) {
            setToolSteps((p) => appendProcessStep(p, "行程图已取消（您开始了新对话）"));
            return;
          }
          if (!result.ok || !("image_url" in result)) {
            pushLog(
              `itinerary-image failed: ${"error" in result ? result.error : "unknown"}`,
            );
            return;
          }
          const md = formatItineraryImageMarkdown(result.image_url);
          const imgRow: ChatRow = { role: "assistant", text: md, id: `a-img-${Date.now().toString(36)}` };
          persistItineraryImageRow(sessionKey.trim(), fp, imgRow);
          setRows((prev) => {
            const last = prev[prev.length - 1];
            if (last && String(last.role).toLowerCase() === "assistant" && last.text === md) return prev;
            const next = [...prev, imgRow];
            rowsRef.current = next;
            return next;
          });
          setToolSteps((p) => appendProcessStep(p, "行程一览图已生成"));
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
    [appEnabled, cancelItineraryImageGen, pushLog, sessionKey],
  );

  useEffect(() => {
    maybeStartItineraryImageRef.current = maybeStartItineraryImage;
  }, [maybeStartItineraryImage]);

  useEffect(() => {
    imageGenPendingRef.current = imageGenPending;
  }, [imageGenPending]);

  const tryTriggerItineraryImageFromRows = useCallback(() => {
    if (!appEnabled) return;
    if (indexOfFirstVisibleUser(rowsRef.current) < 0) return;
    if (streamingRef.current.trim()) return;
    if (imageGenPendingRef.current || itineraryImageJobIdRef.current) return;
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
        const noteToolStart = (payload: unknown) => {
          const raw = JSON.stringify(payload ?? "");
          if (/lifecare__|tool|mcp/i.test(raw)) {
            toolStartedThisRunRef.current = true;
            queueMicrotask(() => tryEarlyFlushAckRef.current());
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
            setStreaming((prev) => {
              let n = mergeStreamText(prev, piece);
              n = stripLeadingAssistantPlaceholders(n);
              streamingRef.current = n;
              return n;
            });
            queueMicrotask(() => tryEarlyFlushAckRef.current());
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
            flushStreamingIntoRowsRef.current();
            if (chatState === "final") {
              window.setTimeout(() => tryTriggerItineraryImageFromRowsRef.current(), 80);
            }
            toolStartedThisRunRef.current = false;
            setAckFlushedTick((t) => t + 1);
            setAwaitingAgent(false);
            stopHistoryPollRef.current();
            void refreshHistoryRef.current({ keepOnEmpty: true });
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
        const extra = error ? ` ${error.code}: ${error.message}` : "";
        const mixed =
          code === 1006 && insecureWsFromSecurePage(ws)
            ? " · 若本页是 HTTPS：浏览器会拦截 ws://（混合内容），请改用 http://… 打开本页，或为 18789 配 wss 反代"
            : "";
        const raw = `closed ${code} ${reason}${extra}${mixed}`;
        pushLog(`close ${raw}`);
        if (compactUi && autoConnect && appEnabled) {
          if (!wasEverConnectedRef.current) {
            setConnected(false);
            setHello(null);
          }
          setStatus("disconnected");
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
    try {
      const loc = await refreshUserLocation();
      if (!loc) {
        setLocationError("未能获取位置（请检查网络或稍后重试）。若持续失败，可刷新页面重试。");
        return;
      }
      storeLocationConsent();
      setLocationConsent("granted");
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

  const sendHiddenContextMessage = useCallback(
    async (text: string) => {
      const c = clientRef.current;
      if (!c?.connected || !sessionKey.trim()) return false;
      const idem = newIdempotencyKey();
      try {
        await c.request("chat.send", {
          sessionKey: sessionKey.trim(),
          message: text,
          idempotencyKey: idem,
        });
        pushLog("location context injected (hidden)");
        return true;
      } catch (e) {
        pushLog(`location inject failed: ${formatRpcError(e)}`);
        return false;
      }
    },
    [pushLog, sessionKey],
  );

  const finishWarmupRun = useCallback((sk: string) => {
    if (!warmupInFlightRef.current && !warmupResolveRef.current) return;
    warmupInFlightRef.current = false;
    warmupStateRef.current = "done";
    if (sk) warmupDoneSessions.current.add(sk);
    setStreaming("");
    streamingRef.current = "";
    setToolSteps([]);
    warmupResolveRef.current?.();
    warmupResolveRef.current = null;
    warmupPromiseRef.current = null;
  }, []);

  useEffect(() => {
    finishWarmupRunRef.current = finishWarmupRun;
  }, [finishWarmupRun]);

  const startSessionWarmup = useCallback(async () => {
    const sk = sessionKey.trim();
    if (!sk || !appEnabled || !clientRef.current?.connected) return;
    if (warmupDoneSessions.current.has(sk)) return;
    if (warmupInFlightRef.current) return;
    if (indexOfFirstVisibleUser(rowsRef.current) >= 0) {
      warmupDoneSessions.current.add(sk);
      warmupStateRef.current = "done";
      return;
    }
    if (
      !shouldStartWarmup({
        sessionKey: sk,
        hasVisibleUserMessage: false,
        warmupState: warmupStateRef.current,
      })
    ) {
      return;
    }

    warmupInFlightRef.current = true;
    warmupStateRef.current = "running";
    warmupPromiseRef.current = new Promise<void>((resolve) => {
      warmupResolveRef.current = resolve;
    });

    const ok = await sendHiddenContextMessage(WARMUP_MESSAGE);
    if (!ok) {
      pushLog("warmup: hidden send failed");
      warmupStateRef.current = "failed";
      finishWarmupRun(sk);
      return;
    }

    window.setTimeout(() => {
      if (!warmupInFlightRef.current) return;
      pushLog("warmup: timeout, unblocking user send");
      warmupStateRef.current = "failed";
      finishWarmupRun(sk);
    }, WARMUP_TIMEOUT_MS);
  }, [appEnabled, finishWarmupRun, pushLog, sendHiddenContextMessage, sessionKey]);

  const ensureWarmupComplete = useCallback(
    async (timeoutMs = WARMUP_TIMEOUT_MS) => {
      const sk = sessionKey.trim();
      if (!sk || warmupDoneSessions.current.has(sk)) return;
      if (indexOfFirstVisibleUser(rowsRef.current) >= 0) {
        warmupDoneSessions.current.add(sk);
        return;
      }
      if (warmupStateRef.current === "failed") return;
      if (warmupStateRef.current === "idle" && !warmupInFlightRef.current) {
        void startSessionWarmup();
      }
      const p = warmupPromiseRef.current;
      if (!p) return;
      await Promise.race([p, new Promise<void>((r) => window.setTimeout(r, timeoutMs))]);
    },
    [sessionKey, startSessionWarmup],
  );

  useEffect(() => {
    startSessionWarmupRef.current = () => void startSessionWarmup();
    ensureWarmupCompleteRef.current = ensureWarmupComplete;
  }, [ensureWarmupComplete, startSessionWarmup]);

  const injectLocationForSession = useCallback(
    async (userText: string): Promise<boolean> => {
      if (!appEnabled || !resolvedLocation) return false;
      const sk = sessionKey.trim();
      if (!sk || locationInjectedSessions.current.has(sk)) return true;
      const c = clientRef.current;
      if (!c?.connected) return false;

      const inflight = locationInjectInFlightRef.current.get(sk);
      if (inflight) return inflight;

      const task = (async () => {
        const msg = formatLocationContextMessage(resolvedLocation, userText);
        const ok = await sendHiddenContextMessage(msg);
        if (ok) locationInjectedSessions.current.add(sk);
        return ok;
      })();
      locationInjectInFlightRef.current.set(sk, task);
      try {
        return await task;
      } finally {
        locationInjectInFlightRef.current.delete(sk);
      }
    },
    [appEnabled, resolvedLocation, sendHiddenContextMessage, sessionKey],
  );

  /** 仅在用户发送可见消息时注入位置（每 session 一次），不抢先触发 Agent */
  const ensureLocationInjected = useCallback(
    async (userText: string, maxWaitMs = LOCATION_INJECT_WAIT_MS): Promise<void> => {
      if (!appEnabled || !resolvedLocation) return;
      const sk = sessionKey.trim();
      if (!sk || locationInjectedSessions.current.has(sk)) return;
      const deadline = Date.now() + maxWaitMs;
      while (Date.now() < deadline) {
        if (locationInjectedSessions.current.has(sk)) return;
        const ok = await injectLocationForSession(userText);
        if (ok) return;
        if (!clientRef.current?.connected) return;
        await new Promise((r) => window.setTimeout(r, 150));
      }
      pushLog(`location inject: wait ${maxWaitMs}ms (send without context)`);
    },
    [appEnabled, injectLocationForSession, pushLog, resolvedLocation, sessionKey],
  );

  useEffect(() => {
    if (!connected || !appEnabled || !sessionKey.trim()) return;
    if (indexOfFirstVisibleUser(rows) >= 0) return;
    void injectLocationForSession("");
    void startSessionWarmup();
  }, [appEnabled, connected, injectLocationForSession, rows, sessionKey, startSessionWarmup]);

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
    async (text: string, opts?: { displayText?: string; hideVisibleUser?: boolean }) => {
      const c = clientRef.current;
      const msg = text.trim();
      const userVisible = (opts?.displayText ?? msg).trim();
      if (!appEnabled || !c?.connected || !msg) return;
      if (isLocationContextMessage(msg)) return;
      if (isWarmupMessage(msg)) return;
      if (!sessionKey.trim()) {
        setStatus("session key required");
        return;
      }
      cancelItineraryImageGenRef.current();
      hadSearchPlacesRef.current = false;
      historyHadSearchRef.current = false;
      seenToolsThisRunRef.current = new Set();
      ackFlushedThisRunRef.current = false;
      ackTextThisRunRef.current = "";
      toolStartedThisRunRef.current = false;
      setAckFlushedTick((t) => t + 1);
      await ensureWarmupComplete();
      await ensureLocationInjected(msg);
      const idem = newIdempotencyKey();
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
      setStreaming("");
      setAwaitingAgent(true);
      setToolSteps((p) =>
        appendProcessStep(
          p,
          isIntakeSubmissionText(msg)
            ? "已提交选项，Agent 正在规划路线并调用工具…"
            : "消息已发送，Agent 正在回复（补槽 / 调工具 / 生成方案）…",
        ),
      );
      setStatus("sending…");
      optimisticUserRef.current = msg;
      if (!opts?.hideVisibleUser) {
        setRows((r) => [...r, { role: "user", text: userVisible, id: `u-${idem}` }]);
      }
      try {
        const ack = await c.request("chat.send", {
          sessionKey: sessionKey.trim(),
          message: msg,
          idempotencyKey: idem,
        });
        pushLog(`chat.send ack → ${JSON.stringify(ack)}`);
        void notifyHarnessUserMessage(sessionKey.trim(), msg);
        setStatus("connected · sent");
        setThreads((prev) => {
          if (!activeThreadId) return prev;
          const next = prev.map((t) => {
            if (t.id !== activeThreadId) return t;
            const short = msg.replace(/\s+/g, " ").slice(0, 28);
            const title =
              t.title === "新对话" || /^对话 \d+$/.test(t.title) ? short || t.title : t.title;
            return { ...t, title, updatedAt: Date.now() };
          });
          saveThreads(next);
          return next;
        });
        startHistoryPoll();
        await refreshHistory({ keepOnEmpty: true });
      } catch (e) {
        setAwaitingAgent(false);
        setStatus(`chat.send failed: ${formatRpcError(e)}`);
      }
    },
    [activeThreadId, appEnabled, ensureLocationInjected, ensureWarmupComplete, pushLog, refreshHistory, sessionKey, startHistoryPoll],
  );

  const clearIntakeUi = useCallback(() => {
    setIntakeSelections({});
    setIntakeCustom({});
    setIntakeFollowUp({});
    setFrozenIntake(null);
    setFrozenIntakeIntro("");
    setIntakeFocusQ(null);
    setIntakeSubmitted(false);
    setSubmittedIntake(null);
    setIntakeAnchorUserId(null);
  }, []);

  const sendDefaultIntake = useCallback(async () => {
    const blocks = frozenIntake ?? intakeBlocks;
    if (blocks.length) {
      setSubmittedIntake({
        blocks,
        selections: { ...intakeSelections },
        custom: { ...intakeCustom },
        followUp: { ...intakeFollowUp },
      });
      setFrozenIntake(blocks);
    }
    setIntakeSubmitted(true);
    setIntakeAnchorUserId((prev) => {
      if (prev) return prev;
      for (let i = rows.length - 1; i >= 0; i--) {
        const r = rows[i]!;
        if (String(r.role).toLowerCase() === "user" && !isIntakeSubmissionText(r.text)) return r.id;
      }
      return prev;
    });
    await sendMessage("全部用默认（城市默认坐标、半天、2成人、不忌口、地铁+打车）", { hideVisibleUser: true });
  }, [frozenIntake, intakeBlocks, intakeCustom, intakeFollowUp, intakeSelections, rows, sendMessage]);

  const submitIntakeChoices = useCallback(async () => {
    const blocks = frozenIntake ?? intakeBlocks;
    if (!intakeAnswerComplete(blocks, intakeSelections, intakeCustom, intakeFollowUp)) return;
    const selections = { ...intakeSelections };
    const custom = { ...intakeCustom };
    const followUp = { ...intakeFollowUp };
    const apiText = formatIntakeSubmission(blocks, selections, custom, followUp);
    setSubmittedIntake({ blocks, selections, custom, followUp });
    setFrozenIntake(blocks);
    setIntakeSubmitted(true);
    setIntakeAnchorUserId((prev) => {
      if (prev) return prev;
      for (let i = rows.length - 1; i >= 0; i--) {
        const r = rows[i]!;
        if (String(r.role).toLowerCase() === "user" && !isIntakeSubmissionText(r.text)) return r.id;
      }
      return prev;
    });
    await sendMessage(apiText, { hideVisibleUser: true });
  }, [frozenIntake, intakeBlocks, intakeCustom, intakeFollowUp, intakeSelections, rows, sendMessage]);

  const applyDraftToIntakeOther = useCallback(
    (text: string): boolean => {
      const blocks = frozenIntake ?? intakeBlocks;
      if (!blocks.length) return false;
      const q =
        intakeFocusQ ??
        blocks.find((b) => {
          const letter = intakeSelections[b.n];
          const opt = b.options.find((o) => o.letter === letter);
          return opt?.isOther;
        })?.n ??
        blocks.find((b) => b.options.some((o) => o.isOther) && !intakeSelections[b.n])?.n;
      if (q == null) return false;
      const letter =
        intakeSelections[q] ?? blocks.find((b) => b.n === q)?.options.find((o) => o.isOther)?.letter ?? "D";
      setIntakeSelections((prev) => ({ ...prev, [q]: letter }));
      setIntakeCustom((prev) => ({ ...prev, [q]: text }));
      return true;
    },
    [frozenIntake, intakeBlocks, intakeFocusQ, intakeSelections],
  );

  const send = useCallback(async () => {
    const text = draft.trim();
    if (!text) return;
    const blocks = frozenIntake ?? intakeBlocks;
    const intakeOpen =
      !intakeLocked && blocks.length > 0 && !intakeAnswerComplete(blocks, intakeSelections, intakeCustom, intakeFollowUp);
    if (intakeOpen) {
      if (applyDraftToIntakeOther(text)) {
        setDraft("");
        setStatus("已写入「其他」说明；请点「确认提交」继续规划（直接发送不会跳过问卷）");
        return;
      }
      setStatus("请先点选 A/B/C/D，或在选中「其他」后输入说明；完成后再点「确认提交」");
      return;
    }
    await sendMessage(text);
    setDraft("");
  }, [
    applyDraftToIntakeOther,
    draft,
    frozenIntake,
    intakeBlocks,
    intakeCustom,
    intakeFollowUp,
    intakeLocked,
    intakeSelections,
    sendMessage,
  ]);

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
      stopHistoryPoll();
      historyLoadGen.current += 1;
      lastHistorySessionRef.current = "";
      setStreaming("");
      setAwaitingAgent(false);
      setToolSteps([]);
      warmupInFlightRef.current = false;
      warmupPromiseRef.current = null;
      warmupResolveRef.current?.();
      warmupResolveRef.current = null;
      warmupStateRef.current = "idle";
      clearIntakeUi();
      optimisticUserRef.current = null;
      rowsRef.current = [];
      setActiveThreadId(threadId);
      localStorage.setItem(ACTIVE_THREAD_LS, threadId);
      localStorage.setItem("gw.session", t.sessionKey);
      setSessionKey(t.sessionKey);
      setRows([]);
    },
    [activeThreadId, clearIntakeUi, historyLoading, threads, stopHistoryPoll],
  );

  const createNewThread = useCallback(async () => {
    if (creatingThread) return;
    const c = clientRef.current;
    if (!c?.connected) {
      pendingNewThreadRef.current = true;
      setStatus("连接中，连接成功后将自动新建对话…");
      connect();
      return;
    }
    pendingNewThreadRef.current = false;
    setCreatingThread(true);
    stopHistoryPoll();
    setStreaming("");
    optimisticUserRef.current = null;
    clearIntakeUi();
    rowsRef.current = [];
    try {
      const newKey = await allocateWebchatSessionKey(c, pushLog, {
        label: `webchat-${getOrCreateDeviceId().slice(0, 24)}-${new Date().toISOString().slice(0, 16)}`,
      });
      const id = "t-" + Date.now().toString(36);
      const nt: ChatThread = { id, sessionKey: newKey, title: "新对话", updatedAt: Date.now() };
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
      setRows([]);
      rowsRef.current = [];
      setStatus("已新建对话");
    } catch (e) {
      pushLog(`createNewThread ${formatRpcError(e)}`);
      setStatus(`新建对话失败：${formatRpcError(e)}`);
    } finally {
      setCreatingThread(false);
    }
  }, [clearIntakeUi, connect, creatingThread, pushLog, sessionKey, stopHistoryPoll]);

  const clearAllLocalHistory = useCallback(() => {
    stopHistoryPoll();
    historyLoadGen.current += 1;
    lastHistorySessionRef.current = "";
    clearLocalChatStorage();
    clearIntakeUi();
    setThreads([]);
    setActiveThreadId("");
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
    void createNewThread().finally(() => {
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

  useEffect(() => () => disconnect(), [disconnect]);

  const displayStatus = userFacingStatus(status, connected);
  const uiLocked = !appEnabled;

  const cardAnchorUserId = useMemo(
    () => sessionPlanningIntake?.anchorId ?? intakeAnchorUserId ?? findIntakeAnchorUserId(rows),
    [intakeAnchorUserId, rows, sessionPlanningIntake],
  );

  const intakeCardEl =
    showIntakeCard && intakeCardBlocks.length > 0 ? (
      <div className="bubble role-assistant intake-bubble-shell">
        <IntakeCard
          intro={displayIntakeIntro}
          blocks={intakeCardBlocks}
          selections={cardSelections}
          custom={intakeLocked && effectiveSubmittedIntake ? effectiveSubmittedIntake.custom : intakeCustom}
          followUp={intakeLocked && effectiveSubmittedIntake ? effectiveSubmittedIntake.followUp ?? {} : intakeFollowUp}
          locked={intakeLocked}
          showDefault={/全部用默认/.test(intakeParseText)}
          canSubmit={canSubmitIntake}
          uiLocked={uiLocked}
          onSelect={(n, letter, isOther, hasFollowUp) => {
            setIntakeSelections((prev) => ({ ...prev, [n]: letter }));
            setIntakeFocusQ(isOther || hasFollowUp ? n : null);
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
    <div className={`app${compactUi ? " compact-mode" : ""}${uiLocked ? " app-locked" : ""}`}>
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
      </header>

      <div className="main-layout">
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
                        {t.sessionKey.length > 36 ? `${t.sessionKey.slice(0, 32)}…` : t.sessionKey}
                      </span>
                    ) : null}
                  </button>
                </li>
              ))}
          </ul>
        </aside>

        <div className="main-col">
      {!compactUi ? (
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
      ) : !compactUi && displayStatus ? (
        <p className="compact-connecting" role="status">
          {displayStatus}
        </p>
      ) : null}

      <main className="chat">
        <div className="stream" ref={streamScrollRef}>
          {(() => {
            let intakeCardPlaced = false;
            const bubbles = displayRows.map((r) => {
              const rl = String(r.role).toLowerCase();
              if (isHiddenChatRow(rl, r.text)) {
                return null;
              }
              if (rl === "assistant" && isNoiseAssistantBubble(r.text)) {
                return null;
              }
              if (rl === "assistant" && isIntakeQuestionBubble(r.text)) {
                return null;
              }
              const placeCardWithUser =
                intakeCardEl &&
                !intakeCardPlaced &&
                rl === "user" &&
                cardAnchorUserId != null &&
                cardAnchorUserId === r.id;
              if (placeCardWithUser) intakeCardPlaced = true;

              const bubble = (
                <div key={r.id} className={`bubble role-${rl}`}>
                  <div className="role">{rl}</div>
                  <MarkdownErrorBoundary text={r.text}>
                    <BubbleMarkdown text={r.text} />
                  </MarkdownErrorBoundary>
                </div>
              );
              if (placeCardWithUser) {
                return (
                  <Fragment key={`${r.id}-with-intake`}>
                    {bubble}
                    {intakeCardEl}
                  </Fragment>
                );
              }
              return bubble;
            });
            return (
              <>
                {bubbles}
                {!intakeCardPlaced ? intakeCardEl : null}
              </>
            );
          })()}
          {showLiveBubble &&
          liveStreamText.trim() &&
          !isNoiseAssistantBubble(liveStreamText) &&
          !isRawToolPayloadText(liveStreamText) ? (
            <div className="bubble role-assistant streaming">
              <div className="role">live</div>
              <MarkdownErrorBoundary text={liveStreamText}>
                {shouldStreamMarkdown(liveStreamText) ? (
                  <StreamingMarkdown text={liveStreamText} />
                ) : (
                  <StreamingPlainText text={liveStreamText} />
                )}
              </MarkdownErrorBoundary>
            </div>
          ) : null}
        </div>
        <div className="composer">
          {appEnabled && wasEverConnected ? (
            <div className="process-log" ref={processLogRef} aria-label="任务进展与工具调用">
              <div className="process-log-title">任务进展 · 工具调用</div>
              {!connected ? (
                <p className="process-log-status">网络重连中，请稍候再发送…</p>
              ) : awaitingAgent ? (
                <p className="process-log-status">处理中（补槽 / 调工具 / 生成方案）…</p>
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
              请在上方卡片点选后点「确认提交」；确认前可改选，确认后不可修改。
            </p>
          ) : null}
          <div className="composer-input-row">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={3}
              placeholder="槽位未提交时：Enter 写入「其他」说明；提交后 Enter 发送消息"
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
              className="send"
              onClick={() => void send()}
              disabled={!connected || uiLocked}
            >
              Send
            </button>
          </div>
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
  );
}
