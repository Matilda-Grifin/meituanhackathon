/** 流式阶段纯文本展示，避免每个 chunk 全量 Markdown 重解析导致主线程阻塞 */

export function StreamingPlainText({ text }: { text: string }) {
  const src = text.replace(/\r\n/g, "\n");
  if (!src.trim()) return null;
  return <div className="md-body streaming-plain">{src}</div>;
}
