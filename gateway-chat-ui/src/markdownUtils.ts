/** Mermaid 仅在 fence 闭合后渲染，避免流式/半截块触发异步 render */

export function isMermaidFenceComplete(fullSource: string): boolean {
  const src = fullSource.replace(/\r\n/g, "\n");
  const open = src.lastIndexOf("```mermaid");
  if (open < 0) return false;
  const afterOpen = src.slice(open + "```mermaid".length);
  return afterOpen.includes("```");
}
