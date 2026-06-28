/** Chat timeline merge: never drop local rows when chat.history lags or truncates. */

import { extractUserVisibleTextFromMessage } from "./location";

/** 工具调用记录（来自时序采集） */
export type ToolCallTiming = {
  name: string;
  /** 工具调用耗时 (ms) */
  durationMs?: number;
  /** 调用是否成功 */
  ok?: boolean;
  /** 错误信息 */
  error?: string;
};

export type ChatRow = {
  role: string;
  text: string;
  id: string;
  /** 消息时间戳 (Date.now()，毫秒) */
  timestamp?: number;
  /** 首字时长 (ms)：用户发送 → 首个 assistant 文本 WebSocket 帧到达 */
  ttftMs?: number;
  /** 本轮 assistant 完整响应时长 (ms) */
  durationMs?: number;
  /** 首个工具调用延迟 (ms)：用户发送 → 首个工具调用事件 */
  firstToolMs?: number;
  /** 本轮工具调用详情 */
  toolCalls?: ToolCallTiming[];
};

function isItineraryImageBubbleText(text: string): boolean {
  return /##\s*📸\s*行程一览图/.test(text);
}

function isClientOnlyAssistantRow(row: ChatRow): boolean {
  if (normRole(row.role) !== "assistant") return false;
  if (isItineraryImageBubbleText(row.text)) return true;
  if (row.id.startsWith("a-img-")) return true;
  /** 工具调用前 early-flush 的首响 ack；history 滞后时须保留，避免闪退 */
  if (row.id.startsWith("a-ack-")) return true;
  /** 口语跳过问卷后的 B 阶段入口声明；须常驻对话区 */
  if (row.id.startsWith("a-skip-intake-")) return true;
  return false;
}

function normRole(role: string): string {
  return String(role).toLowerCase();
}

export function lastUserTextInRows(rows: ChatRow[]): string | null {
  for (let i = rows.length - 1; i >= 0; i--) {
    if (normRole(rows[i]!.role) === "user") return rows[i]!.text;
  }
  return null;
}

function userVisibleText(row: ChatRow): string {
  if (normRole(row.role) !== "user") return row.text.trim();
  return extractUserVisibleTextFromMessage(row.text).trim() || row.text.trim();
}

function rowIdentityKey(row: ChatRow): string | null {
  const role = normRole(row.role);
  if (role !== "user" && role !== "assistant") return null;
  const text = role === "user" ? userVisibleText(row) : row.text.trim();
  if (!text) return null;
  const fp = text.length > 280 ? text.slice(0, 280) : text;
  return `${role}|${fp}`;
}

function userRefreshKey(row: ChatRow): string | null {
  if (normRole(row.role) !== "user") return null;
  const t = userVisibleText(row);
  if (!t) return null;
  const fp = t.length > 200 ? t.slice(0, 200) : t;
  return `user|${fp}`;
}

function appendPendingUser(rows: ChatRow[], pendingUserText: string | null): ChatRow[] {
  const pending = pendingUserText?.trim();
  if (!pending) return rows;
  const pendingVisible = extractUserVisibleTextFromMessage(pending).trim() || pending;
  for (let i = rows.length - 1; i >= 0; i--) {
    if (normRole(rows[i]!.role) !== "user") continue;
    if (userVisibleText(rows[i]!) === pendingVisible) return rows;
    break;
  }
  return [...rows, { role: "user", text: pending, id: `u-opt-${Date.now().toString(36)}` }];
}

/** 去掉相邻、用户可见文本相同的 user 气泡（乐观更新 + 带位置前缀的 history） */
export function dedupeAdjacentUser(rows: ChatRow[]): ChatRow[] {
  const out: ChatRow[] = [];
  for (const r of rows) {
    const last = out[out.length - 1];
    if (
      last &&
      normRole(last.role) === "user" &&
      normRole(r.role) === "user" &&
      userVisibleText(last) === userVisibleText(r)
    ) {
      continue;
    }
    out.push(r);
  }
  return out;
}

function dedupeAdjacent(rows: ChatRow[]): ChatRow[] {
  return dedupeAdjacentUser(dedupeAdjacentAssistant(rows));
}

/** 去掉相邻、完全相同的 assistant 气泡 */
export function dedupeAdjacentAssistant(rows: ChatRow[]): ChatRow[] {
  const out: ChatRow[] = [];
  for (const r of rows) {
    const last = out[out.length - 1];
    if (
      last &&
      normRole(last.role) === "assistant" &&
      normRole(r.role) === "assistant" &&
      last.text === r.text
    ) {
      continue;
    }
    out.push(r);
  }
  return out;
}

function reconcileIds(previous: ChatRow[], incoming: ChatRow[]): ChatRow[] {
  if (!previous.length || !incoming.length) return incoming;

  const idsByKey = new Map<string, string[]>();
  for (const row of previous) {
    const key = rowIdentityKey(row);
    if (!key) continue;
    const arr = idsByKey.get(key) ?? [];
    arr.push(row.id);
    idsByKey.set(key, arr);
  }

  return incoming.map((row) => {
    const key = rowIdentityKey(row);
    if (!key) return row;
    const ids = idsByKey.get(key);
    if (!ids?.length) return row;
    const reused = ids.shift()!;
    if (!ids.length) idsByKey.delete(key);
    else idsByKey.set(key, ids);
    return reused === row.id ? row : { ...row, id: reused };
  });
}

