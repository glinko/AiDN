import { CircleDot, Network, Plus } from 'lucide-react'

import { isSpatialOperatorPreviewEnabled } from '@/lib/feature-flags'
import { openSpatialRoute } from '@/spatial/route'
import type { SavedHypervisorConnection } from '@/lib/hypervisor-connections'
import type { DashboardScreen } from '@/stores/operator-dashboard'

export type HypervisorSelectorProps = {
  nodeName: string
  onNavigate: (screen: DashboardScreen) => void
  savedHypervisors: SavedHypervisorConnection[]
  onAddHypervisor: () => void
  onRemoveHypervisor: (connection: SavedHypervisorConnection) => void
}

/** Classic shell's local/remote Hypervisor controls and rollout affordance. */
export function HypervisorSelector({ nodeName, onNavigate, savedHypervisors, onAddHypervisor, onRemoveHypervisor }: HypervisorSelectorProps) {
  return (
    <div className="flex min-w-0 items-stretch gap-1 overflow-x-auto [scrollbar-width:none]">
      <button
        type="button"
        aria-label={`Open ${nodeName} overview`}
        className="relative shrink-0 border-x border-t border-border/70 bg-[#0a1725] px-3 py-2 text-left text-sm font-semibold text-cyan-200 after:absolute after:inset-x-3 after:bottom-0 after:h-0.5 after:bg-cyan-300 sm:px-4"
        onClick={() => onNavigate('overview')}
      >
        <span className="block max-w-44 truncate">{nodeName}</span>
        <span className="hidden text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground sm:block">Local Hypervisor</span>
      </button>
      {savedHypervisors.map((connection) => (
        <div key={connection.id} className="group flex shrink-0 items-stretch border border-border/70 bg-[#071321]">
          <a
            href={connection.url}
            target="_blank"
            rel="noreferrer"
            className="flex min-w-0 items-center px-3 py-2 text-left text-sm font-medium text-slate-200 transition-colors hover:bg-cyan-300/[0.06] hover:text-cyan-100 sm:px-4"
            title={`Open ${connection.name} at ${connection.url}`}
          >
            <span className="block max-w-36 truncate">{connection.name}</span>
          </a>
          <button
            type="button"
            aria-label={`Remove ${connection.name} from this browser`}
            className="border-l border-border/70 px-2 text-xs text-slate-500 transition-colors hover:bg-rose-300/10 hover:text-rose-200"
            onClick={() => onRemoveHypervisor(connection)}
          >
            ×
          </button>
        </div>
      ))}
      <button
        type="button"
        aria-label="Add Hypervisor"
        className="flex shrink-0 items-center gap-1.5 border border-dashed border-cyan-300/30 px-3 text-xs font-medium text-cyan-100 transition-colors hover:border-cyan-200/70 hover:bg-cyan-300/[0.06] sm:px-4"
        onClick={onAddHypervisor}
      >
        <Plus className="size-3.5" />
        <span className="hidden sm:inline">Add Hypervisor</span>
      </button>
      {isSpatialOperatorPreviewEnabled() ? <button type="button" aria-label="Open Spatial UI" className="flex shrink-0 items-center gap-1.5 border border-cyan-300/30 px-3 text-xs font-medium text-cyan-100 transition-colors hover:border-cyan-200/70 hover:bg-cyan-300/[0.06] sm:px-4" onClick={openSpatialRoute}><CircleDot className="size-3.5" /><span className="hidden sm:inline">Spatial UI</span></button> : null}
      <button type="button" className="hidden shrink-0 items-center gap-2 border border-dashed border-border/70 px-3 text-xs text-muted-foreground transition-colors hover:border-cyan-300/40 hover:text-cyan-100 md:flex" onClick={() => onNavigate('network')}>
        <Network className="size-3.5" />
        Remote discovery
      </button>
    </div>
  )
}
