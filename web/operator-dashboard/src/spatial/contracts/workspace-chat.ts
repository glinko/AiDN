import { z } from 'zod'
import { spatialArtifactSchema, spatialConversationTurnSchema, spatialWorkspaceSessionSchema } from './index'

export const workspaceChatIntentSchema = z.object({
  conversation_id: z.string().min(1).max(128).regex(/^[A-Za-z0-9_.:-]+$/),
  action: z.enum(['message', 'open']),
}).strict()

export const workspacePublicationSchema = z.object({
  revision: z.number().int().nonnegative(),
  artifacts: z.array(z.object({ artifact: spatialArtifactSchema, order: z.number().int().nonnegative() }).strict()).max(128),
  active: z.object({
    session: spatialWorkspaceSessionSchema,
    artifact: spatialArtifactSchema,
    turns: z.array(spatialConversationTurnSchema).max(2000),
    request_id: z.string(),
  }).strict().nullable(),
}).strict()

export type WorkspaceChatIntent = z.infer<typeof workspaceChatIntentSchema>
export type WorkspacePublication = z.infer<typeof workspacePublicationSchema>
export type WorkspaceArtifact = WorkspacePublication['artifacts'][number]
