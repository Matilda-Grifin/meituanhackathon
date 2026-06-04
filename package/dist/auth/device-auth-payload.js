export function buildDeviceAuthPayload(params) {
    const scopes = params.scopes.join(",");
    const token = params.token ?? "";
    return [
        "v2",
        params.deviceId,
        params.clientId,
        params.clientMode,
        params.role,
        scopes,
        String(params.signedAtMs),
        token,
        params.nonce,
    ].join("|");
}
//# sourceMappingURL=device-auth-payload.js.map