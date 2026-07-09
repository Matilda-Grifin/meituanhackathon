/**
 * formatBPhaseSearchLine 回归 —— 区域词已含「附近/周边/一带」时不重复拼「附近」
 * Run: npm run test:progress-copy
 */
import {
  extractBPhaseRegion,
  formatBPhaseSearchLine,
  mapBPhaseProgress,
  mapFollowUpProgress,
  B_PHASE_STAGE_MS,
} from "../src/friendlyProgress.ts";

const cases: { region: string; want: string }[] = [
  { region: "", want: "🔍 搜罗附近好吃的/好逛的…" },
  { region: "附近玩", want: "🔍 搜罗附近玩好吃的/好逛的…" },
  { region: "去周边玩", want: "🔍 搜罗去周边玩好吃的/好逛的…" },
  { region: "闵行附近", want: "🔍 搜罗闵行附近好吃的/好逛的…" },
  { region: "杭州", want: "🔍 搜罗杭州附近好吃的/好逛的…" },
  { region: "周边", want: "🔍 搜罗周边好吃的/好逛的…" },
];

let failed = 0;
for (const { region, want } of cases) {
  const got = formatBPhaseSearchLine(region);
  if (got !== want) {
    console.error(`FAIL region=${JSON.stringify(region)}\n  got:  ${got}\n  want: ${want}`);
    failed++;
  }
}

const fromUser = extractBPhaseRegion("我想附近玩，带娃轻松点", "上海");
const line = mapBPhaseProgress(0, "上海", "我想附近玩，带娃轻松点");
if (/附近.*附近/.test(line)) {
  console.error(`FAIL duplicate 附近 in user echo: ${line}`);
  failed++;
}
if (line !== formatBPhaseSearchLine(fromUser)) {
  console.error(`FAIL mapBPhaseProgress mismatch: ${line}`);
  failed++;
}

const follow2 = mapFollowUpProgress(B_PHASE_STAGE_MS + 100);
if (follow2 !== "🔍 看看有没有更合你心意的…") {
  console.error(`FAIL mapFollowUpProgress stage2: ${follow2}`);
  failed++;
}
if (/附近加一家咖啡/.test(follow2)) {
  console.error(`FAIL mapFollowUpProgress must not echo user text: ${follow2}`);
  failed++;
}

if (failed) {
  console.error(`\n${failed} case(s) failed`);
  process.exit(1);
}
console.log("ok: friendly progress copy", cases.length + 1, "checks");
