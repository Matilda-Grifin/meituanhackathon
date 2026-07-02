import { useEffect, useRef, useState } from "react";

const LIGHT_THEME = {
  startOnLoad: false,
  theme: "base" as const,
  securityLevel: "loose" as const,
  fontFamily: "system-ui, sans-serif",
  themeVariables: {
    primaryColor: "#fff8e1",
    primaryTextColor: "#1a1a1a",
    primaryBorderColor: "#e0e0e0",
    lineColor: "#3d3d3d",
    secondaryColor: "#f5f5f5",
    tertiaryColor: "#ffffff",
    nodeTextColor: "#1a1a1a",
    mainBkg: "#ffffff",
    textColor: "#3d3d3d",
    border1: "#e0e0e0",
    border2: "#d0d0d0",
  },
};

const DARK_THEME = {
  startOnLoad: false,
  theme: "dark" as const,
  securityLevel: "loose" as const,
  fontFamily: "system-ui, sans-serif",
};

export function MermaidBlock({ code, theme = "dark" }: { code: string; theme?: "dark" | "light" }) {
  const ref = useRef<HTMLDivElement>(null);
  const [fallback, setFallback] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const { default: mermaid } = await import("mermaid");
        mermaid.initialize(theme === "light" ? LIGHT_THEME : DARK_THEME);
        const id = `mmd-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
        const { svg } = await mermaid.render(id, code.trim());
        if (!cancelled && ref.current) {
          ref.current.innerHTML = svg;
        }
      } catch {
        if (!cancelled) setFallback(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [code, theme]);

  if (fallback) {
    return (
      <pre className={`md-pre md-mermaid-fallback${theme === "light" ? " md-mermaid-fallback--light" : ""}`}>
        <code>{code}</code>
      </pre>
    );
  }

  return (
    <div
      className={`md-mermaid${theme === "light" ? " md-mermaid--light" : ""}`}
      ref={ref}
      aria-label="mermaid diagram"
    />
  );
}
