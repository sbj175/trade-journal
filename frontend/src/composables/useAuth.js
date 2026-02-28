/**
 * Composable wrapping the global Auth singleton.
 * During transition, Auth is loaded as a <script> tag and lives on window.
 * This composable provides a clean import path for Vue components.
 */
export function useAuth() {
  return window.Auth
}
