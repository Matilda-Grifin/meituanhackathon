export type ChatAttachment = {
    id: string;
    dataUrl: string;
    mimeType: string;
};
export type ChatEventPayload = {
    runId: string;
    sessionKey: string;
    state: "delta" | "final" | "aborted" | "error";
    message?: unknown;
    errorMessage?: string;
};
//# sourceMappingURL=types.d.ts.map