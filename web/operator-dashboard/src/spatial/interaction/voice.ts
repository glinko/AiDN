import {
  SPATIAL_SCHEMA_VERSIONS,
  type SpatialAttachmentManifest,
} from '@/spatial/contracts'

import { IntentGateway, IntentGatewayError, type IntentSubmission } from './intent-gateway'

export type VoicePermissionState = 'prompt' | 'granted' | 'denied' | 'unavailable'
export type VoiceCaptureState = 'IDLE' | 'REQUESTING_PERMISSION' | 'READY' | 'RECORDING' | 'REVIEW' | 'SUBMITTING' | 'FAILED'

export type VoiceTranscript = {
  text: string
  is_final: boolean
  confidence: number | null
  updated_at: string
}

export type VoiceAdapterOptions = {
  gateway: IntentGateway
  actorRef: string
  workspaceId: string
  nodeId: string
  now?: () => Date
  idFactory?: (prefix: string) => string
  maxTranscriptChars?: number
  permission?: VoicePermissionState
  stt?: {
    start?: () => void | Promise<void>
    stop?: () => void | Promise<void>
    cancel?: () => void | Promise<void>
  }
  audioCapture?: {
    start?: () => void | Promise<void>
    stop?: () => void | Promise<void>
    cancel?: () => void | Promise<void>
  }
}

export class VoiceInteractionError extends Error {
  readonly code: 'PERMISSION_DENIED' | 'UNAVAILABLE' | 'NOT_RECORDING' | 'EMPTY_TRANSCRIPT' | 'INVALID_AUDIO_REF'

  constructor(code: VoiceInteractionError['code'], message: string) {
    super(message)
    this.name = 'VoiceInteractionError'
    this.code = code
  }
}

