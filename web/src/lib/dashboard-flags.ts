declare global {
  interface Window {
    /** Set true by the server only for `marlow dashboard --tui` (or MARLOW_DASHBOARD_TUI=1). */
    __MARLOW_DASHBOARD_EMBEDDED_CHAT__?: boolean;
    /** @deprecated Older injected name; treated as on when true. */
    __MARLOW_DASHBOARD_TUI__?: boolean;
  }
}

/** True only when the dashboard was started with embedded TUI Chat (`marlow dashboard --tui`). */
export function isDashboardEmbeddedChatEnabled(): boolean {
  if (typeof window === "undefined") return false;
  if (window.__MARLOW_DASHBOARD_EMBEDDED_CHAT__ === true) return true;
  return window.__MARLOW_DASHBOARD_TUI__ === true;
}
