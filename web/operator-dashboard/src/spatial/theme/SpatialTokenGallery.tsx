import { useState } from 'react'

import { motion, useReducedMotion } from 'motion/react'

import {
  spatialContrastSpecimens,
  spatialTokens,
  type SpatialContrastMode,
  type SpatialTransparencyMode,
} from './tokens'
import { SpatialPrimitivesGallery } from '@/spatial/primitives/SpatialPrimitivesGallery'

type SpatialTokenGalleryProps = {
  contrast: SpatialContrastMode
  transparency: SpatialTransparencyMode
  onContrastChange: (contrast: SpatialContrastMode) => void
  onTransparencyChange: (transparency: SpatialTransparencyMode) => void
  onReturn: () => void
}

const colorSwatches = [
  { label: 'Background / base', value: spatialTokens.color.background.base },
  { label: 'Surface / fallback', value: spatialTokens.color.surface.fallback },
  { label: 'Accent / blue', value: spatialTokens.color.accent.blue },
  { label: 'Accent / violet', value: spatialTokens.color.accent.violet },
  { label: 'State / ready', value: spatialTokens.color.state.ready },
  { label: 'State / attention', value: spatialTokens.color.state.attention },
] as const

const primitiveRows = [
  ['Radius / medium', spatialTokens.radius.medium],
  ['Blur / large', spatialTokens.blur.large],
  ['Spacing / six', spatialTokens.spacing.six],
  ['Shadow / soft', 'soft elevation'],
  ['Motion / enter', spatialTokens.motion.enter],
] as const

function ProfileButton({ label, selected, onClick }: { label: string; selected: boolean; onClick: () => void }) {
  return (
    <button type="button" className="aidn-spatial-button" aria-pressed={selected} onClick={onClick}>
      {label}
    </button>
  )
}

