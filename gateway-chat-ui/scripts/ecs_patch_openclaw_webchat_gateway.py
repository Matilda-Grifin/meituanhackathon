#!/usr/bin/env python3
"""
Patch OpenClaw gateway dist so webchat (e.g. client webchat-ui) honors
gateway.controlUi.allowInsecureAuth + dangerouslyDisableDeviceAuth
the same way Control UI does — fixes chat.send missing operator.write
when browser is on plain http://公网IP (no SubtleCrypto / no device identity).

Upstream: controlUi flags were only applied when isControlUi; webchat never
got allowInsecureAuthConfigured / allowBypass, so scopes were always cleared.

Re-run after `npm i -g openclaw` upgrades (patch is overwritten).
"""
from __future__ import annotations

from pathlib import Path

TARGET = Path("/usr/lib/node_modules/openclaw/dist/message-handler-Cc2t2lqw.js")


def main() -> None:
    p = TARGET
    s = p.read_text(encoding="utf-8")
    original = s

    old1 = """	const allowInsecureAuthConfigured = params.isControlUi && params.controlUiConfig?.allowInsecureAuth === true;
	const dangerouslyDisableDeviceAuth = params.isControlUi && params.controlUiConfig?.dangerouslyDisableDeviceAuth === true;"""
    new1 = """	const allowInsecureAuthConfigured = (params.isControlUi || params.isWebchat) && params.controlUiConfig?.allowInsecureAuth === true;
	const dangerouslyDisableDeviceAuth = (params.isControlUi || params.isWebchat) && params.controlUiConfig?.dangerouslyDisableDeviceAuth === true;"""
    if old1 not in s:
        raise SystemExit("resolveControlUiAuthPolicy block not found (openclaw version mismatch?)")
    s = s.replace(old1, new1, 1)

    old2 = """const controlUiAuthPolicy = resolveControlUiAuthPolicy({
					isControlUi,
					controlUiConfig: configSnapshot.gateway?.controlUi,
					deviceRaw
				});"""
    new2 = """const controlUiAuthPolicy = resolveControlUiAuthPolicy({
					isControlUi,
					isWebchat,
					controlUiConfig: configSnapshot.gateway?.controlUi,
					deviceRaw
				});"""
    if old2 not in s:
        raise SystemExit("resolveControlUiAuthPolicy call not found")
    s = s.replace(old2, new2, 1)

    old3 = """	if (params.isControlUi && params.controlUiAuthPolicy.allowBypass && params.role === "operator") return { kind: "allow" };"""
    new3 = """	if ((params.isControlUi || params.isWebchat) && params.controlUiAuthPolicy.allowBypass && params.role === "operator") return { kind: "allow" };"""
    if old3 not in s:
        raise SystemExit("evaluateMissingDeviceIdentity allowBypass line not found")
    s = s.replace(old3, new3, 1)

    old4 = """					const decision = evaluateMissingDeviceIdentity({
						hasDeviceIdentity: Boolean(device),
						role,
						isControlUi,
						controlUiAuthPolicy,
						trustedProxyAuthOk,
						sharedAuthOk,
						authOk,
						hasSharedAuth,
						isLocalClient
					});"""
    new4 = """					const decision = evaluateMissingDeviceIdentity({
						hasDeviceIdentity: Boolean(device),
						role,
						isControlUi,
						isWebchat,
						controlUiAuthPolicy,
						trustedProxyAuthOk,
						sharedAuthOk,
						authOk,
						hasSharedAuth,
						isLocalClient
					});"""
    if old4 not in s:
        raise SystemExit("evaluateMissingDeviceIdentity call not found")
    s = s.replace(old4, new4, 1)

    old5 = """					const preserveInsecureLocalControlUiScopes = isControlUi && controlUiAuthPolicy.allowInsecureAuthConfigured && isLocalClient && (authMethod === "token" || authMethod === "password");"""
    new5 = """					const preserveInsecureLocalControlUiScopes = controlUiAuthPolicy.allowInsecureAuthConfigured && (authMethod === "token" || authMethod === "password") && (isWebchat || isControlUi && isLocalClient);"""
    if old5 not in s:
        raise SystemExit("preserveInsecureLocalControlUiScopes line not found")
    s = s.replace(old5, new5, 1)

    bak = p.with_suffix(".js.bak-gateway-chat-ui")
    if not bak.exists():
        bak.write_text(original, encoding="utf-8")
    p.write_text(s, encoding="utf-8")
    print("patched:", p)
    print("backup:", bak)


if __name__ == "__main__":
    main()
