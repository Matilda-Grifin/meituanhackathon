import { memo, useDeferredValue, useEffect, useState } from "react";
import { BubbleMarkdown } from "./BubbleMarkdown";
import { findStableMarkdownBoundary } from "./streamMarkdown";

const StableMd = memo(function StableMd({ text }: { text: string }) {
  return <BubbleMarkdown text={text} />;
});

export function StreamingMarkdown({ text }: { text: string }) {
  const deferred = useDeferredValue(text);
  const [stableEnd, setStableEnd] = useState(0);

  useEffect(() => {
    if (!deferred.trim()) {
      setStableEnd(0);
      return;
    }
    const boundary = findStableMarkdownBoundary(deferred);
    setStableEnd((prev) => (boundary > prev ? boundary : prev));
  }, [deferred]);

  const stable = deferred.slice(0, stableEnd);
  const tail = deferred.slice(stableEnd);

  return (
    <div className="md-body markdown-body streaming-md">
      {stable ? <StableMd text={stable} /> : null}
      {tail ? <BubbleMarkdown text={tail} /> : null}
    </div>
  );
}
