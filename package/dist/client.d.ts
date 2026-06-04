import { type GatewayClientMode, type GatewayClientName } from "./protocol/index.js";
export type GatewayEventFrame = {
    type: "event";
    event: string;
    payload?: unknown;
    seq?: number;
    stateVersion?: {
        presence: number;
        health: number;
    };
};
export type GatewayResponseFrame = {
    type: "res";
    id: string;
    ok: boolean;
    payload?: unknown;
    error?: {
        code: string;
        message: string;
        details?: unknown;
    };
};
export type GatewayErrorInfo = {
    code: string;
    message: string;
    details?: unknown;
};
export declare class GatewayRequestError extends Error {
    readonly gatewayCode: string;
    readonly details?: unknown;
    constructor(error: GatewayErrorInfo);
}
export declare function resolveGatewayErrorDetailCode(error: {
    details?: unknown;
} | null | undefined): string | null;
export type GatewayHelloOk = {
    type: "hello-ok";
    protocol: number;
    server?: {
        version?: string;
        connId?: string;
    };
    features?: {
        methods?: string[];
        events?: string[];
    };
    snapshot?: unknown;
    auth?: {
        deviceToken?: string;
        role?: string;
        scopes?: string[];
        issuedAtMs?: number;
    };
    policy?: {
        tickIntervalMs?: number;
    };
};
export type GatewayBrowserClientOptions = {
    url: string;
    token?: string;
    password?: string;
    clientName?: GatewayClientName;
    clientVersion?: string;
    platform?: string;
    mode?: GatewayClientMode;
    instanceId?: string;
    onHello?: (hello: GatewayHelloOk) => void;
    onEvent?: (evt: GatewayEventFrame) => void;
    onClose?: (info: {
        code: number;
        reason: string;
        error?: GatewayErrorInfo;
    }) => void;
    onGap?: (info: {
        expected: number;
        received: number;
    }) => void;
};
export declare class GatewayBrowserClient {
    private opts;
    private ws;
    private pending;
    private closed;
    private lastSeq;
    private connectNonce;
    private connectSent;
    private connectTimer;
    private backoffMs;
    private pendingConnectError;
    constructor(opts: GatewayBrowserClientOptions);
    start(): void;
    stop(): void;
    get connected(): boolean;
    private connect;
    private scheduleReconnect;
    private flushPending;
    private sendConnect;
    private handleMessage;
    request<T = unknown>(method: string, params?: unknown): Promise<T>;
    private queueConnect;
}
//# sourceMappingURL=client.d.ts.map