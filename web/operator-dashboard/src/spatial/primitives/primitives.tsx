import * as React from 'react'

import { cn } from '@/lib/utils'

export type SurfaceDepth = 'flat' | 'raised' | 'floating' | 'inset'
export type GlassLevel = 'none' | 'soft' | 'medium' | 'strong'
export type SurfaceRadius = 'small' | 'medium' | 'large' | 'pill'
export type SurfaceAccent = 'neutral' | 'blue' | 'violet' | 'cyan' | 'amber' | 'critical'
export type SurfaceEmphasis = 'secondary' | 'normal' | 'primary'

export type SpatialSurfaceStyleProps = {
  depth?: SurfaceDepth
  glass?: GlassLevel
  accent?: SurfaceAccent
  radius?: SurfaceRadius
  emphasis?: SurfaceEmphasis
}

const surfaceDefaults = {
  depth: 'flat' as const,
  glass: 'none' as const,
  accent: 'neutral' as const,
  radius: 'medium' as const,
  emphasis: 'normal' as const,
}

function surfaceClassName(className: string | undefined, slot: string) {
  return cn('aidn-surface', slot, className)
}

function surfaceData(style: SpatialSurfaceStyleProps) {
  return {
    'data-aidn-depth': style.depth ?? surfaceDefaults.depth,
    'data-aidn-glass': style.glass ?? surfaceDefaults.glass,
    'data-aidn-accent': style.accent ?? surfaceDefaults.accent,
    'data-aidn-radius': style.radius ?? surfaceDefaults.radius,
    'data-aidn-emphasis': style.emphasis ?? surfaceDefaults.emphasis,
  }
}

export type SurfaceProps = React.ComponentPropsWithoutRef<'div'> & SpatialSurfaceStyleProps

export function Surface({
  className,
  depth,
  glass,
  accent,
  radius,
  emphasis,
  ...props
}: SurfaceProps) {
  const style = { depth, glass, accent, radius, emphasis }
  return (
    <div
      data-slot="spatial-surface"
      className={surfaceClassName(className, 'aidn-surface-standard')}
      {...props}
      {...surfaceData(style)}
    />
  )
}

export type GlassFrameProps = React.ComponentPropsWithoutRef<'section'> & SpatialSurfaceStyleProps

export function GlassFrame({
  className,
  depth = 'floating',
  glass = 'medium',
  accent = 'neutral',
  radius = 'large',
  emphasis = 'normal',
  ...props
}: GlassFrameProps) {
  return (
    <section
      data-slot="glass-frame"
      className={surfaceClassName(className, 'aidn-glass-frame')}
      {...props}
      {...surfaceData({ depth, glass, accent, radius, emphasis })}
    />
  )
}

export type SpatialButtonVariant = 'solid' | 'outline' | 'ghost' | 'critical'
export type SpatialButtonSize = 'sm' | 'md' | 'lg'

export type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & SpatialSurfaceStyleProps & {
  variant?: SpatialButtonVariant
  size?: SpatialButtonSize
  loading?: boolean
}

export function Button({
  className,
  type = 'button',
  depth = 'raised',
  glass = 'soft',
  accent = 'blue',
  radius = 'small',
  emphasis = 'primary',
  variant = 'solid',
  size = 'md',
  loading = false,
  disabled,
  'aria-busy': ariaBusy,
  ...props
}: ButtonProps) {
  return (
    <button
      data-slot="spatial-button"
      className={cn('aidn-spatial-button', className)}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || ariaBusy}
      data-aidn-variant={variant}
      data-aidn-size={size}
      {...props}
      {...surfaceData({ depth, glass, accent, radius, emphasis })}
    />
  )
}

export type IconButtonProps = Omit<ButtonProps, 'children' | 'size' | 'aria-label'> & {
  children: React.ReactNode
  'aria-label': string
}

export function IconButton({ className, children, ...props }: IconButtonProps) {
  return (
    <Button
      {...props}
      size="md"
      className={cn('aidn-icon-button', className)}
    >
      {children}
    </Button>
  )
}

