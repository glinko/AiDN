import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Check, RotateCcw } from 'lucide-react'
import { SpatialComponentRegistry } from '@/spatial/interaction/component-registry'
import { agentDocumentSchema, type AgentDocument, type AgentDocumentField, type AgentFieldValue, type AgentFormChange, type AgentInterface } from '@/spatial/contracts/agent-document'
import type { AgentConversationMessage } from '@/lib/types'

const registry = new SpatialComponentRegistry()
const valueText = (value: AgentFieldValue): string => value === null ? '—' : typeof value === 'boolean' ? value ? 'Да' : 'Нет' : String(value)
const inputText = (value: AgentFieldValue): string => value === null ? '' : String(value)

export function formValue(field: AgentDocumentField, raw: string | boolean): AgentFieldValue {
  if (field.type === 'boolean') {
    if (typeof raw !== 'boolean') throw new Error('Выберите значение переключателя.')
    return raw
  }
  if (typeof raw !== 'string' || !raw.trim()) throw new Error('Поле «' + field.label + '» не должно быть пустым.')
  if (field.type === 'number' || field.type === 'integer') {
    const value = Number(raw)
    if (!Number.isFinite(value) || (field.type === 'integer' && !Number.isInteger(value))) throw new Error('Проверьте число в поле «' + field.label + '».')
    if ((field.minimum !== null && value < field.minimum) || (field.maximum !== null && value > field.maximum)) throw new Error('Значение «' + field.label + '» вне допустимого диапазона.')
    return value
  }
  if (raw.length > 240 || (field.type === 'select' && !field.options.includes(raw))) throw new Error('Недопустимое значение «' + field.label + '».')
  return raw
}

type Props = {
  document: AgentDocument
  disabled?: boolean
  intents: AgentInterface['intents']
  messages: readonly AgentConversationMessage[]
  onSubmit: (text: string, change: AgentFormChange) => Promise<string>
}

/** Render only registered native controls. There is no HTML injection or node API here. */
export function AgentDocumentFrame({ document, disabled = false, intents, messages, onSubmit }: Props) {
  const lastValid = useRef<AgentDocument | null>(null)
  const validation = useMemo(() => {
    try { return { document: agentDocumentSchema.parse(registry.validateData('agent-document', '1.0.0', document)), error: false } }
    catch { return { document: null, error: true } }
  }, [document])
  if (validation.document) lastValid.current = validation.document
  return <>
    {validation.error ? <p role="alert">Документ не прошёл проверку. Попросите агента сформировать его заново.</p> : null}
    {lastValid.current ? <ValidatedDocumentFrame document={lastValid.current} disabled={disabled || validation.error} intents={intents} messages={messages} onSubmit={onSubmit} /> : null}
  </>
}

