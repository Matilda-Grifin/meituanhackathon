# openclaw-ws

OpenClaw WebSocket client and protocol for browser environments.

## Features

- WebSocket client with auto-reconnect
- Device identity and authentication (Ed25519)
- Device token caching
- Protocol type definitions
- Request/response and event handling

## Installation

```bash
pnpm add openclaw-ws
```

## Usage

```typescript
import { GatewayBrowserClient } from "openclaw-ws";

const client = new GatewayBrowserClient({
  url: "ws://localhost:18789",
  token: "your-token",
  clientName: "webchat-ui",
  mode: "webchat",
  onHello: (hello) => {
    console.log("Connected:", hello);
  },
  onEvent: (evt) => {
    console.log("Event:", evt.event, evt.payload);
  },
  onClose: (info) => {
    console.log("Closed:", info);
  },
});

client.start();

// Make a request
const response = await client.request("chat.history", {
  sessionKey: "session-key",
});

client.stop();
```

## API

### GatewayBrowserClient

- `start()` - Start the connection
- `stop()` - Stop the connection
- `connected` - Get connection status
- `request<T>(method, params)` - Make a request

### Device Auth

- `loadOrCreateDeviceIdentity()` - Load or create device identity
- `signDevicePayload(privateKey, payload)` - Sign a payload
- `loadDeviceAuthToken(params)` - Load cached token
- `storeDeviceAuthToken(params)` - Store token
- `clearDeviceAuthToken(params)` - Clear token

### Protocol

- `GATEWAY_CLIENT_IDS` - Client ID constants
- `GATEWAY_CLIENT_MODES` - Client mode constants
- `ConnectErrorDetailCodes` - Error code constants
- Various normalization utilities
