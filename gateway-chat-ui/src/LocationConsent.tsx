import { useState } from "react";
import { isSecureContextForGeo } from "./location";

type Props = {
  open: boolean;
  busy: boolean;
  error: string;
  onAgree: () => void;
  onDeny: () => void;
};

export function LocationConsentModal({ open, busy, error, onAgree, onDeny }: Props) {
  const [denyConfirm, setDenyConfirm] = useState(false);

  if (!open) return null;

  const secure = isSecureContextForGeo();

  return (
    <div className="location-consent-backdrop" role="dialog" aria-modal="true" aria-labelledby="loc-consent-title">
      <div className="location-consent-card">
        <h2 id="loc-consent-title">位置信息说明</h2>
        <p>
          为推荐更准确的周边出行与动线，本页需要获取您的<strong>大致位置</strong>（优先使用浏览器定位；无法使用时用
          访问 IP 推测城市/区域）。
        </p>
        <ul className="location-consent-list">
          <li>数据仅用于本次对话内的行程规划，不会用于其他用途。</li>
          <li>点击「同意」后，系统会向助手发送一条<strong>不展示在聊天区</strong>的位置说明，便于少问重复问题。</li>
          <li>
            定位耗时：仅 IP 约 1 秒内；HTTPS 下浏览器 GPS + 逆地理通常 2～6 秒（需您点允许）。新建对话后会自动注入，发首条消息前最多再等约 5 秒。
          </li>
          {!secure ? (
            <li className="location-consent-warn">
              当前为 HTTP 页面，浏览器可能<strong>无法</strong>提供精确定位，将主要依赖 IP 推测；请用 https:// 访问本页。
            </li>
          ) : null}
        </ul>
        {error ? (
          <p className="location-consent-error" role="alert">
            {error}
          </p>
        ) : null}
        <div className="location-consent-actions">
          <button type="button" className="chip primary" disabled={busy} onClick={() => void onAgree()}>
            {busy ? "正在获取位置…" : "同意"}
          </button>
          <button
            type="button"
            className="chip ghost"
            disabled={busy}
            onClick={() => {
              if (!denyConfirm) {
                setDenyConfirm(true);
                return;
              }
              onDeny();
            }}
          >
            {denyConfirm ? "确认不同意" : "不同意"}
          </button>
        </div>
        {denyConfirm && !busy ? (
          <p className="location-consent-deny-hint">不同意将无法使用本页功能；刷新页面后可重新选择。</p>
        ) : null}
      </div>
    </div>
  );
}
