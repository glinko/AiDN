import { useState } from 'react'

import { Check, Info, Plus, Settings2 } from 'lucide-react'

import {
  Button,
  FocusRing,
  GlassFrame,
  IconButton,
  InsetField,
  Input,
  RaisedControl,
  Slider,
  StatusLabel,
  Surface,
  TextArea,
  Toggle,
  Tooltip,
} from './index'

export function SpatialPrimitivesGallery() {
  const [name, setName] = useState('Primary workspace')
  const [notes, setNotes] = useState('Keyboard navigation keeps the DOM contract visible.')
  const [previewEnabled, setPreviewEnabled] = useState(true)
  const [intensity, setIntensity] = useState('64')
  const [feedback, setFeedback] = useState('No action has been submitted.')

  return (
    <section className="aidn-spatial-section" aria-labelledby="spatial-primitives-title">
      <div className="aidn-spatial-section-heading">
        <h2 id="spatial-primitives-title">DOM primitives gallery</h2>
        <p>Every control keeps its native semantics while depth, glass, accent, radius, and emphasis stay declarative.</p>
      </div>

      <div className="aidn-primitives-gallery">
        <GlassFrame className="aidn-primitives-surface" glass="medium" depth="floating" accent="blue">
          <div className="aidn-primitives-heading">
            <div>
              <h3>Working surface</h3>
              <p>GlassFrame holds content; controls remain ordinary keyboard targets.</p>
            </div>
            <Tooltip content="Surface profiles are semantic; the renderer owns their visual values.">
              <IconButton
                aria-label="Explain surface profiles"
                variant="ghost"
                accent="blue"
                onClick={() => setFeedback('Surface profile guidance is available in the token record.')}
              >
                <Info aria-hidden="true" />
              </IconButton>
            </Tooltip>
          </div>
          <div className="aidn-primitives-actions">
            <Button accent="blue" onClick={() => setFeedback(`Saved ${name || 'workspace'} with explicit action handler.`)}>
              <Check aria-hidden="true" />
              Save workspace
            </Button>
            <Button variant="outline" accent="violet" onClick={() => setFeedback('Preview action is explicit and reversible.')}>
              <Plus aria-hidden="true" />
              Preview
            </Button>
            <Button variant="ghost" accent="neutral" onClick={() => setFeedback('No changes applied.')}>
              Cancel
            </Button>
          </div>
          <p className="aidn-primitive-feedback" role="status" aria-live="polite">{feedback}</p>
        </GlassFrame>

        <Surface className="aidn-primitives-form" depth="inset" glass="soft" radius="medium" emphasis="normal">
          <div className="aidn-primitives-heading">
            <div>
              <h3>Inset fields</h3>
              <p>Labels and helper copy stay attached to their native fields.</p>
            </div>
            <Settings2 aria-hidden="true" className="aidn-primitives-heading-icon" />
          </div>
          <InsetField label="Workspace name" htmlFor="spatial-input-name" hint="Use a stable label for the Node-owned workspace.">
            <Input id="spatial-input-name" value={name} onChange={(event) => setName(event.target.value)} />
          </InsetField>
          <InsetField label="Operator note" htmlFor="spatial-input-notes" hint="Notes remain local to this fixture.">
            <TextArea id="spatial-input-notes" value={notes} onChange={(event) => setNotes(event.target.value)} />
          </InsetField>
        </Surface>
      </div>

      <div className="aidn-primitives-controls">
        <RaisedControl className="aidn-primitives-control-panel" accent="cyan">
          <div className="aidn-control-row">
            <div>
              <h3>Raised controls</h3>
              <p>Toggle and Slider expose state through native ARIA values.</p>
            </div>
            <Toggle
              aria-label="Enable live preview"
              checked={previewEnabled}
              onCheckedChange={setPreviewEnabled}
            />
          </div>
          <div className="aidn-slider-row">
            <div className="aidn-slider-labels">
              <label htmlFor="spatial-preview-intensity">Preview intensity</label>
              <output htmlFor="spatial-preview-intensity">{intensity}%</output>
            </div>
            <Slider
              id="spatial-preview-intensity"
              aria-label="Preview intensity"
              min="0"
              max="100"
              value={intensity}
              onChange={(event) => setIntensity(event.target.value)}
              disabled={!previewEnabled}
            />
          </div>
        </RaisedControl>

        <FocusRing className="aidn-focus-demo">
          <Surface className="aidn-primitives-control-panel" depth="raised" glass="soft" radius="medium">
            <h3>Status and focus</h3>
            <p>FocusRing preserves a clear keyboard cue around a composed surface.</p>
            <div className="aidn-status-stack">
              <StatusLabel status="ready">Ready</StatusLabel>
              <StatusLabel status="attention">Needs review</StatusLabel>
              <StatusLabel status="offline">Offline fallback</StatusLabel>
            </div>
            <Button variant="outline" accent="cyan" onClick={() => setFeedback('Focus-ring action reached the handler.')}>
              Focus-ring action
            </Button>
          </Surface>
        </FocusRing>
      </div>

      <p className="aidn-primitives-note">Keyboard order: profile controls → fields → actions → toggle → slider → status action → return. Icon-only controls have explicit accessible labels.</p>
    </section>
  )
}

