import { Layers3, Menu, RefreshCw, Sparkles } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import type { SavedHypervisorConnection } from '@/lib/hypervisor-connections'
import type { DashboardScreen } from '@/stores/operator-dashboard'

import { HypervisorSelector } from '@/app/HypervisorSelector'
import type { RefreshFeedback } from '@/app/shell-types'

export type TopBarProps = {
  nodeName: string
  advanced: boolean
  isRefreshing: boolean
  refreshError: boolean
  refreshFeedback: RefreshFeedback
  onRefresh: () => void
  onToggleAdvanced: () => void
  onOpenNavigation: () => void
  onNavigate: (screen: DashboardScreen) => void
  savedHypervisors: SavedHypervisorConnection[]
  onAddHypervisor: () => void
  onRemoveHypervisor: (connection: SavedHypervisorConnection) => void
}

export function TopBar({
  nodeName,
  advanced,
  isRefreshing,
  refreshError,
  refreshFeedback,
  onRefresh,
  onToggleAdvanced,
  onOpenNavigation,
  onNavigate,
  savedHypervisors,
  onAddHypervisor,
  onRemoveHypervisor,
}: TopBarProps) {
  return (
    <header className="sticky top-0 z-30 border-b border-border/80 bg-[#050c15]/95 backdrop-blur-xl">
      <div className="mx-auto flex h-16 w-full max-w-[1760px] items-center gap-3 px-3 lg:px-5">
        <Button
          aria-label="Open navigation"
          className="lg:hidden"
          variant="outline"
          size="icon"
          onClick={onOpenNavigation}
        >
          <Menu />
        </Button>
        <button type="button" aria-label="Open Hypervisor overview" className="flex shrink-0 items-center gap-2.5 font-semibold tracking-[-0.04em] text-white" onClick={() => onNavigate('overview')}>
          <span className="grid size-8 place-items-center rounded-[10px] bg-gradient-to-br from-cyan-300 via-cyan-400 to-blue-500 shadow-[0_0_24px_rgba(43,215,197,0.18)]">
            <Sparkles className="size-4 text-[#04101c]" strokeWidth={2.8} />
          </span>
          <span className="hidden text-lg sm:inline">AiDN</span>
        </button>
        <span className="hidden rounded-full border border-emerald-300/20 bg-emerald-300/10 px-2 py-1 font-mono text-[10px] font-semibold tracking-[0.12em] text-emerald-300 xl:inline">
          ONLINE
        </span>
        <Separator orientation="vertical" className="hidden h-6 bg-border/80 lg:block" />
        <HypervisorSelector
          nodeName={nodeName}
          onNavigate={onNavigate}
          savedHypervisors={savedHypervisors}
          onAddHypervisor={onAddHypervisor}
          onRemoveHypervisor={onRemoveHypervisor}
        />
        <div className="ml-auto flex shrink-0 items-center gap-1.5">
          <span aria-live="polite" className={cn('hidden max-w-64 truncate font-mono text-[10px] xl:block', refreshFeedback.state === 'error' ? 'text-amber-200' : refreshFeedback.state === 'running' ? 'text-cyan-200' : 'text-slate-500')}>
            {refreshFeedback.message}
          </span>
          <Tooltip>
            <TooltipTrigger render={<Button variant="ghost" size="icon" aria-label="Refresh dashboard" onClick={onRefresh} />}>
              <RefreshCw className={cn('size-4', isRefreshing && 'animate-spin', refreshError && 'text-amber-300')} />
            </TooltipTrigger>
            <TooltipContent>Refresh current Hypervisor state</TooltipContent>
          </Tooltip>
          <Button variant="outline" size="sm" className="hidden border-border bg-[#081523] text-foreground hover:bg-[#102438] sm:inline-flex" onClick={onToggleAdvanced}>
            <Layers3 />
            {advanced ? 'Basic mode' : 'Advanced mode'}
          </Button>
        </div>
      </div>
    </header>
  )
}