export type InputProps = React.InputHTMLAttributes<HTMLInputElement> & {
  inset?: boolean
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(function Input(
  { className, type = 'text', inset = true, ...props },
  ref,
) {
  return (
    <input
      ref={ref}
      data-slot="spatial-input"
      className={cn('aidn-spatial-input', inset && 'aidn-inset-input', className)}
      type={type}
      {...props}
    />
  )
})

export type TextAreaProps = React.TextareaHTMLAttributes<HTMLTextAreaElement> & {
  inset?: boolean
}

export const TextArea = React.forwardRef<HTMLTextAreaElement, TextAreaProps>(function TextArea(
  { className, inset = true, ...props },
  ref,
) {
  return (
    <textarea
      ref={ref}
      data-slot="spatial-textarea"
      className={cn('aidn-spatial-textarea', inset && 'aidn-inset-input', className)}
      {...props}
    />
  )
})

export type InsetFieldProps = React.ComponentPropsWithoutRef<'div'> & {
  label: React.ReactNode
  htmlFor: string
  hint?: React.ReactNode
  error?: React.ReactNode
  children: React.ReactElement<InsetFieldControlProps>
}

type InsetFieldControlProps = {
  'aria-describedby'?: string
  'aria-invalid'?: boolean | 'false' | 'true'
}

export function InsetField({ label, htmlFor, hint, error, children, className, ...props }: InsetFieldProps) {
  const messageId = React.useId()
  const messageIdForField = error || hint ? messageId : undefined
  const describedBy = [children.props['aria-describedby'], messageIdForField].filter(Boolean).join(' ') || undefined
  const field = React.cloneElement(children, {
    'aria-describedby': describedBy,
    'aria-invalid': error ? true : children.props['aria-invalid'],
  })
  return (
    <div
      data-slot="inset-field"
      className={cn('aidn-inset-field', className)}
      data-aidn-invalid={Boolean(error)}
      {...props}
    >
      <label className="aidn-field-label" htmlFor={htmlFor}>{label}</label>
      {field}
      {error ? <p id={messageId} className="aidn-field-error" role="alert">{error}</p> : null}
      {!error && hint ? <p id={messageId} className="aidn-field-hint">{hint}</p> : null}
    </div>
  )
}

export type ToggleProps = Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, 'aria-checked' | 'role'> & {
  checked: boolean
  onCheckedChange?: (checked: boolean) => void
  'aria-label': string
}

export function Toggle({ checked, onCheckedChange, onClick, className, disabled, ...props }: ToggleProps) {
  return (
    <button
      {...props}
      type="button"
      role="switch"
      aria-checked={checked}
      className={cn('aidn-toggle', className)}
      disabled={disabled}
      onClick={(event) => {
        onClick?.(event)
        if (!event.defaultPrevented) onCheckedChange?.(!checked)
      }}
    >
      <span className="aidn-toggle-track" aria-hidden="true"><span className="aidn-toggle-thumb" /></span>
    </button>
  )
}

export type SliderProps = Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type'> & {
  'aria-label': string
}

export const Slider = React.forwardRef<HTMLInputElement, SliderProps>(function Slider({ className, ...props }, ref) {
  return <input ref={ref} data-slot="spatial-slider" className={cn('aidn-spatial-slider', className)} type="range" {...props} />
})

type TooltipChildProps = { 'aria-describedby'?: string }

export type TooltipProps = {
  content: React.ReactNode
  children: React.ReactElement<TooltipChildProps>
  delay?: number
}

export function Tooltip({ content, children, delay = 0 }: TooltipProps) {
  const [open, setOpen] = React.useState(false)
  const tooltipId = React.useId()
  const timer = React.useRef<ReturnType<typeof setTimeout> | null>(null)

  const schedule = (next: boolean) => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => setOpen(next), next ? delay : 0)
  }

  React.useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current)
  }, [])

  const describedBy = [children.props['aria-describedby'], open ? tooltipId : undefined].filter(Boolean).join(' ') || undefined
  const trigger = React.cloneElement(children, { 'aria-describedby': describedBy })

  return (
    <span
      className="aidn-tooltip"
      onMouseEnter={() => schedule(true)}
      onMouseLeave={() => schedule(false)}
      onFocusCapture={() => schedule(true)}
      onBlurCapture={() => schedule(false)}
    >
      <span className="aidn-tooltip-trigger">{trigger}</span>
      {open ? <span id={tooltipId} role="tooltip" className="aidn-tooltip-content">{content}</span> : null}
    </span>
  )
}

export type StatusLabelStatus = 'ready' | 'attention' | 'critical' | 'offline' | 'unknown'

export type StatusLabelProps = React.ComponentPropsWithoutRef<'span'> & {
  status: StatusLabelStatus
}

export function StatusLabel({ status, children, className, ...props }: StatusLabelProps) {
  return (
    <span
      data-slot="status-label"
      role="status"
      className={cn('aidn-status-label', className)}
      data-aidn-status={status}
      {...props}
    >
      {children ?? status}
    </span>
  )
}

export const StatusBadge = StatusLabel

export type FocusRingProps = React.ComponentPropsWithoutRef<'div'>

export function FocusRing({ className, ...props }: FocusRingProps) {
  return <div data-slot="focus-ring" className={cn('aidn-focus-ring', className)} {...props} />
}

export type RaisedControlProps = React.ComponentPropsWithoutRef<'div'> & SpatialSurfaceStyleProps

export function RaisedControl({ className, depth = 'raised', glass = 'soft', radius = 'medium', ...props }: RaisedControlProps) {
  return (
    <div
      data-slot="raised-control"
      className={cn('aidn-raised-control', className)}
      {...props}
      {...surfaceData({ depth, glass, radius })}
    />
  )
}
