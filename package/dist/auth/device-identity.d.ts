export type DeviceIdentity = {
    deviceId: string;
    publicKey: string;
    privateKey: string;
};
export declare const STORAGE_KEY = "openclaw-device-identity-v1";
export declare function loadOrCreateDeviceIdentity(): Promise<DeviceIdentity>;
export declare function signDevicePayload(privateKeyBase64Url: string, payload: string): Promise<string>;
//# sourceMappingURL=device-identity.d.ts.map