/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_DEFAULT_GATEWAY_WS?: string;
  readonly VITE_GATEWAY_TOKEN?: string;
  readonly VITE_DEFAULT_SESSION_KEY?: string;
  readonly VITE_AUTO_CONNECT?: string;
  readonly VITE_COMPACT_UI?: string;
  readonly VITE_SHOW_DEBUG?: string;
}