function ValidatedDocumentFrame({ document: validated, disabled = false, intents, messages, onSubmit }: Props) {
  const [shown, setShown] = useState(validated)
  const [draft, setDraft] = useState<Record<string, string | boolean>>({})
  const [error, setError] = useState<string | null>(null)
  const [requestId, setRequestId] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [success, setSuccess] = useState(false)
  const sendingRef = useRef(false)
  const intent = intents.find(item => item.intent_id === requestId)
  const reply = messages.find(item => item.direction === 'AGENT' && item.request_id === requestId)
  const applying = requestId !== null && !reply && intent?.state !== 'APPLIED'
  const changed = Object.keys(draft).length > 0
  const updated = validated.revision !== shown.revision

  useEffect(() => {
    if (validated.revision === shown.revision) return
    if (!changed) {
      setShown(validated)
      setError(null)
      return
    }
    if (intent?.state !== 'APPLIED') return
    // Rebase only our verified change. Retain unrelated drafts when their
    // baseline is unchanged; any real conflict requires an explicit refresh.
    const rebased: Record<string, string | boolean> = {}
    let conflict = false
    for (const oldBlock of shown.blocks) {
      if (oldBlock.type !== 'fields') continue
      for (const field of oldBlock.fields) {
        const raw = draft[oldBlock.source_id + ':' + field.id]
        if (raw === undefined) continue
        const nextBlock = validated.blocks.find(block => block.type === 'fields' && block.target_id === oldBlock.target_id && block.fields.some(item => item.id === field.id))
        const nextField = nextBlock?.type === 'fields' ? nextBlock.fields.find(item => item.id === field.id) : undefined
        if (nextBlock?.type !== 'fields' || !nextField) { conflict = true; continue }
        if (oldBlock.source_id === intent.change.source_id && Object.hasOwn(intent.change.proposed, field.id) && nextField.value === intent.change.proposed[field.id]) continue
        if (nextField.value !== field.value) { conflict = true; continue }
        rebased[nextBlock.source_id + ':' + field.id] = raw
      }
    }
    setSuccess(true)
    setRequestId(null)
    if (!conflict) { setShown(validated); setDraft(rebased); setError(null) }
  }, [changed, draft, intent, shown, validated])

  function edit(sourceId: string, field: AgentDocumentField, raw: string | boolean) {
    setError(null)
    setSuccess(false)
    const key = sourceId + ':' + field.id
    setDraft(current => {
      const next = { ...current }
      if (raw === (field.type === 'boolean' ? field.value : inputText(field.value))) delete next[key]
      else next[key] = raw
      return next
    })
  }

  async function submit(event: FormEvent, block: Extract<AgentDocument['blocks'][number], { type: 'fields' }>) {
    event.preventDefault()
    if (sendingRef.current || disabled || applying || updated) return
    const current: Record<string, AgentFieldValue> = {}
    const proposed: Record<string, AgentFieldValue> = {}
    try {
      for (const field of block.fields) {
        const raw = draft[block.source_id + ':' + field.id]
        if (raw === undefined || !field.editable) continue
        const value = formValue(field, raw)
        if (value !== field.value) { current[field.id] = field.value; proposed[field.id] = value }
      }
      if (!Object.keys(proposed).length) return
      if ('local_agent_use' in proposed && Object.keys(proposed).length > 1) throw new Error('Измените доступ локального агента отдельно от остальных настроек.')
      sendingRef.current = true
      setSending(true)
      setError(null)
      setSuccess(false)
      const request = await onSubmit('Примени изменения из формы «' + shown.title + '» и обнови этот frame после проверки.', {
        kind: 'form_change', document_id: shown.document_id, document_revision: shown.revision,
        source_id: block.source_id, source_revision: block.source_revision, current, proposed,
      })
      setRequestId(request)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось отправить изменения. Черновик сохранён; повторите отправку.')
    } finally { sendingRef.current = false; setSending(false) }
  }

  return <article className="agent-document" aria-label={shown.title}>
    {updated && changed && intent?.state !== 'APPLIED' ? <div className="agent-document__notice" role="status">
      <p>Агент обновил документ. Ваш черновик сохранён. Перед применением загрузите актуальные значения.</p>
      <button type="button" onClick={() => { setShown(validated); setDraft({}); setRequestId(null); setError(null) }}>Загрузить новые значения и сбросить черновик</button>
    </div> : null}
    {shown.blocks.map((block, index) => block.type === 'text'
      ? <p className="agent-document__text" key={'text-' + index}>{block.text}</p>
      : <form className="agent-document__section" key={block.source_id + ':' + index} onSubmit={event => void submit(event, block)}>
        <fieldset disabled={disabled || sending || applying || updated}>
          <legend>{block.title || 'Настройки'}</legend>
          <p className="agent-document__target">{block.target_id}</p>
          {block.fields.map(field => {
            const key = block.source_id + ':' + field.id
            const inputId = shown.document_id + '-' + block.source_id + '-' + field.id
            const raw = draft[key] ?? (field.type === 'boolean' ? Boolean(field.value) : inputText(field.value))
            return <div className="agent-document__field" data-editable={field.editable} data-field-type={field.type} key={field.id}>
              <label htmlFor={field.editable ? inputId : undefined}>{field.label}</label>
              {field.editable ? field.type === 'boolean'
                ? <input id={inputId} type="checkbox" checked={Boolean(raw)} aria-describedby={field.description ? inputId + '-hint' : undefined} onChange={event => edit(block.source_id, field, event.target.checked)} />
                : field.type === 'select'
                  ? <select id={inputId} value={String(raw)} aria-describedby={field.description ? inputId + '-hint' : undefined} onChange={event => edit(block.source_id, field, event.target.value)}>{field.options.map(option => <option value={option} key={option}>{option}</option>)}</select>
                  : <input id={inputId} type={field.type === 'number' || field.type === 'integer' ? 'number' : 'text'}
                    value={String(raw)} required maxLength={240} min={field.minimum ?? undefined} max={field.maximum ?? undefined}
                    step={field.type === 'integer' ? 1 : 'any'} aria-describedby={field.description ? inputId + '-hint' : undefined}
                    onChange={event => edit(block.source_id, field, event.target.value)} />
                : <span className="agent-document__value">{valueText(field.value)}</span>}
              {field.description ? <small id={inputId + '-hint'}>{field.description}</small> : null}
              {draft[key] !== undefined ? <small className="agent-document__was">Было: {valueText(field.value)}</small> : null}
            </div>
          })}
          {block.fields.some(field => field.editable) ? <div className="agent-document__actions">
            <button className="agent-document__apply" type="submit" disabled={!block.fields.some(field => draft[block.source_id + ':' + field.id] !== undefined)}>{sending ? 'Отправляем…' : applying ? 'Агент применяет…' : 'Применить через агента'}</button>
            <button type="button" aria-label="Сбросить изменения в этой группе" disabled={!changed} onClick={() => setDraft(current => Object.fromEntries(Object.entries(current).filter(([key]) => !block.fields.some(field => key === block.source_id + ':' + field.id))))}><RotateCcw size={16} /><span>Сбросить</span></button>
          </div> : null}
        </fieldset>
      </form>)}
    {error ? <p className="agent-document__error" role="alert">{error}</p> : null}
    {applying ? <p className="agent-document__notice" role="status">Изменения переданы агенту. Ждём выполнения и проверки; значения ещё не подтверждены.</p> : null}
    {success || intent?.state === 'APPLIED' ? <p className="agent-document__success" role="status"><Check size={16} /> Нода подтвердила изменение.</p> : reply ? <p className="agent-document__notice" role="status">{reply.text}</p> : null}
  </article>
}
