/** App 壳不展示「动线示意」Mermaid 段（改由 RouteSheet 地图承载） */
export function stripMovementDiagramSection(text: string): string {
  const src = text.replace(/\r\n/g, "\n");
  const stripped = src.replace(
    /^#{1,3}\s*动线(?:示意|可视化)?[^\n]*\n(?:[\s\S]*?)(?=^##\s|\Z)/gm,
    "",
  );
  return stripped.replace(/\n{3,}/g, "\n\n").trimEnd();
}

/** Mermaid 仅在 fence 闭合后渲染，避免流式/半截块触发异步 render */

export function isMermaidFenceComplete(fullSource: string): boolean {
  const src = fullSource.replace(/\r\n/g, "\n");
  const open = src.lastIndexOf("```mermaid");
  if (open < 0) return false;
  const afterOpen = src.slice(open + "```mermaid".length);
  return afterOpen.includes("```");
}
