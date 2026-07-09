/**
 * intake footer 解析 + orphan 泡判定
 * Run: npm run test:intake-footer
 */
import {
  extractIntakeFooterLine,
  extractIntakeOnlyText,
  extractIntakeRemainderText,
  hasIntakeQuestions,
  isIntakeFooterOnlyBubble,
} from "../src/intakeParse.ts";

const sample = `已确认需求摘要...

1. 请问您计划什么时候出发？
A. 今天
B. 明天

2. 类型？
A. 自然
B. 人文

或直接回复：全部用默认（默认：从闵行区出发，明天上午出发，游玩一天）`;

const footer =
  "或直接回复：全部用默认（默认：从闵行区出发，明天上午出发，游玩一天）";

let failed = 0;
function fail(msg: string) {
  console.error(`FAIL ${msg}`);
  failed++;
}

const only = extractIntakeOnlyText(sample);
if (!only.includes("或直接回复")) {
  fail(`intakeOnly should include footer, got tail: ${only.slice(-80)}`);
}

const rem = extractIntakeRemainderText(sample);
if (rem.trim()) {
  fail(`remainder should be empty after parse fix, got: ${JSON.stringify(rem)}`);
}

const extracted = extractIntakeFooterLine(sample);
if (!extracted.includes("全部用默认")) {
  fail(`extractIntakeFooterLine: ${extracted}`);
}

if (!isIntakeFooterOnlyBubble(footer)) {
  fail("footer-only text should be orphan bubble");
}

if (isIntakeFooterOnlyBubble(sample)) {
  fail("full intake should not be footer-only");
}

if (!hasIntakeQuestions(only)) {
  fail("intakeOnly should still have questions");
}

if (failed) {
  console.error(`\n${failed} case(s) failed`);
  process.exit(1);
}
console.log("ok: intake footer parse 5 checks");
