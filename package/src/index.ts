// Main client export
export {
  GatewayBrowserClient,
  GatewayRequestError,
  type GatewayBrowserClientOptions,
  type GatewayErrorInfo,
  type GatewayEventFrame,
  type GatewayHelloOk,
  type GatewayResponseFrame,
  resolveGatewayErrorDetailCode,
} from "./client.js";

// Utility exports
export { generateUUID } from "./uuid.js";

// Auth exports
export {
  buildDeviceAuthPayload,
  type DeviceAuthPayloadParams,
  clearDeviceAuthToken,
  loadDeviceAuthToken,
  normalizeDeviceAuthRole,
  normalizeDeviceAuthScopes,
  type DeviceAuthEntry,
  type DeviceAuthStore,
  storeDeviceAuthToken,
  loadOrCreateDeviceIdentity,
  signDevicePayload,
  type DeviceIdentity,
} from "./auth/index.js";

// Protocol exports
export {
  GATEWAY_CLIENT_IDS,
  GATEWAY_CLIENT_MODES,
  GATEWAY_CLIENT_NAMES,
  GATEWAY_CLIENT_CAPS,
  type GatewayClientId,
  type GatewayClientInfo,
  type GatewayClientMode,
  type GatewayClientName,
  type GatewayClientCap,
  normalizeGatewayClientId,
  normalizeGatewayClientMode,
  normalizeGatewayClientName,
  hasGatewayClientCap,
} from "./protocol/index.js";

export {
  ConnectErrorDetailCodes,
  resolveAuthConnectErrorDetailCode,
  readConnectErrorDetailCode,
  type ConnectErrorDetailCode,
} from "./protocol/index.js";

// Types
export type { ChatAttachment, ChatEventPayload } from "./types.js";
