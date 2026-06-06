/** 会话空闲预热：在用户首句前触发 Agent 读取 workspace 规则 */

export const WARMUP_MESSAGE =
  "[系统预热] 请读取 workspace 中的 SOUL.md、AGENTS.md、skills/travel-intake/SKILL.md，" +
  "熟悉补槽与两阶段规则。本消息为系统预热，不要向用户输出任何可见文字，读完即可结束本轮。";

export const WARMUP_TIMEOUT_MS = 45_000;

export type WarmupState = "idle" | "running" | "done" | "failed";

export function isWarmupMessage(text: string): boolean {
  return text.trimStart().startsWith("[系统预热]");
}

export function shouldStartWarmup(opts: {
  sessionKey: string;
  hasVisibleUserMessage: boolean;
  warmupState: WarmupState;
}): boolean {
  if (!opts.sessionKey.trim()) return false;
  if (opts.hasVisibleUserMessage) return false;
  if (opts.warmupState === "done" || opts.warmupState === "running") return false;
  return true;
}
