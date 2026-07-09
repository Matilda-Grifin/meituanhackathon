/** 展示层：一轮 assistant 合并为 ack + plan，去英文碎句、去重复开头 */

import {
  isEmptyAssistantPlaceholder,
  stripLeadingAssistantPlaceholders,
} from "./assistantPlaceholders";
import type { ChatRow } from "./chatHistoryMerge";
import {
  extractIntakeOnlyText,
  extractIntakeRemainderText,
  hasIntakeQuestions,
} from "./intakeParse";
import { isLocationContextOnlyMessage, extractUserVisibleTextFromMessage } from "./location";
import { isWarmupMessage } from "./sessionWarmup";

export function extractRunId(payload: unknown): string | null {
  if (!payload || typeof payload !== "object") return null;
  const runId = (payload as Record<string, unknown>).runId;
  return typeof runId === "string" && runId.trim() ? runId.trim() : null;
}

export function isItineraryImageBubble(text: string): boolean {
  return /##\s*📸\s*行程一览图/.test(text);
}

export function isIntakeQuestionText(text: string): boolean {
  if (/行程速览|预算参考|##\s*📋/.test(text)) return false;
  if (/第\s*\d+\s*题/.test(text) && /(?:^|\n)\s*[A-F][\.、．、：)]\s/m.test(text)) return true;
  if (/\d+\uFE0F?\u20E3/.test(text) && /(?:^|\n)\s*[A-F][\.、．、：)]\s/m.test(text)) return true;
  return /^\s*1[\.、．]\s/m.test(text) && /(?:^|\n)\s*[A-F][\.、．\)]\s/m.test(text);
}

const NOISE_EN =
  /^(Now let me|Let me calculate|Let me search|I'll search|I'll plan|I'll calculate|I need to|First,? I'll)/i;

export function isNoiseAssistantSegment(text: string): boolean {
  const t = text.trim();
  if (isEmptyAssistantPlaceholder(t)) return true;
  if (!t || t.length > 320) return false;
  if (NOISE_EN.test(t)) return true;
  if (!/[\u4e00-\u9fff]/.test(t) && t.length < 200) return true;
  return false;
}

