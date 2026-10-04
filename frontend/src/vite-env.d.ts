/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_PLAYGROUND_STORAGE?: "local";
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
