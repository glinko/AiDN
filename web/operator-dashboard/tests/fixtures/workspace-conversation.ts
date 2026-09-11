import type { WorkspaceArtifact, WorkspacePublication } from '../../src/spatial/contracts/workspace-chat'

/** Synthetic transcript only. Does not describe or call a live node. */
export function workspaceDocument(id = 'session-test', texts = ['Тестовый вопрос', 'Тестовый ответ'], requestId = 'request-test'): NonNullable<WorkspacePublication['active']> {
  const timestamp = new Date().toISOString()
  const turns = texts.map((text, index) => ({
    schema_version: 'spatial.conversation-turn.v1' as const, turn_id: `${id}-turn-${index}`,
    session_id: id, workspace_id: 'workspace:test-node', node_id: 'test-node', revision: 1, sequence: index,
    role: index % 2 === 0 ? 'operator' as const : 'agent' as const, state: 'COMPLETED' as const, text,
    intent_id: requestId, provenance: { intent_id: requestId, correlation_id: requestId, binding_id: 'test-agent', source_ref: null },
    citation_refs: [], attachment_refs: [], created_at: timestamp, updated_at: timestamp,
  }))
  const shared = { session_id: id, workspace_id: 'workspace:test-node', node_id: 'test-node', revision: turns.length,
    title: texts[0]!.slice(0, 120), summary: texts.at(-1)!, turn_refs: turns.map(turn => turn.turn_id), object_refs: [],
    context_root_ref: 'context:' + id, created_at: timestamp, updated_at: timestamp }
  const artifact = { ...shared, schema_version: 'spatial.artifact.v1' as const, artifact_id: 'artifact:' + id, turn_count: turns.length,
    state: 'ACTIVE' as const, pinned: false, camera_snapshot: null }
  return { request_id: requestId, artifact, turns, session: { ...shared, schema_version: 'spatial.workspace-session.v1',
    state: texts.length % 2 ? 'SUBMITTING' : 'ACTIVE', root_intent_id: requestId, parent_session_id: null, structural_parent_ref: null,
    semantic_anchor: 'primary-agent', artifact_ref: artifact.artifact_id } }
}

export function workspaceArtifact(id: string, order: number): WorkspaceArtifact {
  return { order, artifact: workspaceDocument(id).artifact }
}
