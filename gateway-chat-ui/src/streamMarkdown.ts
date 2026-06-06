/** 流式 Markdown 作用域：仅长文方案 live 气泡 */

import { extractIntakeOnlyText, hasIntakeQuestions } from "./intakeParse";
import {
  isAckMessage,
  isIntakeQuestionText,
  isItineraryImageBubble,
  isPlanMessage,
} from "./presentChatRows";

export function shouldStreamMarkdown(text: string): boolean {
  const t = text.trim();
  if (!t) return false;
  if (isIntakeQuestionText(t)) return false;
  const intakeOnly = extractIntakeOnlyText(t);
  if (hasIntakeQuestions(intakeOnly) && intakeOnly.length > 0 && t.includes(intakeOnly.slice(0, 24))) {
    return false;
  }
  if (isAckMessage(t) && !isPlanMessage(t)) return false;
  if (isItineraryImageBubble(t)) return false;
  return isPlanMessage(t) || (/^#\s/m.test(t) && t.length > 280);
}

/** 稳定边界 = 最后一个不在代码围栏内的双换行之后 */
export function findStableMarkdownBoundary(text: string): number {
  const src = text.replace(/\r\n/g, "\n");
  let inFence = false;
  let last = 0;
  let i = 0;
  while (i < src.length) {
    if (src.startsWith("```", i)) {
      inFence = !inFence;
      i += 3;
      continue;
    }
    if (!inFence && src.startsWith("\n\n", i)) {
      last = i + 2;
      i += 2;
      continue;
    }
    i += 1;
  }
  return last;
}
