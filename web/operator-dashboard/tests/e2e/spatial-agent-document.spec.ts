import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

for (const viewport of [{ name: 'desktop', width: 1280, height: 853 }, { name: 'mobile', width: 390, height: 844 }]) {
  test('agent documents, exact change events and no node API bypass — ' + viewport.name, async ({ page }, testInfo) => {
    // Cold shader compilation on software WebGL can outlast the default 30 s.
    test.setTimeout(90_000)
    await page.setViewportSize(viewport)
    await page.emulateMedia({ reducedMotion: 'reduce' })
    const unexpected: string[] = []
    const pageErrors: string[] = []
    page.on('pageerror', error => pageErrors.push(error.message))
    let surfaceId = 'pending'
    let temperature = 0.7
    let documentRevision = 1
    let sourceId = 'source-one'
    let documents: unknown[] = []
    let scene: unknown = null
    const intents: unknown[] = []
    const messages: unknown[] = []
    const changes: Array<Record<string, unknown>> = []
    const field = (id: string, label: string, type: string, value: unknown, editable: boolean, minimum: number | null = null, maximum: number | null = null) => ({ id, label, type, value, editable, minimum, maximum, options: [], description: '' })
    const makeDocument = (requestId: string) => ({
      schema_version: 'agent-document.v1', document_id: 'llama-settings', surface_id: surfaceId, request_id: requestId,
      title: 'Настройки llama.cpp', revision: documentRevision, updated_at: new Date().toISOString(),
      blocks: [
        { type: 'text', text: 'Тестовые данные для проверки интерфейса. Агент собрал только запрошенные параметры; это не конфигурация рабочей ноды.' },
        { type: 'fields', title: 'Параметры запросов', source_id: sourceId, source_revision: 'revision-' + documentRevision, target_id: 'ep-interface-test', fields: [
          field('display_name', 'Название', 'text', 'Локальная языковая модель', true),
          { ...field('parameter.temperature', 'Temperature', 'number', temperature, true, 0, 2), description: 'Вариативность ответа. Допустимый диапазон: 0–2.' },
          { ...field('parameter.max_tokens', 'Максимум токенов', 'integer', 1024, true, 1, 32768), description: 'Верхняя граница длины ответа.' },
          field('model_id', 'Модель', 'text', 'test-model-q8', false),
          { ...field('parameter.context_length', 'Контекст', 'integer', 32768, false), description: 'Изменение потребует новой ревизии Bundle.' },
        ] },
      ],
    })
    await page.route('**/operators/**', async route => {
      const request = route.request()
      const url = new URL(request.url())
      if (url.pathname.startsWith('/operators/dashboard/react/')) return route.continue()
      if (url.pathname === '/operators/dashboard/agent-channel' && request.method() === 'GET') {
        surfaceId = url.searchParams.get('surface_id') ?? surfaceId
        return route.fulfill({ json: { connected: true, agent_id: 'test-agent', messages, message_limit: 200,
          message_event_type: 'aidn.operator.agent_message', media: { text: true, attachments: false, detail: 'text' },
          interface: { documents, intents, scene },
        } })
      }
      if (url.pathname === '/operators/dashboard/agent-channel/messages' && request.method() === 'POST') {
        const body = request.postDataJSON()
        surfaceId = body.surface_id
        messages.push({ message_id: 'operator-' + body.request_id, direction: 'OPERATOR', agent_id: 'test-agent', text: body.text,
          created_at: new Date().toISOString(), request_id: body.request_id, surface_id: surfaceId })
        if (body.request_id.startsWith('scene-')) {
          const resources = { cpu: 0, ram_mb: 0, vram_mb: 0 }
          scene = { source_id: 'scene-source', revision: 'scene-one', observed_at: new Date().toISOString(), data: {
            node_id: 'test-node', agent_id: 'test-agent', fleet: { node: { node_id: 'test-node' }, resources: { total: resources, reserved: resources, free: resources }, queue: { queued: 0, active: 0, completed: 0, failed: 0 }, bundles: [] },
            endpoints: { summary: { total: 0 }, items: [] }, sessions: { summary: { total: 0 }, items: [] }, failures: [],
          } }
        } else if (body.interaction) {
          changes.push(body.interaction)
          temperature = body.interaction.proposed['parameter.temperature']
          documentRevision += 1
          sourceId = 'source-two'
          documents = [makeDocument(body.request_id)]
          intents.push({ intent_id: body.request_id, surface_id: surfaceId, change: body.interaction, state: 'APPLIED', result: { verified: true } })
        } else { documents = [makeDocument(body.request_id)] }
        messages.push({ message_id: 'agent-' + body.request_id, direction: 'AGENT', agent_id: 'test-agent', text: 'Подготовил запрошенные данные.',
          created_at: new Date().toISOString(), request_id: body.request_id, surface_id: surfaceId })
        return route.fulfill({ json: { message_id: 'operator-' + body.request_id } })
      }
      unexpected.push(request.method() + ' ' + url.pathname)
      return route.fulfill({ status: 500, json: { detail: 'Direct node request is forbidden in this test' } })
    })
    await page.goto('/operators/dashboard/react/spatial-calibration.html')
    await expect(page.locator('.pearl-study')).toHaveAttribute('data-scene-ready', 'true', { timeout: 30_000 })
    await expect(page.locator('.pearl-study')).toHaveAttribute('data-scene-source', 'agent', { timeout: 20_000 })
    await expect(page.getByRole('button', { name: 'Отправить агенту', exact: true })).toBeDisabled()
    await page.getByRole('textbox', { name: 'Сообщение основному агенту' }).fill('Покажи настройки llama.cpp')
    await expect(page.getByRole('button', { name: 'Отправить агенту', exact: true })).toBeEnabled()
    await page.getByRole('button', { name: 'Отправить агенту', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Настройки llama.cpp' })).toBeVisible({ timeout: 15_000 })
    await expect(page.getByRole('spinbutton', { name: 'Temperature', exact: true })).toHaveValue('0.7')
    await expect(page.locator('.pearl-study')).toHaveAttribute('data-scene-ready', 'true')
    await page.screenshot({ path: testInfo.outputPath('agent-document-' + viewport.name + '.png') })
    const a11y = await new AxeBuilder({ page }).include('.agent-frame').include('.agent-composer').analyze()
    expect(a11y.violations).toEqual([])
    const frame = page.locator('.agent-frame')
    const bounds = await frame.boundingBox()
    expect(bounds).not.toBeNull()
    expect(bounds!.x).toBeGreaterThanOrEqual(0)
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(viewport.width)
    const input = page.getByRole('spinbutton', { name: 'Temperature', exact: true })
    await input.fill('0.4')
    await page.getByRole('button', { name: 'Применить через агента' }).click()
    await expect(page.getByText('Нода подтвердила изменение.')).toBeVisible()
    expect(changes).toHaveLength(1)
    expect(changes[0]).toMatchObject({ current: { 'parameter.temperature': 0.7 }, proposed: { 'parameter.temperature': 0.4 }, document_revision: 1 })
    await expect(input).toHaveValue('0.4')
    await page.getByRole('button', { name: 'Свернуть frame' }).click()
    await expect(frame).toBeHidden()
    await page.screenshot({ path: testInfo.outputPath('agent-scene-' + viewport.name + '.png') })
    expect(unexpected).toEqual([])
    expect(pageErrors).toEqual([])
  })
}
