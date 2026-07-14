type MobileHeaderProps = {
  onMenu: () => void;
};

export function MobileHeader({ onMenu }: MobileHeaderProps) {
  return (
    <header className="mobile-header">
      <div className="mobile-header-spacer" aria-hidden />
      <div className="mobile-header-brand">
        <img
          className="mobile-logo-icon"
          src="/xiaoxing-logo.png"
          alt=""
          width={28}
          height={28}
          decoding="async"
        />
        <h1 className="mobile-header-title">小星</h1>
      </div>
      <button type="button" className="mobile-header-menu" onClick={onMenu} aria-label="历史对话">
        ☰
      </button>
    </header>
  );
}
