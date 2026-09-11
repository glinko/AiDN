import { z } from 'zod'

const id = z.string().min(1).max(128).regex(/^[A-Za-z0-9_.:-]+$/)
export const agentFieldValueSchema = z.union([z.string().max(8000), z.boolean(), z.number().finite(), z.null()])
export const agentDocumentFieldSchema = z.object({
  id, label: z.string().min(1).max(240),
  type: z.enum(['text', 'number', 'integer', 'boolean', 'select']),
  value: agentFieldValueSchema, editable: z.boolean(),
  description: z.string().max(1000),
  minimum: z.number().nullable(), maximum: z.number().nullable(),
  options: z.array(z.string()).max(64),
}).strict()

export const agentDocumentSchema = z.object({
  schema_version: z.literal('agent-document.v1'),
  document_id: id, surface_id: id, request_id: id,
  title: z.string().min(1).max(240), revision: z.number().int().positive(), updated_at: z.string(),
  blocks: z.array(z.discriminatedUnion('type', [
    z.object({ type: z.literal('text'), text: z.string().min(1).max(8000) }).strict(),
    z.object({ type: z.literal('fields'), title: z.string().max(240), source_id: id,
      source_revision: z.string().min(1).max(128), target_id: z.string().min(1),
      fields: z.array(agentDocumentFieldSchema).max(64),
    }).strict(),
  ])).min(1).max(16),
}).strict()

export const agentFormChangeSchema = z.object({
  kind: z.literal('form_change'), document_id: id, document_revision: z.number().int().positive(),
  source_id: id, source_revision: z.string().min(1).max(128),
  current: z.record(id, agentFieldValueSchema), proposed: z.record(id, agentFieldValueSchema),
}).strict()

export const agentInterfaceSchema = z.object({
  documents: z.array(agentDocumentSchema).max(8).default([]),
  intents: z.array(z.object({
    intent_id: id, surface_id: id, change: agentFormChangeSchema,
    state: z.enum(['PROPOSED', 'APPLIED']),
    result: z.record(z.string(), z.unknown()).nullable(),
  }).passthrough()).max(64).default([]),
  scene: z.object({ source_id: id, revision: z.string(), observed_at: z.string(), data: z.record(z.string(), z.unknown()) }).strict().nullable().default(null),
}).strict()

export type AgentDocument = z.infer<typeof agentDocumentSchema>
export type AgentDocumentField = z.infer<typeof agentDocumentFieldSchema>
export type AgentFieldValue = z.infer<typeof agentFieldValueSchema>
export type AgentFormChange = z.infer<typeof agentFormChangeSchema>
export type AgentInterface = z.infer<typeof agentInterfaceSchema>