function defaultId(prefix: string): string {
  const uuid = typeof globalThis.crypto?.randomUUID === 'function' ? globalThis.crypto.randomUUID() : `${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
  return `${prefix}_${uuid}`
}

function iso(now: () => Date): string {
  return now().toISOString()
}

/** Explicit-permission voice adapter. It stores an audio reference, never audio bytes. */
export class VoiceInteractionAdapter {
  private readonly gateway: IntentGateway
  private readonly actorRef: string
  private readonly workspaceId: string
  private readonly nodeId: string
  private readonly now: () => Date
  private readonly idFactory: (prefix: string) => string
  private readonly maxTranscriptChars: number
  private readonly stt?: VoiceAdapterOptions['stt']
  private readonly audioCapture?: VoiceAdapterOptions['audioCapture']
  private permission: VoicePermissionState
  private state: VoiceCaptureState = 'IDLE'
  private transcript: VoiceTranscript = { text: '', is_final: false, confidence: null, updated_at: '' }
  private audioRef: SpatialAttachmentManifest | null = null
  private idempotencyKey: string | null = null

  constructor(options: VoiceAdapterOptions) {
    this.gateway = options.gateway
    this.actorRef = options.actorRef
    this.workspaceId = options.workspaceId
    this.nodeId = options.nodeId
    this.now = options.now ?? (() => new Date())
    this.idFactory = options.idFactory ?? defaultId
    this.maxTranscriptChars = Math.max(1, options.maxTranscriptChars ?? 32_000)
    this.permission = options.permission ?? 'prompt'
    this.stt = options.stt
    this.audioCapture = options.audioCapture
    this.transcript.updated_at = iso(this.now)
  }

  getSnapshot(): { permission: VoicePermissionState; state: VoiceCaptureState; transcript: VoiceTranscript; audioRef: SpatialAttachmentManifest | null } {
    return {
      permission: this.permission,
      state: this.state,
      transcript: { ...this.transcript },
      audioRef: this.audioRef ? { ...this.audioRef } : null,
    }
  }

  setPermission(permission: VoicePermissionState): void {
    this.permission = permission
    this.state = permission === 'granted' ? 'READY' : 'IDLE'
  }

  async requestPermission(requester: () => Promise<boolean> = async () => {
    if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) return false
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    stream.getTracks().forEach((track) => track.stop())
    return true
  }): Promise<VoicePermissionState> {
    if (this.permission === 'unavailable') return this.permission
    this.state = 'REQUESTING_PERMISSION'
    try {
      const granted = await requester()
      this.permission = granted ? 'granted' : 'denied'
      this.state = granted ? 'READY' : 'IDLE'
    } catch {
      this.permission = 'denied'
      this.state = 'IDLE'
    }
    return this.permission
  }

  async start(): Promise<void> {
    if (this.permission === 'unavailable') throw new VoiceInteractionError('UNAVAILABLE', 'voice input is unavailable')
    if (this.permission !== 'granted') throw new VoiceInteractionError('PERMISSION_DENIED', 'microphone permission is required')
    this.state = 'RECORDING'
    this.transcript = { text: '', is_final: false, confidence: null, updated_at: iso(this.now) }
    this.audioRef = null
    this.idempotencyKey = this.idFactory('voice-interaction')
    await this.stt?.start?.()
    await this.audioCapture?.start?.()
  }

  pushTranscript(text: string, options: { isFinal?: boolean; confidence?: number | null } = {}): VoiceTranscript {
    if (this.state !== 'RECORDING' && this.state !== 'REVIEW') throw new VoiceInteractionError('NOT_RECORDING', 'voice capture is not active')
    this.transcript = {
      text: text.slice(0, this.maxTranscriptChars),
      is_final: options.isFinal ?? false,
      confidence: options.confidence ?? null,
      updated_at: iso(this.now),
    }
    return { ...this.transcript }
  }

  async stop(audioRef?: Partial<Pick<SpatialAttachmentManifest, 'attachment_id' | 'mime_type' | 'size_bytes' | 'checksum'>> & { ref: string; kind?: 'audio' }): Promise<VoiceTranscript> {
    if (this.state !== 'RECORDING') throw new VoiceInteractionError('NOT_RECORDING', 'voice capture is not active')
    await this.stt?.stop?.()
    await this.audioCapture?.stop?.()
    this.state = 'REVIEW'
    this.transcript.is_final = true
    this.transcript.updated_at = iso(this.now)
    if (audioRef) {
      if (!audioRef.ref) throw new VoiceInteractionError('INVALID_AUDIO_REF', 'audio reference is required')
      this.audioRef = {
        schema_version: SPATIAL_SCHEMA_VERSIONS.attachmentManifest,
        attachment_id: audioRef.attachment_id || this.idFactory('audio'),
        kind: 'audio',
        ref: audioRef.ref,
        mime_type: audioRef.mime_type ?? 'audio/webm',
        size_bytes: audioRef.size_bytes ?? null,
        checksum: audioRef.checksum ?? null,
      }
    }
    return { ...this.transcript }
  }

  async cancel(): Promise<void> {
    await this.stt?.cancel?.()
    await this.audioCapture?.cancel?.()
    this.state = this.permission === 'granted' ? 'READY' : 'IDLE'
    this.transcript = { text: '', is_final: false, confidence: null, updated_at: iso(this.now) }
    this.audioRef = null
    this.idempotencyKey = null
  }

  editTranscript(text: string): VoiceTranscript {
    if (this.state !== 'REVIEW') throw new VoiceInteractionError('NOT_RECORDING', 'transcript is not ready for review')
    return this.pushTranscript(text, { isFinal: true, confidence: this.transcript.confidence })
  }

  async submit(currentRevision?: number): Promise<IntentSubmission> {
    if (this.state !== 'REVIEW') throw new VoiceInteractionError('NOT_RECORDING', 'review the transcript before submitting')
    if (!this.transcript.text.trim()) throw new VoiceInteractionError('EMPTY_TRANSCRIPT', 'voice transcript is empty')
    this.state = 'SUBMITTING'
    try {
      const submission = this.gateway.submit({
        actor_ref: this.actorRef,
        workspace_id: this.workspaceId,
        node_id: this.nodeId,
        modality: 'voice',
        intent_kind: 'message',
        text: this.transcript.text,
        attachments_manifest: this.audioRef ? [this.audioRef] : [],
        current_revision: currentRevision,
        idempotency_key: this.idempotencyKey ?? this.idFactory('voice-interaction'),
      })
      this.state = 'READY'
      return submission
    } catch (error) {
      this.state = 'FAILED'
      if (error instanceof IntentGatewayError) throw error
      throw error
    }
  }

  getFallbackMode(): 'text' | 'voice' {
    return this.permission === 'granted' ? 'voice' : 'text'
  }
}

export const VoiceAdapter = VoiceInteractionAdapter

export function createVoiceInteractionAdapter(options: VoiceAdapterOptions): VoiceInteractionAdapter {
  return new VoiceInteractionAdapter(options)
}
