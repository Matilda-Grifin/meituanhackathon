const DEFAULT_CHIPS = [
  "路线再轻松点",
  "附近加一家咖啡",
  "预算再低一点",
  "换几家本地人爱吃的",
];

type FollowUpChipsProps = {
  onPick: (text: string) => void;
  disabled?: boolean;
};

export function FollowUpChips({ onPick, disabled }: FollowUpChipsProps) {
  return (
    <div className="follow-up-chips" aria-label="猜你想问">
      <p className="follow-up-label">猜你想问</p>
      <div className="follow-up-row">
        {DEFAULT_CHIPS.map((c) => (
          <button
            key={c}
            type="button"
            className="follow-up-chip"
            disabled={disabled}
            onClick={() => onPick(c)}
          >
            {c}
          </button>
        ))}
      </div>
    </div>
  );
}
