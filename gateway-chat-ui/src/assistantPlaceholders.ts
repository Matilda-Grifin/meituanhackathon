/** 网关/OpenClaw 空 assistant 占位文案 — 不应出现在聊天气泡 */

const PLACEHOLDER_LINE =
  /^(?:【无回复】|无回复|NO_REPLY|NO\s*REPLY|【NO_REPLY】|（空回复）|\(空回复\)|（无正文[^）]*）|\(无正文[^)]*\)|模型未返回正文[^\n]*)$/i;

export function isEmptyAssistantPlaceholder(text: string): boolean {
  const t = text.trim();
  if (!t) return true;
  if (PLACEHOLDER_LINE.test(t)) return true;
  if (/^（无正文\s*·\s*stop:\s*\w+）$/i.test(t)) return true;
  return false;
}

/** 去掉正文开头的占位行（历史里与方案粘在同一条时） */
export function stripLeadingAssistantPlaceholders(text: string): string {
  let t = text.replace(/\r\n/g, "\n").trim();
  for (let i = 0; i < 8; i++) {
    const m = t.match(
      /^(?:【无回复】|无回复|NO_REPLY|NO\s*REPLY|【NO_REPLY】|（空回复）|\(空回复\)|（无正文[^）]*）|\(无正文[^)]*\)|模型未返回正文[^\n]*)\s*\n+/i,
    );
    if (!m) break;
    t = t.slice(m[0].length).trimStart();
  }
  if (isEmptyAssistantPlaceholder(t)) return "";
  return t;
}
