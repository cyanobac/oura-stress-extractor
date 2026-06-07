/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Contact address for the footer mailto link; injected at build time. */
  readonly VITE_CONTACT_EMAIL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
