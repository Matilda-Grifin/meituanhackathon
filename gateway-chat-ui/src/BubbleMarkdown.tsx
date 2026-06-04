import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { MermaidBlock } from "./MermaidBlock";
import { isMermaidFenceComplete } from "./markdownUtils";

export function BubbleMarkdown({ text }: { text: string }): ReactNode {
  const src = text.replace(/\r\n/g, "\n");
  if (!src.trim()) return null;
  const mermaidOk = isMermaidFenceComplete(src);

  return (
    <div className="md-body markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          img: ({ src: href, alt }) => (
            <img
              className="md-img"
              src={href ?? ""}
              alt={alt ?? "配图"}
              loading="lazy"
              referrerPolicy="no-referrer"
            />
          ),
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          ),
          table: ({ children }) => (
            <div className="md-table-wrap">
              <table>{children}</table>
            </div>
          ),
          code: ({ className, children }) => {
            const body = String(children).replace(/\n$/, "");
            const lang = /language-(\w+)/.exec(className ?? "")?.[1];
            if (lang === "mermaid") {
              if (!mermaidOk) {
                return (
                  <pre className="md-pre md-mermaid-pending">
                    <code>{body}</code>
                  </pre>
                );
              }
              return <MermaidBlock code={body} />;
            }
            if (className) {
              return <code className={className}>{children}</code>;
            }
            return <code className="md-inline-code">{children}</code>;
          },
          pre: ({ children }) => <pre className="md-pre">{children}</pre>,
        }}
      >
        {src}
      </ReactMarkdown>
    </div>
  );
}
