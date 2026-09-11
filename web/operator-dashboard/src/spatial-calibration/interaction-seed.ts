export type SeedPoint = { x: number; y: number }
export type SeedViewport = { width: number; height: number; offsetTop: number; offsetLeft: number }

/** Pointer intent, shared by empty-space and object hit handlers. A pinch is never a tap. */
export class SceneTapGesture {
  private pointers = new Set<number>()
  private start: SeedPoint = { x: 0, y: 0 }
  private blocked = true

  down(id: number, x: number, y: number, button: number) {
    if (this.pointers.size === 0) { this.start = { x, y }; this.blocked = button !== 0 }
    this.pointers.add(id)
    if (this.pointers.size > 1) this.blocked = true
  }

  move(x: number, y: number) {
    if (this.pointers.size && Math.hypot(x - this.start.x, y - this.start.y) > 6) this.blocked = true
  }

  up(id: number) { this.pointers.delete(id) }
  cancel(id: number) { this.blocked = true; this.up(id) }
  canTap() { return !this.blocked && this.pointers.size === 0 }
}

export function seedLayout(point: SeedPoint, viewport: SeedViewport, expanded: boolean, textWidth: number, lines: number, hasHistory: boolean) {
  const margin = expanded ? 16 : 64 // Includes the initial radial buttons.
  const cap = viewport.width < 680 ? viewport.width - 32 : Math.min(720, viewport.width * 0.6)
  const width = expanded ? Math.min(cap, Math.max(hasHistory ? 360 : 220, textWidth + 40)) : 72
  const maxHeight = Math.min(viewport.height - 32, viewport.height < 500 ? viewport.height - 32 : Math.min(480, viewport.height * 0.5))
  const height = expanded ? Math.min(maxHeight, hasHistory ? maxHeight : Math.max(142, 112 + lines * 24)) : 72
  const left = Math.max(viewport.offsetLeft + margin, Math.min(point.x - 36, viewport.offsetLeft + viewport.width - width - margin))
  const top = Math.max(viewport.offsetTop + margin, Math.min(point.y - 36, viewport.offsetTop + viewport.height - height - margin))
  return { width, height, left, top }
}
