export declare const ConnectErrorDetailCodes: {
    readonly AUTH_REQUIRED: "AUTH_REQUIRED";
    readonly AUTH_UNAUTHORIZED: "AUTH_UNAUTHORIZED";
    readonly AUTH_TOKEN_MISSING: "AUTH_TOKEN_MISSING";
    readonly AUTH_TOKEN_MISMATCH: "AUTH_TOKEN_MISMATCH";
    readonly AUTH_TOKEN_NOT_CONFIGURED: "AUTH_TOKEN_NOT_CONFIGURED";
    readonly AUTH_PASSWORD_MISSING: "AUTH_PASSWORD_MISSING";
    readonly AUTH_PASSWORD_MISMATCH: "AUTH_PASSWORD_MISMATCH";
    readonly AUTH_PASSWORD_NOT_CONFIGURED: "AUTH_PASSWORD_NOT_CONFIGURED";
    readonly AUTH_DEVICE_TOKEN_MISMATCH: "AUTH_DEVICE_TOKEN_MISMATCH";
    readonly AUTH_RATE_LIMITED: "AUTH_RATE_LIMITED";
    readonly AUTH_TAILSCALE_IDENTITY_MISSING: "AUTH_TAILSCALE_IDENTITY_MISSING";
    readonly AUTH_TAILSCALE_PROXY_MISSING: "AUTH_TAILSCALE_PROXY_MISSING";
    readonly AUTH_TAILSCALE_WHOIS_FAILED: "AUTH_TAILSCALE_WHOIS_FAILED";
    readonly AUTH_TAILSCALE_IDENTITY_MISMATCH: "AUTH_TAILSCALE_IDENTITY_MISMATCH";
    readonly CONTROL_UI_DEVICE_IDENTITY_REQUIRED: "CONTROL_UI_DEVICE_IDENTITY_REQUIRED";
    readonly DEVICE_IDENTITY_REQUIRED: "DEVICE_IDENTITY_REQUIRED";
    readonly DEVICE_AUTH_INVALID: "DEVICE_AUTH_INVALID";
    readonly PAIRING_REQUIRED: "PAIRING_REQUIRED";
};
export type ConnectErrorDetailCode = (typeof ConnectErrorDetailCodes)[keyof typeof ConnectErrorDetailCodes];
export declare function resolveAuthConnectErrorDetailCode(reason: string | undefined): ConnectErrorDetailCode;
export declare function readConnectErrorDetailCode(details: unknown): string | null;
//# sourceMappingURL=connect-error-details.d.ts.map