/// <reference types="vite/client" />
interface ImportMetaEnv {
  readonly VITE_MOCK?: string;
  /** "hr": render the hr.blockid.au app on any host (local testing) */
  readonly VITE_HOST?: string;
}