function appendTrailingFromPrevious(previous: ChatRow[], reconciled: ChatRow[]): ChatRow[] {
  if (!previous.length) return reconciled;

  const incomingKeys = new Set(reconciled.map((r) => rowIdentityKey(r)).filter((k): k is string => Boolean(k)));
  const remainingIncomingUser = new Map<string, number>();
  for (const row of reconciled) {
    const uk = userRefreshKey(row);
    if (uk) remainingIncomingUser.set(uk, (remainingIncomingUser.get(uk) ?? 0) + 1);
  }

  let lastMatchedIndex: number | undefined;
  for (let i = 0; i < previous.length; i++) {
    const row = previous[i]!;
    const key = rowIdentityKey(row);
    if (key && incomingKeys.has(key)) {
      lastMatchedIndex = i;
      continue;
    }
    const uk = userRefreshKey(row);
    if (uk) {
      const rem = remainingIncomingUser.get(uk) ?? 0;
      if (rem > 0) {
        remainingIncomingUser.set(uk, rem - 1);
        lastMatchedIndex = i;
      }
    }
  }

  const trailingStart = lastMatchedIndex !== undefined ? lastMatchedIndex + 1 : 0;
  const trailingExtra = previous.slice(trailingStart).filter((row) => {
    if (isClientOnlyAssistantRow(row)) {
      const key = rowIdentityKey(row);
      return !(key && incomingKeys.has(key));
    }
    if (normRole(row.role) !== "user") return false;
    const uk = userRefreshKey(row);
    if (!uk) return true;
    const rem = remainingIncomingUser.get(uk) ?? 0;
    if (rem > 0) {
      remainingIncomingUser.set(uk, rem - 1);
      return false;
    }
    return true;
  });

  if (!trailingExtra.length) return reconciled;
  return [...reconciled, ...trailingExtra];
}

/** 保留 previous 中任意位置的客户端专属 assistant 行（生图 / early-ack），避免多轮对话后被 reconcile 丢掉 */
function preserveClientOnlyAssistantRows(previous: ChatRow[], merged: ChatRow[]): ChatRow[] {
  if (!previous.length) return merged;

  const presentIds = new Set(merged.map((r) => r.id));
  const presentKeys = new Set(
    merged.map((r) => rowIdentityKey(r)).filter((k): k is string => Boolean(k)),
  );

  const orphans = previous.filter((r) => {
    if (!isClientOnlyAssistantRow(r)) return false;
    if (presentIds.has(r.id)) return false;
    const key = rowIdentityKey(r);
    if (key && presentKeys.has(key)) return false;
    return true;
  });
  if (!orphans.length) return merged;

  let result = [...merged];
  for (const orphan of orphans) {
    const origIdx = previous.indexOf(orphan);
    let insertAfter = -1;
    for (let i = origIdx - 1; i >= 0; i--) {
      const pr = previous[i]!;
      const prKey = rowIdentityKey(pr);
      const idxInResult = result.findIndex(
        (r) => r.id === pr.id || (prKey != null && rowIdentityKey(r) === prKey),
      );
      if (idxInResult >= 0 && normRole(pr.role) === "assistant") {
        insertAfter = idxInResult;
        break;
      }
    }
    if (insertAfter >= 0) result.splice(insertAfter + 1, 0, orphan);
    else result.push(orphan);
  }
  return result;
}

/**
 * Merge server history with on-screen rows. Never shrink to empty when previous has content.
 */
export function reconcileChatRows(
  previous: ChatRow[],
  incoming: ChatRow[],
  opts?: { pendingUserText?: string | null },
): ChatRow[] {
  const pending = opts?.pendingUserText ?? null;

  if (!incoming.length) {
    return dedupeAdjacent(appendPendingUser([...previous], pending));
  }

  if (!previous.length) {
    return dedupeAdjacent(appendPendingUser([...incoming], pending));
  }

  let merged = reconcileIds(previous, incoming);
  merged = appendTrailingFromPrevious(previous, merged);
  merged = preserveClientOnlyAssistantRows(previous, merged);
  merged = appendPendingUser(merged, pending);
  return dedupeAdjacent(merged);
}

export function getChatEventState(payload: unknown): string | null {
  if (!payload || typeof payload !== "object") return null;
  const state = (payload as Record<string, unknown>).state;
  return typeof state === "string" ? state.trim().toLowerCase() : null;
}

/** history 合并结果指纹：用于无变化时跳过 setRows，减轻长方案 Markdown 闪动 */
export function rowsStableSignature(rows: ChatRow[]): string {
  return rows
    .map((r) => {
      const t = r.text;
      const head = t.length > 96 ? t.slice(0, 96) : t;
      return `${r.id}|${normRole(r.role)}|${t.length}|${head}`;
    })
    .join("\n");
}
