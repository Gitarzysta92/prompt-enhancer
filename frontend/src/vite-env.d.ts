/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SOCIAL_DIRECT_FILE_PROTOTYPE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
