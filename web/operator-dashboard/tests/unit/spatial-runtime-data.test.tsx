import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import {
  MOCK_SPATIAL_SCOPE,
  createPrimaryAgentSlot,
  createMockSpatialWorkspaceData,
  mockSpatialEventStream,
  useSpatialWorkspaceData,
} from '@/spatial/data'

function Probe(props: { scope?: { hypervisor_id: string; node_id: string }; mode?: 'mock-real' | 'offline' | 'empty' | 'malformed'; stream?: readonly unknown[] }) {
  const data = useSpatialWorkspaceData({ scope: props.scope, mode: props.mode, eventStream: props.stream })
  return (
    <output
      data-testid="spatial-probe"
      data-node={data.scope.node_id}
      data-state={data.state}
      data-revision={data.projection.sourceRevision}
      data-last-event={data.lastEvent?.event_id ?? 'none'}
      data-runtime-state={data.projection.entities.find((entity) => entity.id === 'endpoint-runtime')?.visualState ?? 'missing'}
      data-agent-lifecycle={data.primaryAgentSlot.lifecycle_state}
      data-agent-state={data.primaryAgentOperationalState?.state ?? 'none'}
    >
      {data.state}
    </output>
  )
}

function renderProbe(props: React.ComponentProps<typeof Probe> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}><Probe {...props} /></QueryClientProvider>)
}

describe('Spatial M2.7 runtime data path', () => {
  it('materializes mock-real data and applies a retained endpoint recovery stream', async () => {
    renderProbe({ stream: mockSpatialEventStream })
    const probe = screen.getByTestId('spatial-probe')
    expect(probe).toHaveAttribute('data-state', 'ready')
    await waitFor(() => expect(probe).toHaveAttribute('data-last-event', 'mock-event-3'))
    expect(probe).toHaveAttribute('data-runtime-state', 'healthy')
    expect(Number(probe.getAttribute('data-revision'))).toBeGreaterThan(1)
  })

  it('keeps live Primary Agent slot and state events in the cache-to-view-model path', async () => {
    const slot = {
      ...createPrimaryAgentSlot(MOCK_SPATIAL_SCOPE, { now: new Date('2026-09-05T16:00:00.000Z') }),
      current_binding_id: 'binding-runtime-live',
      lifecycle_state: 'CONNECTED' as const,
      revision: 1,
      assigned_at: '2026-09-05T16:00:00.000Z',
      assigned_by: 'operator:runtime',
      last_seen_at: '2026-09-05T16:00:00.000Z',
      changed_at: '2026-09-05T16:00:00.000Z',
    }
    const state = {
      schema_version: 'spatial.primary-agent-state.v1',
      node_id: MOCK_SPATIAL_SCOPE.node_id,
      slot_id: slot.slot_id,
      binding_id: slot.current_binding_id,
      state: 'THINKING',
      attention_severity: 'NONE',
      source: 'runtime.fixture',
      revision: 1,
      observed_at: '2026-09-05T16:00:00.000Z',
      last_successful_response_at: null,
      last_failed_response_at: null,
    }
    renderProbe({ stream: [
      { event_id: 'runtime-binding-1', event_type: 'spatial.primary-agent.binding-changed.v1', schema_version: 'spatial.primary-agent-slot.v1', node_id: MOCK_SPATIAL_SCOPE.node_id, sequence: 1, revision: 1, occurred_at: '2026-09-05T16:00:00Z', correlation_id: null, causation_id: null, payload: slot },
      { event_id: 'runtime-state-1', event_type: 'spatial.primary-agent.state-changed.v1', schema_version: 'spatial.primary-agent-state.v1', node_id: MOCK_SPATIAL_SCOPE.node_id, sequence: 2, revision: 1, occurred_at: '2026-09-05T16:00:00Z', correlation_id: null, causation_id: null, payload: state },
    ] })
    const probe = screen.getByTestId('spatial-probe')
    await waitFor(() => expect(probe).toHaveAttribute('data-agent-lifecycle', 'CONNECTED'))
    expect(probe).toHaveAttribute('data-agent-state', 'THINKING')
  })

  it('destroys the previous Node projection when the scoped query changes', async () => {
    const { rerender } = renderProbe()
    const probe = screen.getByTestId('spatial-probe')
    expect(probe).toHaveAttribute('data-node', MOCK_SPATIAL_SCOPE.node_id)
    rerender(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <Probe scope={{ hypervisor_id: 'hypervisor-two', node_id: 'node-two' }} />
      </QueryClientProvider>,
    )
    await waitFor(() => expect(probe).toHaveAttribute('data-node', 'node-two'))
    expect(probe).toHaveAttribute('data-state', 'ready')
  })

  it('keeps empty, offline, and malformed states explicit', async () => {
    expect(createMockSpatialWorkspaceData('desktop', 'empty').state).toBe('empty')
    expect(createMockSpatialWorkspaceData('desktop', 'offline').state).toBe('offline')
    renderProbe({ mode: 'malformed' })
    await waitFor(() => expect(screen.getByTestId('spatial-probe')).toHaveAttribute('data-state', 'error'))
  })
})
