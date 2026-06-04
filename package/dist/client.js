import { buildDeviceAuthPayload } from "./auth/index.js";
import { GATEWAY_CLIENT_MODES, GATEWAY_CLIENT_NAMES, } from "./protocol/index.js";
import { clearDeviceAuthToken, loadDeviceAuthToken, storeDeviceAuthToken } from "./auth/index.js";
import { loadOrCreateDeviceIdentity, signDevicePayload } from "./auth/index.js";
import { generateUUID } from "./uuid.js";
export class GatewayRequestError extends Error {
    gatewayCode;
    details;
    constructor(error) {
        super(error.message);
        this.name = "GatewayRequestError";
        this.gatewayCode = error.code;
        this.details = error.details;
    }
}
export function resolveGatewayErrorDetailCode(error) {
    if (!error || typeof error !== "object" || Array.isArray(error)) {
        return null;
    }
    const code = error.code;
    return typeof code === "string" && code.trim().length > 0 ? code : null;
}
// 4008 = application-defined code (browser rejects 1008 "Policy Violation")
const CONNECT_FAILED_CLOSE_CODE = 4008;
export class GatewayBrowserClient {
    opts;
    ws = null;
    pending = new Map();
    closed = false;
    lastSeq = null;
    connectNonce = null;
    connectSent = false;
    connectTimer = null;
    backoffMs = 800;
    pendingConnectError;
    constructor(opts) {
        this.opts = opts;
    }
    start() {
        this.closed = false;
        this.connect();
    }
    stop() {
        this.closed = true;
        this.ws?.close();
        this.ws = null;
        this.pendingConnectError = undefined;
        this.flushPending(new Error("gateway client stopped"));
    }
    get connected() {
        return this.ws?.readyState === WebSocket.OPEN;
    }
    connect() {
        if (this.closed) {
            return;
        }
        this.ws = new WebSocket(this.opts.url);
        this.ws.addEventListener("open", () => this.queueConnect());
        this.ws.addEventListener("message", (ev) => this.handleMessage(String(ev.data ?? "")));
        this.ws.addEventListener("close", (ev) => {
            const reason = String(ev.reason ?? "");
            const connectError = this.pendingConnectError;
            this.pendingConnectError = undefined;
            this.ws = null;
            this.flushPending(new Error(`gateway closed (${ev.code}): ${reason}`));
            this.opts.onClose?.({ code: ev.code, reason, error: connectError });
            this.scheduleReconnect();
        });
        this.ws.addEventListener("error", () => {
            // ignored; close handler will fire
        });
    }
    scheduleReconnect() {
        if (this.closed) {
            return;
        }
        const delay = this.backoffMs;
        this.backoffMs = Math.min(this.backoffMs * 1.7, 15_000);
        window.setTimeout(() => this.connect(), delay);
    }
    flushPending(err) {
        for (const [, p] of this.pending) {
            p.reject(err);
        }
        this.pending.clear();
    }
    async sendConnect() {
        if (this.connectSent) {
            return;
        }
        this.connectSent = true;
        if (this.connectTimer !== null) {
            window.clearTimeout(this.connectTimer);
            this.connectTimer = null;
        }
        // crypto.subtle is only available in secure contexts (HTTPS, localhost).
        // Over plain HTTP, we skip device identity and fall back to token-only auth.
        // Gateways may reject this unless gateway.controlUi.allowInsecureAuth is enabled.
        const isSecureContext = typeof crypto !== "undefined" && !!crypto.subtle;
        const scopes = ["operator.admin", "operator.approvals", "operator.pairing"];
        const role = "operator";
        let deviceIdentity = null;
        let canFallbackToShared = false;
        let authToken = this.opts.token;
        if (isSecureContext) {
            deviceIdentity = await loadOrCreateDeviceIdentity();
            const storedToken = loadDeviceAuthToken({
                deviceId: deviceIdentity.deviceId,
                role,
            })?.token;
            authToken = storedToken ?? this.opts.token;
            canFallbackToShared = Boolean(storedToken && this.opts.token);
        }
        const auth = authToken || this.opts.password
            ? {
                token: authToken,
                password: this.opts.password,
            }
            : undefined;
        let device;
        if (isSecureContext && deviceIdentity) {
            const signedAtMs = Date.now();
            const nonce = this.connectNonce ?? "";
            const payload = buildDeviceAuthPayload({
                deviceId: deviceIdentity.deviceId,
                clientId: this.opts.clientName ?? GATEWAY_CLIENT_NAMES.CONTROL_UI,
                clientMode: this.opts.mode ?? GATEWAY_CLIENT_MODES.WEBCHAT,
                role,
                scopes,
                signedAtMs,
                token: authToken ?? null,
                nonce,
            });
            const signature = await signDevicePayload(deviceIdentity.privateKey, payload);
            device = {
                id: deviceIdentity.deviceId,
                publicKey: deviceIdentity.publicKey,
                signature,
                signedAt: signedAtMs,
                nonce,
            };
        }
        const params = {
            minProtocol: 3,
            maxProtocol: 3,
            client: {
                id: this.opts.clientName ?? GATEWAY_CLIENT_NAMES.CONTROL_UI,
                version: this.opts.clientVersion ?? "dev",
                platform: this.opts.platform ?? navigator.platform ?? "web",
                mode: this.opts.mode ?? GATEWAY_CLIENT_MODES.WEBCHAT,
                instanceId: this.opts.instanceId,
            },
            role,
            scopes,
            device,
            caps: [],
            auth,
            userAgent: navigator.userAgent,
            locale: navigator.language,
        };
        void this.request("connect", params)
            .then((hello) => {
            if (hello?.auth?.deviceToken && deviceIdentity) {
                storeDeviceAuthToken({
                    deviceId: deviceIdentity.deviceId,
                    role: hello.auth.role ?? role,
                    token: hello.auth.deviceToken,
                    scopes: hello.auth.scopes ?? [],
                });
            }
            this.backoffMs = 800;
            this.opts.onHello?.(hello);
        })
            .catch((err) => {
            if (err instanceof GatewayRequestError) {
                this.pendingConnectError = {
                    code: err.gatewayCode,
                    message: err.message,
                    details: err.details,
                };
            }
            else {
                this.pendingConnectError = undefined;
            }
            if (canFallbackToShared && deviceIdentity) {
                clearDeviceAuthToken({ deviceId: deviceIdentity.deviceId, role });
            }
            this.ws?.close(CONNECT_FAILED_CLOSE_CODE, "connect failed");
        });
    }
    handleMessage(raw) {
        let parsed;
        try {
            parsed = JSON.parse(raw);
        }
        catch {
            return;
        }
        const frame = parsed;
        if (frame.type === "event") {
            const evt = parsed;
            if (evt.event === "connect.challenge") {
                const payload = evt.payload;
                const nonce = payload && typeof payload.nonce === "string" ? payload.nonce : null;
                if (nonce) {
                    this.connectNonce = nonce;
                    void this.sendConnect();
                }
                return;
            }
            const seq = typeof evt.seq === "number" ? evt.seq : null;
            if (seq !== null) {
                if (this.lastSeq !== null && seq > this.lastSeq + 1) {
                    this.opts.onGap?.({ expected: this.lastSeq + 1, received: seq });
                }
                this.lastSeq = seq;
            }
            try {
                this.opts.onEvent?.(evt);
            }
            catch (err) {
                console.error("[gateway] event handler error:", err);
            }
            return;
        }
        if (frame.type === "res") {
            const res = parsed;
            const pending = this.pending.get(res.id);
            if (!pending) {
                return;
            }
            this.pending.delete(res.id);
            if (res.ok) {
                pending.resolve(res.payload);
            }
            else {
                pending.reject(new GatewayRequestError({
                    code: res.error?.code ?? "UNAVAILABLE",
                    message: res.error?.message ?? "request failed",
                    details: res.error?.details,
                }));
            }
            return;
        }
    }
    request(method, params) {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            return Promise.reject(new Error("gateway not connected"));
        }
        const id = generateUUID();
        const frame = { type: "req", id, method, params };
        const p = new Promise((resolve, reject) => {
            this.pending.set(id, { resolve: (v) => resolve(v), reject });
        });
        this.ws.send(JSON.stringify(frame));
        return p;
    }
    queueConnect() {
        this.connectNonce = null;
        this.connectSent = false;
        if (this.connectTimer !== null) {
            window.clearTimeout(this.connectTimer);
        }
        this.connectTimer = window.setTimeout(() => {
            void this.sendConnect();
        }, 750);
    }
}
//# sourceMappingURL=client.js.map