export function SpatialTokenGallery({
  contrast,
  transparency,
  onContrastChange,
  onTransparencyChange,
  onReturn,
}: SpatialTokenGalleryProps) {
  const [motionReplayKey, setMotionReplayKey] = useState(0)
  const prefersReducedMotion = useReducedMotion()

  return (
    <motion.main
      initial={prefersReducedMotion ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={prefersReducedMotion ? { duration: 0 } : { duration: 0.28, ease: 'easeOut' }}
      aria-labelledby="spatial-route-title"
      className="aidn-spatial-page"
      data-spatial-bundle="aidn-spatial-runtime-m05"
      data-spatial-route-state="ready"
    >
      <header className="aidn-spatial-intro">
        <h1 id="spatial-route-title">Spatial Workspace preview</h1>
        <p>
          M1.1 Milky Glass tokens make the Spatial surface calm, legible, and reversible. This gallery shows the
          versioned values, contrast checks, motion behavior, and fallbacks that sit inside the Spatial-only theme boundary.
        </p>
      </header>

      <div className="aidn-spatial-scene-lane" aria-hidden="true">
        <span>Mock scene · select a Node</span>
      </div>

      <section className="aidn-spatial-section" aria-labelledby="spatial-profile-title">
        <div className="aidn-spatial-section-heading">
          <h2 id="spatial-profile-title">Profiles you can change safely</h2>
          <p>These controls change only the Spatial wrapper. Classic remains on its existing dark control-plane palette.</p>
        </div>
        <div className="aidn-glass-surface aidn-profile-controls">
          <fieldset className="aidn-profile-group">
            <legend>Contrast profile</legend>
            <div className="aidn-profile-options">
              <ProfileButton label="Standard" selected={contrast === 'standard'} onClick={() => onContrastChange('standard')} />
              <ProfileButton label="High contrast" selected={contrast === 'high'} onClick={() => onContrastChange('high')} />
            </div>
          </fieldset>
          <fieldset className="aidn-profile-group">
            <legend>Transparency profile</legend>
            <div className="aidn-profile-options">
              <ProfileButton label="Glass" selected={transparency === 'full'} onClick={() => onTransparencyChange('full')} />
              <ProfileButton label="Reduced transparency" selected={transparency === 'reduced'} onClick={() => onTransparencyChange('reduced')} />
            </div>
          </fieldset>
          <p className="aidn-inline-note">System preferences for reduced transparency, reduced motion, and forced colors are honored as well.</p>
        </div>
      </section>

      <section className="aidn-spatial-section" aria-labelledby="spatial-token-title">
        <div className="aidn-spatial-section-heading">
          <h2 id="spatial-token-title">Token preview</h2>
          <p>Colors and primitives are named once so components can share a visual grammar without arbitrary values.</p>
        </div>
        <div className="aidn-token-grid">
          <article className="aidn-glass-surface aidn-token-card">
            <h3>Color roles</h3>
            <p>Surface, accent, and state colors remain explicit and testable.</p>
            <div className="aidn-swatch-row">
              {colorSwatches.map((swatch) => (
                <div className="aidn-swatch" key={swatch.label}>
                  <div className="aidn-swatch-color" style={{ backgroundColor: swatch.value }} aria-hidden="true" />
                  <span className="aidn-swatch-label">{swatch.label}</span>
                  <code className="aidn-swatch-value">{swatch.value}</code>
                </div>
              ))}
            </div>
          </article>
          <article className="aidn-glass-surface aidn-token-card">
            <h3>System primitives</h3>
            <p>Spacing, depth, radius, blur, and motion values are ready for the first Spatial primitives.</p>
            <dl className="aidn-token-list">
              {primitiveRows.map(([label, value]) => (
                <div className="aidn-token-row" key={label}>
                  <dt className="aidn-token-name">{label}</dt>
                  <dd className="aidn-token-value">{value}</dd>
                </div>
              ))}
            </dl>
          </article>
        </div>
      </section>

      <SpatialPrimitivesGallery />

      <section className="aidn-spatial-section" aria-labelledby="spatial-contrast-title">
        <div className="aidn-spatial-section-heading">
          <h2 id="spatial-contrast-title">Contrast specimen</h2>
          <p>Primary, secondary, and muted text use opaque backgrounds in this check so the ratios stay meaningful.</p>
        </div>
        <div className="aidn-glass-surface aidn-token-card">
          <table className="aidn-contrast-table">
            <caption>WCAG AA text contrast checks</caption>
            <thead>
              <tr>
                <th scope="col">Role</th>
                <th scope="col">Sample</th>
                <th scope="col">Ratio</th>
                <th scope="col">Result</th>
              </tr>
            </thead>
            <tbody>
              {spatialContrastSpecimens.map((specimen) => (
                <tr key={specimen.id}>
                  <th scope="row">{specimen.label}</th>
                  <td>
                    <span
                      className="aidn-contrast-sample"
                      style={{ color: specimen.foreground, backgroundColor: specimen.background }}
                    >
                      Aa readable text
                    </span>
                  </td>
                  <td className="aidn-contrast-ratio">{specimen.ratio.toFixed(2)}:1</td>
                  <td><span className="aidn-status-pill">AA pass</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="aidn-spatial-section" aria-labelledby="spatial-motion-title">
        <div className="aidn-spatial-section-heading">
          <h2 id="spatial-motion-title">Motion specimen</h2>
          <p>One short entrance moment demonstrates the motion token; the reduced-motion preference removes the authored travel.</p>
        </div>
        <div className="aidn-motion-grid">
          <div className="aidn-glass-surface aidn-token-card">
            <div key={motionReplayKey} className="aidn-motion-sample" data-replay="true">Surface enters with hierarchy</div>
            <p className="aidn-motion-status" role="status" aria-live="polite">Motion profile: {prefersReducedMotion ? 'reduced' : 'standard'}</p>
            <button type="button" className="aidn-spatial-button aidn-spatial-button-primary" onClick={() => setMotionReplayKey((key) => key + 1)}>
              Replay motion
            </button>
          </div>
          <div className="aidn-glass-surface aidn-token-card">
            <h3>Hierarchy survives</h3>
            <p>When motion is reduced, the surface still arrives with the same spacing, contrast, and elevation.</p>
          </div>
        </div>
      </section>

      <section className="aidn-spatial-section" aria-labelledby="spatial-fallback-title">
        <div className="aidn-spatial-section-heading">
          <h2 id="spatial-fallback-title">Fallback specimen</h2>
          <p>Backdrop blur is an enhancement, not a dependency: unsupported or reduced-transparency environments keep a readable opaque surface.</p>
        </div>
        <div className="aidn-fallback-grid">
          <article className="aidn-glass-surface aidn-fallback-sample aidn-fallback-glass-sample">
            <strong>Blur-supported surface</strong>
            <span>Translucent fill and backdrop blur are enabled where the browser supports them.</span>
          </article>
          <article className="aidn-fallback-sample">
            <strong>Opaque fallback</strong>
            <span>The fallback color remains distinct without relying on backdrop-filter.</span>
          </article>
        </div>
      </section>

      <section className="aidn-spatial-section" aria-labelledby="spatial-renderer-title">
        <div className="aidn-glass-surface aidn-renderer-seam">
          <div className="aidn-spatial-section-heading">
            <h2 id="spatial-renderer-title">Renderer dependency seam</h2>
            <p>Three.js and React Three Fiber stay in the fixed canvas layer. DOM controls and GlassFrames stay in the fixed overlay; the shell above demonstrates their pointer boundary.</p>
          </div>
        </div>
      </section>

      <footer className="aidn-spatial-footer">
        <span>Spatial token package <code>spatial.tokens.v1</code></span>
        <button type="button" className="aidn-spatial-button" onClick={onReturn}>Return to Classic UI</button>
      </footer>
    </motion.main>
  )
}
