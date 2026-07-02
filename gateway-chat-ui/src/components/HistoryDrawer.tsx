type ChatThread = {
  id: string;
  sessionKey: string;
  title: string;
  updatedAt: number;
  modelId?: string;
};

type HistoryDrawerProps = {
  open: boolean;
  threads: ChatThread[];
  activeThreadId: string;
  creatingThread: boolean;
  uiLocked: boolean;
  onClose: () => void;
  onSelect: (id: string) => void;
  onNew: () => void;
  onClear: () => void;
};

export function HistoryDrawer({
  open,
  threads,
  activeThreadId,
  creatingThread,
  uiLocked,
  onClose,
  onSelect,
  onNew,
  onClear,
}: HistoryDrawerProps) {
  if (!open) return null;

  return (
    <div className="history-drawer-root" role="presentation">
      <button type="button" className="history-drawer-backdrop" aria-label="关闭" onClick={onClose} />
      <aside className="history-drawer" aria-label="历史对话">
        <div className="history-drawer-head">
          <span className="history-drawer-title">历史对话</span>
          <button type="button" className="history-drawer-close" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </div>
        <div className="history-drawer-actions">
          <button
            type="button"
            className="history-drawer-new"
            onClick={onNew}
            disabled={creatingThread || uiLocked}
          >
            ＋ 新对话
          </button>
          <button
            type="button"
            className="history-drawer-clear ghost"
            disabled={uiLocked}
            onClick={onClear}
          >
            清空
          </button>
        </div>
        <ul className="history-drawer-list">
          {threads.length === 0 ? (
            <li className="history-drawer-empty">暂无历史，发送首条消息开始</li>
          ) : (
            threads.map((t) => (
              <li key={t.id}>
                <button
                  type="button"
                  className={`history-drawer-item${t.id === activeThreadId ? " active" : ""}`}
                  onClick={() => onSelect(t.id)}
                >
                  <span className="history-drawer-item-title">{t.title || "新对话"}</span>
                </button>
              </li>
            ))
          )}
        </ul>
      </aside>
    </div>
  );
}
