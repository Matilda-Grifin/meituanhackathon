type MobileHeaderView = "chat" | "route";

type MobileHeaderProps = {
  onMenu: () => void;
  view: MobileHeaderView;
  routeEnabled: boolean;
  onViewChange: (view: MobileHeaderView) => void;
};

export function MobileHeader({
  onMenu,
  view,
  routeEnabled,
  onViewChange,
}: MobileHeaderProps) {
  return (
    <header className="mobile-header">
      <div className="mobile-header-spacer" aria-hidden />
      <div className="mobile-header-brand">
        <span className="mobile-logo-icon" aria-hidden>
          评
        </span>
        <h1 className="mobile-header-title">点评管家</h1>
      </div>
      <div className="mobile-header-segmented" role="tablist" aria-label="对话与路线">
        <button
          type="button"
          role="tab"
          className={`mobile-seg-btn${view === "chat" ? " on" : ""}`}
          aria-selected={view === "chat"}
          onClick={() => onViewChange("chat")}
        >
          对话
        </button>
        <button
          type="button"
          role="tab"
          className={`mobile-seg-btn${view === "route" ? " on" : ""}`}
          aria-selected={view === "route"}
          disabled={!routeEnabled}
          onClick={() => routeEnabled && onViewChange("route")}
        >
          路线
        </button>
      </div>
      <button type="button" className="mobile-header-menu" onClick={onMenu} aria-label="历史对话">
        ☰
      </button>
    </header>
  );
}
