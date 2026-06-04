import type { IntakeBlock } from "./intakeParse";

export type IntakeCardProps = {
  intro?: string;
  blocks: IntakeBlock[];
  selections: Record<number, string>;
  custom: Record<number, string>;
  followUp: Record<number, string>;
  locked: boolean;
  showDefault?: boolean;
  canSubmit: boolean;
  uiLocked: boolean;
  onSelect: (n: number, letter: string, isOther: boolean, hasFollowUp: boolean) => void;
  onCustomChange: (n: number, value: string) => void;
  onFollowUpChange: (n: number, value: string) => void;
  onSubmit: () => void;
  onDefault: () => void;
};

/** 问卷卡片：气泡 + 可点击 pill（不走 Markdown） */
export function IntakeCard({
  intro,
  blocks,
  selections,
  custom,
  followUp,
  locked,
  showDefault,
  canSubmit,
  uiLocked,
  onSelect,
  onCustomChange,
  onFollowUpChange,
  onSubmit,
  onDefault,
}: IntakeCardProps) {
  if (!blocks.length) return null;

  return (
    <div className={`intake-bubble${locked ? " intake-bubble--submitted" : ""}`} aria-label={locked ? "槽位问卷（已提交）" : "槽位问卷"}>
      {intro ? <p className="intake-bubble-intro">{intro}</p> : null}
      {blocks.map((b) => (
        <div key={b.n} className="intake-bubble-q">
          <p className="intake-bubble-qtext">{b.title || `第 ${b.n} 题`}</p>
          <div className="intake-bubble-options" role="group" aria-label={`第 ${b.n} 题选项`}>
            {b.options.map((o) => {
              const on = selections[b.n] === o.letter;
              return (
                <button
                  key={`${b.n}-${o.letter}`}
                  type="button"
                  className={`intake-pill${on ? " selected" : ""}`}
                  title={o.hint}
                  disabled={uiLocked || locked}
                  aria-pressed={on}
                  onClick={() => {
                    if (locked || uiLocked) return;
                    onSelect(b.n, o.letter, o.isOther, Boolean(o.followUp));
                  }}
                >
                  <span className="intake-pill-letter">{o.letter}</span>
                  <span className="intake-pill-text">{o.hint || o.letter}</span>
                </button>
              );
            })}
          </div>
          {!locked && b.options.some((o) => o.letter === selections[b.n] && o.isOther) ? (
            <input
              type="text"
              className="intake-bubble-input"
              placeholder="选「其他」后填写"
              value={custom[b.n] ?? ""}
              disabled={uiLocked}
              onChange={(e) => onCustomChange(b.n, e.target.value)}
            />
          ) : null}
          {!locked &&
          (() => {
            const letter = selections[b.n];
            const opt = b.options.find((o) => o.letter === letter);
            return opt?.followUp;
          })() ? (
            <input
              type="text"
              className="intake-bubble-input"
              placeholder={
                b.options.find((o) => o.letter === selections[b.n])?.followUp?.placeholder ?? "选填补充"
              }
              value={followUp[b.n] ?? ""}
              disabled={uiLocked}
              onChange={(e) => onFollowUpChange(b.n, e.target.value)}
            />
          ) : null}
        </div>
      ))}
      {locked ? (
        <p className="intake-bubble-locked-hint">已确认，选项不可修改</p>
      ) : (
        <>
          <p className="intake-bubble-edit-hint">点选各题答案，确认前可随时改选</p>
          <div className="intake-bubble-actions">
            {showDefault ? (
              <button type="button" className="intake-action-btn intake-action-default" disabled={uiLocked} onClick={onDefault}>
                全部用默认
              </button>
            ) : null}
            <button
              type="button"
              className="intake-action-btn intake-action-submit"
              disabled={!canSubmit || uiLocked}
              onClick={onSubmit}
            >
              确认提交
            </button>
          </div>
        </>
      )}
    </div>
  );
}
