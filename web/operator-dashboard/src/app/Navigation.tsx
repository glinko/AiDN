import { ServerCog } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { formatPercent } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { DashboardScreen } from '@/stores/operator-dashboard'

import { advancedItems, navigationItems } from '@/app/screen-registry'

export type NavigationProps = {
  activeScreen: DashboardScreen
  advanced: boolean
  readinessPercent: number
  onNavigate: (screen: DashboardScreen) => void
  onToggleAdvanced: () => void
  className?: string
  panel?: boolean
}

export function Navigation({ activeScreen, advanced, readinessPercent, onNavigate, onToggleAdvanced, className, panel = true }: NavigationProps) {
  const items = advanced ? [...navigationItems, ...advancedItems] : navigationItems.filter((item) => !item.advanced)

  return (
    <nav className={cn(panel && 'operator-panel', 'flex min-h-0 flex-col lg:sticky lg:top-[76px] lg:min-h-[calc(100svh-104px)]', className)}>
      <div className="mb-3 px-2 pt-2">
        <p className="eyebrow">Control Plane</p>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">Bundle-first operations for this Hypervisor.</p>
      </div>
      <div className="space-y-1">
        {items.map((item, index) => {
          const Icon = item.icon
          const isCurrent = item.id === activeScreen
          return (
            <Tooltip key={`${item.label}-${index}`}>
              <TooltipTrigger
                render={
                  <button
                    type="button"
                    aria-current={isCurrent ? 'page' : undefined}
                    className={cn(
                      'group flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm font-medium transition-colors',
                      isCurrent
                        ? 'bg-cyan-300/10 text-cyan-100 shadow-[inset_2px_0_0_0_#2bd7c5]'
                        : 'text-slate-300 hover:bg-white/[0.045] hover:text-white',
                    )}
                    onClick={() => onNavigate(item.id)}
                  />
                }
              >
                <Icon className={cn('size-4 shrink-0', isCurrent ? 'text-cyan-300' : 'text-slate-400 group-hover:text-slate-200')} />
                <span>{item.label}</span>
              </TooltipTrigger>
              <TooltipContent side="right">Open {item.label}</TooltipContent>
            </Tooltip>
          )
        })}
      </div>
      <div className="mt-auto space-y-3 px-1 pb-1 pt-5">
        <div className="rounded-lg border border-border/80 bg-black/10 p-3">
          <div className="flex items-center justify-between gap-2">
            <span className="eyebrow">Readiness</span>
            <span className="font-mono text-xs font-semibold text-cyan-200">{formatPercent(readinessPercent)}</span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/8">
            <div className="h-full rounded-full bg-gradient-to-r from-blue-400 to-cyan-300" style={{ width: `${Math.min(100, Math.max(0, readinessPercent))}%` }} />
          </div>
        </div>
        <Button variant="outline" className="w-full border-border bg-transparent text-slate-200 hover:bg-white/[0.05]" onClick={onToggleAdvanced}>
          <ServerCog />
          {advanced ? 'Switch to Basic' : 'Switch to Advanced'}
        </Button>
      </div>
    </nav>
  )
}