export function isPlanMessage(text: string): boolean {
  const t = text.trim();
  if (t.length < 400) return false;
  if (/##\s*📋|行程速览/.test(t)) return true;
  if (/^#\s*[🗺️🏙️🌙🌧️]/m.test(t) && t.length > 800) return true;
  if (/^#\s+.+/m.test(t) && /##\s*💰|预算参考/.test(t)) return true;
  return false;
}

/** 方案正文已开始展示（比 isPlanMessage 宽松，用于收起进度泡） */
export function isPlanContentVisible(text: string): boolean {
  const t = text.trim();
  if (!t || isNoiseAssistantSegment(t)) return false;
  if (isPlanMessage(t)) return true;
  if (/##\s*📋|行程速览/.test(t)) return true;
  if (/^#\s+.+/m.test(t) && t.length >= 48) return true;
  return false;
}

/** 跳过选择题后进 B 阶段的首句声明（须独立展示，不参与 ack 隐藏/合并） */
export function isSkipIntakeEntryAck(text: string): boolean {
  const t = text.trim();
  if (!t || t.length > 680) return false;
  if (isPlanMessage(t) || isIntakeQuestionText(t)) return false;
  return /不再重复问卷/.test(t);
}

/** 流式缓冲里若已完整输出跳过声明，拆成独立泡 + 后续正文 */
export function extractPinnedSkipIntakeEntryAck(
  stream: string,
): { ack: string; remainder: string } | null {
  const t = stream.trim();
  if (!t || !isSkipIntakeEntryAck(t)) return null;

  const planStart = t.search(/^#\s/m);
  const sectionStart = t.search(/^##\s/m);
  const cutAt = planStart >= 0 ? planStart : sectionStart >= 0 ? sectionStart : -1;
  if (cutAt > 80) {
    const ackPart = t.slice(0, cutAt).trim();
    if (isSkipIntakeEntryAck(ackPart)) {
      return { ack: ackPart, remainder: t.slice(cutAt).trimStart() };
    }
  }

  if (!isPlanMessage(t) && /正在查天气|正在并行|搜点|检索地点/.test(t)) {
    return { ack: t, remainder: "" };
  }
  return null;
}

export function isAckMessage(text: string): boolean {
  const t = text.trim();
  if (!t || t.length > 520) return false;
  if (isPlanMessage(t) || isItineraryImageBubble(t)) return false;
  if (isIntakeQuestionText(t)) return false;
  if (isSkipIntakeEntryAck(t)) return false;
  return /好的|收到|明白|正在查|正在并行|搜点|检索地点|重新规划|改成|改为/.test(t);
}

/** 流式阶段：isAckMessage 即 flush，不再要求句号或等工具开始 */
export function shouldEarlyFlushAck(text: string): boolean {
  const t = text.trim();
  if (!t || isPlanMessage(t) || isIntakeQuestionText(t)) return false;
  return isAckMessage(t);
}

export function stripLeadingAckFromPlan(plan: string, ack?: string): string {
  let t = stripLeadingAssistantPlaceholders(plan);
  if (!t) return t;

  const planStart = t.search(/^#\s/m);
  const sectionStart = t.search(/^##\s/m);
  const cutAt = planStart >= 0 ? planStart : sectionStart >= 0 ? sectionStart : -1;

  const ackLike =
    /^好的|^收到|^明白|^数据都齐了|不再重复问卷|重新规划如下|规划如下|下面给你|^---\s*$/m;
  if (cutAt > 0) {
    const head = t.slice(0, cutAt);
    if (ackLike.test(head) || (ack && head.includes(ack.slice(0, Math.min(40, ack.length))))) {
      t = t.slice(cutAt).trimStart();
    }
  } else if (cutAt < 0 && ackLike.test(t.slice(0, 280))) {
    const m = t.match(/^(?:[\s\S]*?)(^#\s[\s\S]*)$/m);
    if (m?.[1]) t = m[1].trimStart();
  }

  if (ack) {
    const ackHead = ack.trim().slice(0, 48);
    if (ackHead.length > 8 && t.startsWith(ackHead)) {
      t = t.slice(ackHead.length).trimStart();
    }
  }
  return t;
}

export function liveStreamDisplayText(
  streaming: string,
  ackText: string,
  ackFlushed: boolean,
  pinnedSkipAck?: string,
  suppressAck = false,
): string {
  const s = streaming.trim();
  if (!s) return "";
  const pinned = pinnedSkipAck?.trim();
  if (pinned && pinned.length > 12) {
    if (s === pinned || s.startsWith(pinned)) {
      const rest = s.slice(pinned.length).trimStart();
      if (!rest) return "";
      if (isPlanMessage(rest)) return stripLeadingAckFromPlan(rest, pinned);
      return rest;
    }
  }
  // 计划/追问阶段：ack（「好的，正在并行查天气…」）只走任务进展条，
  // 对话区不展示纯 ack 文本，避免闪一下又被方案正文顶掉（出现又消失）。
  if (suppressAck) {
    if (isPlanMessage(s)) return stripLeadingAckFromPlan(s, ackText || undefined);
    if (isAckMessage(s)) return "";
    if (!ackFlushed || !ackText) return s;
  }
  if (!ackFlushed || !ackText) return s;
  if (isPlanMessage(s)) return stripLeadingAckFromPlan(s, ackText);
  if (isAckMessage(s) && !isPlanMessage(s)) return "";
  return s;
}

function normRole(role: string): string {
  return String(role).toLowerCase();
}

/** 对话区可见的用户消息（不含仅位置注入 / 预热 hidden user） */
export function isVisibleUserRow(row: ChatRow): boolean {
  if (normRole(row.role) !== "user") return false;
  if (isWarmupMessage(row.text)) return false;
  return !isLocationContextOnlyMessage(row.text);
}

/** 首条可见用户消息的下标；-1 表示尚无用户发言 */
export function indexOfFirstVisibleUser(rows: ChatRow[]): number {
  return rows.findIndex(isVisibleUserRow);
}

/** 丢弃用户首句之前的 assistant（如抢先的位置问候），从首条可见 user 起展示 */
export function rowsFromFirstVisibleUser(rows: ChatRow[]): ChatRow[] {
  const idx = indexOfFirstVisibleUser(rows);
  if (idx < 0) return [];
  return idx > 0 ? rows.slice(idx) : rows;
}

/** 单条 assistant 若含「问卷 + 方案」，拆成两行展示 */
function expandIntakeAssistantRows(assistants: ChatRow[]): ChatRow[] {
  const out: ChatRow[] = [];
  for (const r of assistants) {
    const intakePart = extractIntakeOnlyText(r.text);
    const remainder = extractIntakeRemainderText(r.text);
    const hasIntake = isIntakeQuestionText(r.text) || hasIntakeQuestions(intakePart);
    if (hasIntake && remainder.trim().length > 40) {
      if (intakePart.trim()) {
        out.push({ ...r, text: intakePart });
      }
      out.push({ ...r, id: `${r.id}-plan`, text: remainder });
      continue;
    }
    out.push(r);
  }
  return out;
}

function expandSkipIntakeEntryAckRows(assistants: ChatRow[]): ChatRow[] {
  const out: ChatRow[] = [];
  for (const r of assistants) {
    const split = extractPinnedSkipIntakeEntryAck(r.text);
    if (split?.remainder && split.remainder.length > 40) {
      const ackId = r.id.startsWith("a-skip-intake-") ? r.id : `${r.id}-skip-ack`;
      out.push({ ...r, id: ackId, text: split.ack });
      out.push({ ...r, id: `${r.id}-plan`, text: split.remainder });
      continue;
    }
    out.push(r);
  }
  return out;
}

function mergeAssistantGroup(items: ChatRow[]): ChatRow[] {
  if (!items.length) return [];

  let assistants = items.filter((r) => normRole(r.role) === "assistant");
  const others = items.filter((r) => normRole(r.role) !== "assistant");
  if (!assistants.length) return items;

  if (assistants.some((r) => isIntakeQuestionText(r.text) || hasIntakeQuestions(extractIntakeOnlyText(r.text)))) {
    const expanded = expandIntakeAssistantRows(
      assistants.filter((r) => !isEmptyAssistantPlaceholder(r.text)),
    );
    return [...others, ...expanded];
  }

  assistants = expandSkipIntakeEntryAckRows(assistants);

  const imageRows = assistants.filter((r) => isItineraryImageBubble(r.text));
  const nonImage = assistants.filter((r) => !isItineraryImageBubble(r.text));

  const filtered = nonImage.filter((r) => !isNoiseAssistantSegment(r.text));
  const src = filtered.length ? filtered : nonImage;

  const skipEntryAckRows = src.filter((r) => isSkipIntakeEntryAck(r.text));
  const skipEntryAckIds = new Set(skipEntryAckRows.map((r) => r.id));
  const skipEntryAck =
    skipEntryAckRows.sort((a, b) => b.text.length - a.text.length)[0] ?? null;

  const ackCandidates = src.filter((r) => isAckMessage(r.text) && !skipEntryAckIds.has(r.id));
  const planCandidates = src.filter((r) => isPlanMessage(r.text));
  const ack = ackCandidates.sort((a, b) => b.text.length - a.text.length)[0] ?? null;
  const ackIds = new Set(ackCandidates.map((r) => r.id));
  let plan = planCandidates.sort((a, b) => b.text.length - a.text.length)[0] ?? null;

  const usedIds = new Set<string>();
  if (ack) usedIds.add(ack.id);
  if (plan) usedIds.add(plan.id);
  if (skipEntryAck) usedIds.add(skipEntryAck.id);

  const rest = src.filter(
    (r) => !usedIds.has(r.id) && !ackIds.has(r.id) && !skipEntryAckIds.has(r.id),
  );

  if (!plan && !ack && !skipEntryAck) {
    if (src.length === 1) return [...others, ...src, ...imageRows];
    const longest = [...src].sort((a, b) => b.text.length - a.text.length)[0]!;
    return [...others, longest, ...imageRows];
  }

  const out: ChatRow[] = [...others];
  if (skipEntryAck) out.push(skipEntryAck);
  if (plan) {
    const text = stripLeadingAckFromPlan(plan.text, ack?.text ?? skipEntryAck?.text);
    if (text.trim() && !isEmptyAssistantPlaceholder(text)) {
      out.push({ ...plan, text });
    }
  } else if (rest.length) {
    out.push(...rest);
  } else if (!ack && !skipEntryAck && src.length) {
    out.push(src[src.length - 1]!);
  }
  out.push(...imageRows);
  return out;
}

/** 按 user 消息分段，每段内合并 assistant */
export function presentChatRows(allRows: ChatRow[]): ChatRow[] {
  const rows = rowsFromFirstVisibleUser(allRows);
  if (!rows.length) return rows;

  const out: ChatRow[] = [];
  let group: ChatRow[] = [];

  const flushGroup = () => {
    if (!group.length) return;
    out.push(...mergeAssistantGroup(group));
    group = [];
  };

  for (const row of rows) {
    if (normRole(row.role) === "user") {
      flushGroup();
      const visible =
        extractUserVisibleTextFromMessage(row.text).trim() || row.text.trim();
      const last = out[out.length - 1];
      if (
        last &&
        normRole(last.role) === "user" &&
        (extractUserVisibleTextFromMessage(last.text).trim() || last.text.trim()) === visible
      ) {
        continue;
      }
      out.push(row);
    } else {
      group.push(row);
    }
  }
  flushGroup();
  return out;
}
