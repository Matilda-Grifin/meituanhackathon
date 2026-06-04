import { useEffect, useRef, useState } from "react";

let mermaidInit = false;

export function MermaidBlock({ code }: { code: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [fallback, setFallback] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const { default: mermaid } = await import("mermaid");
        if (!mermaidInit) {
          mermaid.initialize({
            startOnLoad: false,
            theme: "dark",
            securityLevel: "loose",
            fontFamily: "system-ui, sans-serif",
          });
          mermaidInit = true;
        }
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
  }, [code]);

  if (fallback) {
    return (
      <pre className="md-pre md-mermaid-fallback">
        <code>{code}</code>
      </pre>
    );
  }

  return <div className="md-mermaid" ref={ref} aria-label="mermaid diagram" />;
}
