import { atom, computed } from 'nanostores'

import type { OverlayState } from './interfaces.js'

const buildOverlayState = (): OverlayState => ({
  agents: false,
  agentsInitialHistoryIndex: 0,
  approval: null,
  clarify: null,
  confirm: null,
  journey: false,
  modelPicker: false,
  pager: null,
  secret: null,
  sessions: false,
  sudo: null
})

export const $overlayState = atom<OverlayState>(buildOverlayState())

export const $isBlocked = computed(
  $overlayState,
  ({ agents, approval, clarify, confirm, journey, modelPicker, pager, secret, sessions, sudo }) =>
    Boolean(
      agents || approval || clarify || confirm || journey || modelPicker || pager || secret || sessions || sudo
    )
)

export const getOverlayState = () => $overlayState.get()

export const patchOverlayState = (next: Partial<OverlayState> | ((state: OverlayState) => OverlayState)) =>
  $overlayState.set(typeof next === 'function' ? next($overlayState.get()) : { ...$overlayState.get(), ...next })

/** Full reset — used by session/turn teardown and tests. */
export const resetOverlayState = () => $overlayState.set(buildOverlayState())

/**
 * Soft reset: drop FLOW-scoped overlays (approval / clarify / confirm / sudo
 * / secret / pager) but PRESERVE user-toggled ones — agents dashboard, model
 * picker, and sessions overlay. Those are opened deliberately and
 * shouldn't vanish when a turn ends.  Called from turnController.idle() on
 * every turn completion / interrupt; the old "reset everything" behaviour
 * silently closed /agents the moment delegation finished.
 */
export const resetFlowOverlays = () =>
  $overlayState.set({
    ...buildOverlayState(),
    agents: $overlayState.get().agents,
    agentsInitialHistoryIndex: $overlayState.get().agentsInitialHistoryIndex,
    journey: $overlayState.get().journey,
    modelPicker: $overlayState.get().modelPicker,
    sessions: $overlayState.get().sessions
  })
