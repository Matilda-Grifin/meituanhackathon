// Main client export
export { GatewayBrowserClient, GatewayRequestError, resolveGatewayErrorDetailCode, } from "./client.js";
// Utility exports
export { generateUUID } from "./uuid.js";
// Auth exports
export { buildDeviceAuthPayload, clearDeviceAuthToken, loadDeviceAuthToken, normalizeDeviceAuthRole, normalizeDeviceAuthScopes, storeDeviceAuthToken, loadOrCreateDeviceIdentity, signDevicePayload, } from "./auth/index.js";
// Protocol exports
export { GATEWAY_CLIENT_IDS, GATEWAY_CLIENT_MODES, GATEWAY_CLIENT_NAMES, GATEWAY_CLIENT_CAPS, normalizeGatewayClientId, normalizeGatewayClientMode, normalizeGatewayClientName, hasGatewayClientCap, } from "./protocol/index.js";
export { ConnectErrorDetailCodes, resolveAuthConnectErrorDetailCode, readConnectErrorDetailCode, } from "./protocol/index.js";
//# sourceMappingURL=index.js.map