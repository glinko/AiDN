import { FIXED_REQUEST_IDS } from './deterministic'

export const dashboardEventStreamFixture = [
  {
    event_id: 'event-00000001',
    event_type: 'provider.runtime.ready.v1',
    schema_version: 'operator-event.v1',
    correlation_id: FIXED_REQUEST_IDS[0],
    causation_id: null,
    occurred_at: '2026-09-04T12:00:00.000Z',
    payload: { provider_id: 'provider-fixture-1' },
  },
  {
    event_id: 'event-00000002',
    event_type: 'endpoint.published.v1',
    schema_version: 'operator-event.v1',
    correlation_id: FIXED_REQUEST_IDS[0],
    causation_id: 'event-00000001',
    occurred_at: '2026-09-04T12:00:01.000Z',
    payload: { endpoint_id: 'endpoint-fixture-1' },
  },
] as const
