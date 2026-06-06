/** Quick sanity checks for response-speed + streaming markdown helpers */
import { shouldEarlyFlushAck, isAckMessage, presentChatRows } from "../src/presentChatRows";
import { cleanIntakeDisplayText } from "../src/intakeParse";
import { labelForTool, isHiddenProcessStepMsg, detailFromToolArgs } from "../src/toolProgress";
import { shouldStreamMarkdown, findStableMarkdownBoundary } from "../src/streamMarkdown";
import { isWarmupMessage, shouldStartWarmup } from "../src/sessionWarmup";

let passed = 0;
let failed = 0;

function ok(name: string, cond: boolean) {
  if (cond) {
    passed += 1;
    console.log(`OK ${name}`);
  } else {
    failed += 1;
    console.error(`FAIL ${name}`);
  }
}

ok("ack flush without period", shouldEarlyFlushAck("好的，正在并行查广州天气并检索地点"));
ok("ack flush short", shouldEarlyFlushAck("好的"));
ok("no flush for plan", !shouldEarlyFlushAck("# 广州\n\n## 行程速览\n" + "x".repeat(500)));
ok("isAckMessage", isAckMessage("好的，正在并行查天气并检索地点"));
ok("read label", labelForTool("read") === "加载行程规划指引");
ok("hide agent json", isHiddenProcessStepMsg('[agent] {"runId":"abc","stream":"item"}'));
ok(
  "search detail",
  detailFromToolArgs("lifecare__lifecare_search_places", {
    data: { arguments: { city: "广州", keyword: "美食" } },
  }) === "正在搜索「广州 美食」",
);
ok("warmup message", isWarmupMessage("[系统预热] 请读取"));
ok(
  "should start warmup empty session",
  shouldStartWarmup({ sessionKey: "agent:main:main", hasVisibleUserMessage: false, warmupState: "idle" }),
);
ok(
  "stream md plan",
  shouldStreamMarkdown("# 广州周末游\n\n" + "正文".repeat(200)),
);
ok(
  "no stream md ack",
  !shouldStreamMarkdown("好的，正在并行查广州天气并检索美食与景点"),
);
ok(
  "stable boundary",
  findStableMarkdownBoundary("# Title\n\nParagraph one.\n\nPartial") >= "# Title\n\nParagraph one.\n\n".length,
);
ok(
  "strip intake asterisks",
  cleanIntakeDisplayText("** 本周末 (6月7日-8日)") === "本周末 (6月7日-8日)",
);
ok(
  "hide ack bubbles",
  presentChatRows([
    { id: "u1", role: "user", text: "去上海" },
    { id: "a1", role: "assistant", text: "收到！正在并行查上海天气并检索景点与餐饮…" },
    { id: "a2", role: "assistant", text: "收到" },
  ]).filter((r) => r.role === "assistant").length === 0,
);

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed > 0 ? 1 : 0);
