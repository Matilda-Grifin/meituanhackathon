type MobileNoticeProps = {
  message: string;
};

export function MobileNotice({ message }: MobileNoticeProps) {
  if (!message.trim()) return null;
  return (
    <div className="mobile-notice" role="status" aria-live="polite">
      {message}
    </div>
  );
}
