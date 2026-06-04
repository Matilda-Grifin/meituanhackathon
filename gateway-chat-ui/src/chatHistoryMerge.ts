/** Chat timeline merge: never drop local rows when chat.history lags or truncates. */

export type ChatRow = { role: string; text: string; id: string };

function isItineraryImageBubbleText(text: string): boolean {
  return /##\s*📸\s*行程一览图/.test(text);
}

function isClientOnlyAssistantRow(row: ChatRow): boolean {
  if (normRole(row.role) !== "assistant") return false;
  if (isItineraryImageBubbleText(row.text)) return true;
  return row.id.startsWith("a-img-");
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

function rowIdentityKey(row: ChatRow): string | null {
  const role = normRole(row.role);
  if (role !== "user" && role !== "assistant") return null;
  const text = row.text.trim();
  if (!text) return null;
  const fp = text.length > 280 ? text.slice(0, 280) : text;
  return `${role}|${fp}`;
}

function userRefreshKey(row: ChatRow): string | null {
  if (normRole(row.role) !== "user") return null;
  const t = row.text.trim();
  if (!t) return null;
  const fp = t.length > 200 ? t.slice(0, 200) : t;
  return `user|${fp}`;
}

function appendPendingUser(rows: ChatRow[], pendingUserText: string | null): ChatRow[] {
  const pending = pendingUserText?.trim();
  if (!pending) return rows;
  const lastUser = lastUserTextInRows(rows);
  if (lastUser != null && lastUser.trim() === pending) return rows;
  return [...rows, { role: "user", text: pending, id: `u-opt-${Date.now().toString(36)}` }];
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
    return dedupeAdjacentAssistant(appendPendingUser([...previous], pending));
  }

  if (!previous.length) {
    return dedupeAdjacentAssistant(appendPendingUser([...incoming], pending));
  }

  let merged = reconcileIds(previous, incoming);
  merged = appendTrailingFromPrevious(previous, merged);
  merged = appendPendingUser(merged, pending);
  return dedupeAdjacentAssistant(merged);
}

export function getChatEventState(payload: unknown): string | null {
  if (!payload || typeof payload !== "object") return null;
  const state = (payload as Record<string, unknown>).state;
  return typeof state === "string" ? state.trim().toLowerCase() : null;
}
