import type { MouseTrackingMode } from '@hermes/ink'

const truthy = (v?: string) => /^(?:1|true|yes|on)$/i.test((v ?? '').trim())
const falsy = (v?: string) => /^(?:0|false|no|off)$/i.test((v ?? '').trim())

const parseToggle = (v?: string): boolean | null => {
  const raw = (v ?? '').trim()

  if (!raw) {
    return null
  }

  if (truthy(raw)) {
    return true
  }

  if (falsy(raw)) {
    return false
  }

  return null
}

export const STARTUP_RESUME_ID = (process.env.HERMES_TUI_RESUME ?? '').trim()
export const STARTUP_QUERY = (process.env.HERMES_TUI_QUERY ?? '').trim()
export const STARTUP_IMAGE = (process.env.HERMES_TUI_IMAGE ?? '').trim()

// Mouse tracking mode resolution at startup. Per-mode selection (off|wheel|
// buttons|all) lives in display.mouse_tracking in config.yaml — these env
// vars only set the boot-time default before that config is applied.
//
// Precedence (highest first):
//
// - HERMES_TUI_MOUSE_TRACKING (truthy/falsy) explicitly overrides everything.
//   This is the "force a value" knob and intentionally beats the legacy
//   kill-switch.
// - HERMES_TUI_DISABLE_MOUSE=1 forces mouse off — the legacy kill switch.
const mouseTrackingOverride = parseToggle(process.env.HERMES_TUI_MOUSE_TRACKING)
const mouseTrackingDisabledLegacy = truthy(process.env.HERMES_TUI_DISABLE_MOUSE)
const resolvedBootMouseEnabled = mouseTrackingOverride ?? !mouseTrackingDisabledLegacy
export const MOUSE_TRACKING: MouseTrackingMode = resolvedBootMouseEnabled ? 'all' : 'off'

export const NO_CONFIRM_DESTRUCTIVE = truthy(process.env.HERMES_TUI_NO_CONFIRM)

const inlineOverride = parseToggle(process.env.HERMES_TUI_INLINE)

// Skip AlternateScreen — TUI renders into the primary buffer so the host
// terminal's native scrollback captures whatever scrolls off the top.
//
export const INLINE_MODE = inlineOverride ?? false

// Live FPS counter overlay, fed by ink's onFrame (real render rate, not a
// synthetic timer).
export const SHOW_FPS = truthy(process.env.HERMES_TUI_FPS)
