type MobileHeaderProps = {
  onMenu: () => void;
};

export function MobileHeader({ onMenu }: MobileHeaderProps) {
  return (
    <header className="mobile-header">
      <div className="mobile-header-spacer" aria-hidden />
      <div className="mobile-header-brand">
        <span className="mobile-logo-icon" aria-hidden>
          评
        </span>
        <h1 className="mobile-header-title">点评管家</h1>
      </div>
      <button type="button" className="mobile-header-menu" onClick={onMenu} aria-label="历史对话">
        ☰
      </button>
    </header>
  );
}
