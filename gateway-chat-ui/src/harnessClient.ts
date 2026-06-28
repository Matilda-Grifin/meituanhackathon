/** Harness 输出校验/修复 API（服务端处理，不破坏气泡 Markdown 结构） */

import { isItineraryImageBubble, isIntakeQuestionText, isAckMessage } from "./presentChatRows";

export type HarnessRepairResult = {
  ok: boolean;
  text: string;
  blocked: boolean;
  repairs_applied: string[];
  violations: { id?: string; pattern?: string; severity?: string }[];
  skipped?: boolean;
};

export function shouldCallHarnessForAssistantText(text: string): boolean {
  const t = text.trim();
  if (!t || t.length < 40) return false;
  if (isItineraryImageBubble(t)) return false;
  if (isIntakeQuestionText(t) && !/行程速览|##\s*📋/.test(t)) return false;
  if (isAckMessage(t) && t.length < 520) return false;
  return true;
}

export async function notifyHarnessUserMessage(
  sessionKey: string,
  message: string,
  opts?: { intakeSkipped?: boolean },
): Promise<void> {
  const sk = sessionKey.trim();
  const msg = message.trim();
  if (!sk || !msg || msg.startsWith("[位置上下文]")) return;
  try {
    await fetch("/api/harness/on-user-message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_key: sk,
        message: msg,
        intake_skipped: !!opts?.intakeSkipped,
      }),
    });
  } catch {
    // 非阻塞：Harness 失败不影响对话
  }
}

export async function requestHarnessRepair(
  sessionKey: string,
  assistantText: string,
): Promise<HarnessRepairResult | null> {
  const sk = sessionKey.trim();
  const text = assistantText.trim();
  if (!sk || !text || !shouldCallHarnessForAssistantText(text)) return null;
  try {
    const res = await fetch("/api/harness/validate-and-repair", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_key: sk,
        text,
        apply_repairs: true,
      }),
    });
    if (!res.ok) return null;
    return (await res.json()) as HarnessRepairResult;
  } catch {
    return null;
  }
}
