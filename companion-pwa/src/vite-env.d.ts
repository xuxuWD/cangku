/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  readonly VITE_APPROVAL_POLL_SECONDS?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
