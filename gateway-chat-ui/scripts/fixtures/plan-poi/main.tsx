import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { PlanMessageBody } from "../../../src/components/PlanMessageBody";
import { splitPlanWithPois } from "../../../src/planPoiEmbed";
import { PLAN_POI_FIXTURES } from "./fixtures";
import "../../../src/App.css";
import "../../../src/tokens.css";

function App() {
  return (
    <div className="plan-poi-fixture-root" style={{ padding: 16, maxWidth: 420 }}>
      <h1 style={{ fontSize: 18, marginBottom: 16 }}>Plan POI embed fixtures</h1>
      {PLAN_POI_FIXTURES.map((fx) => {
        const segments = splitPlanWithPois(fx.plan, fx.pois);
        const markdownText = segments
          .filter((s): s is { kind: "text"; text: string } => s.kind === "text")
          .map((s) => s.text)
          .join("\n");
        const poiCount = segments.filter((s) => s.kind === "poi").length;
        return (
          <section
            key={fx.id}
            data-testid={`fixture-${fx.id}`}
            data-poi-count={poiCount}
            data-markdown-text={markdownText}
            style={{
              marginBottom: 24,
              border: "1px solid #eee",
              borderRadius: 12,
              padding: 12,
            }}
          >
            <h2 style={{ fontSize: 14, margin: "0 0 8px" }}>{fx.label}</h2>
            <PlanMessageBody text={fx.plan} pois={fx.pois} userLocation={null} />
          </section>
        );
      })}
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
