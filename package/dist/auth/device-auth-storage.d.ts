export type DeviceAuthEntry = {
    token: string;
    role: string;
    scopes: string[];
    updatedAtMs: number;
};
export type DeviceAuthStore = {
    version: 1;
    deviceId: string;
    tokens: Record<string, DeviceAuthEntry>;
};
export declare function normalizeDeviceAuthRole(role: string): string;
export declare function normalizeDeviceAuthScopes(scopes: string[] | undefined): string[];
export declare function loadDeviceAuthToken(params: {
    deviceId: string;
    role: string;
}): DeviceAuthEntry | null;
export declare function storeDeviceAuthToken(params: {
    deviceId: string;
    role: string;
    token: string;
    scopes?: string[];
}): DeviceAuthEntry;
export declare function clearDeviceAuthToken(params: {
    deviceId: string;
    role: string;
}): void;
//# sourceMappingURL=device-auth-storage.d.ts.map