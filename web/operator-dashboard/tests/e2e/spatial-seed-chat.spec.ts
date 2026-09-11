import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { PerspectiveCamera, Vector3 } from 'three'
import { WorkspaceArtifactEntity } from '../../src/spatial-calibration/workspace-artifacts'
import type { WorkspacePublication } from '../../src/spatial/contracts/workspace-chat'
import { workspaceDocument } from '../fixtures/workspace-conversation'

test.use({ video: 'off' })

for (const viewport of [{ name: 'desktop', width: 1280, height: 853 }, { name: 'mobile', width: 390, height: 844 }]) {
  test.describe(viewport.name, () => {
    test.use({ viewport, hasTouch: viewport.name === 'mobile', isMobile: viewport.name === 'mobile' })
    test('empty-space seed, persistent chat, cube and reopen through agent only', async ({ page }, testInfo) => {
      test.setTimeout(240_000) // Software WebGL, optical transmission and a full reload.
      await page.emulateMedia({ reducedMotion: 'reduce' })
      const unexpected: string[] = []
      const pageErrors: string[] = []
      const requests: Array<{ request_id: string; text: string; chat?: { conversation_id: string; action: string } }> = []
      const messages: unknown[] = []
      const archive = new Map<string, ReturnType<typeof workspaceDocument>>()
      let workspace: WorkspacePublication = { revision: 0, artifacts: [], active: null }
      let scene: unknown = null
      page.on('pageerror', error => pageErrors.push(error.message))
      await page.route('**/operators/**', async route => {
        const request = route.request()
        const url = new URL(request.url())
        if (url.pathname.startsWith('/operators/dashboard/react/')) return route.continue()
        if (url.pathname === '/operators/dashboard/agent-channel' && request.method() === 'GET') {
          return route.fulfill({ json: { connected: true, agent_id: 'test-agent', messages, workspace,
            message_limit: 200, message_event_type: 'aidn.operator.agent_message', media: { text: true, attachments: false, detail: 'text' },
            interface: { documents: [], intents: [], scene } } })
        }
        if (url.pathname === '/operators/dashboard/agent-channel/messages' && request.method() === 'POST') {
          const body = request.postDataJSON()
          requests.push(body)
          const base = { agent_id: 'test-agent', created_at: new Date().toISOString(), request_id: body.request_id, surface_id: body.surface_id, chat: body.chat ?? null }
          messages.push({ ...base, message_id: 'op-' + body.request_id, direction: 'OPERATOR', text: body.text })
          if (body.request_id.startsWith('scene-')) {
            const resources = { cpu: 0, ram_mb: 0, vram_mb: 0 }
            scene = { source_id: 'scene-source', revision: 'scene-one', observed_at: new Date().toISOString(), data: {
              node_id: 'test-node', agent_id: 'test-agent', fleet: { node: { node_id: 'test-node' }, resources: { total: resources, reserved: resources, free: resources }, queue: { queued: 0, active: 0, completed: 0, failed: 0 }, bundles: [] },
              endpoints: { summary: { total: 0 }, items: [] }, sessions: { summary: { total: 0 }, items: [] }, failures: [],
            } }
          } else if (body.chat) {
            const id = body.chat.conversation_id
            if (body.chat.action === 'open') {
              workspace = { ...workspace, active: { ...archive.get(id)!, request_id: body.request_id } }
            } else {
              const texts = archive.get(id)?.turns.map(turn => turn.text) ?? []
              const document = workspaceDocument(id, [...texts, body.text, texts.length ? 'Тестовый ответ: продолжаем в той же сессии.' : 'Тестовый ответ агента. Это синтетическая переписка для проверки интерфейса.'], body.request_id)
              archive.set(id, document)
              workspace = { revision: workspace.revision + 1, active: document,
                artifacts: [...archive.values()].map((item, order) => ({ artifact: item.artifact, order })) }
            }
          }
          messages.push({ ...base, message_id: 'agent-' + body.request_id, direction: 'AGENT', text: 'Ответ опубликован.' })
          return route.fulfill({ json: { message_id: 'op-' + body.request_id } })
        }
        unexpected.push(request.method() + ' ' + url.pathname)
        return route.fulfill({ status: 500, json: { detail: 'Direct node API forbidden' } })
      })
      await page.goto('/operators/dashboard/react/spatial-calibration.html')
      await expect(page.locator('.pearl-study')).toHaveAttribute('data-scene-ready', 'true', { timeout: 40_000 })
      await expect(page.locator('.pearl-study')).toHaveAttribute('data-scene-source', 'agent', { timeout: 25_000 })
      const point = { x: viewport.width * 0.26, y: viewport.height * 0.62 }
      // A drag starts over empty ground but must not create a conversation.
      await page.mouse.move(point.x, point.y)
      await page.mouse.down()
      await page.mouse.move(point.x + 60, point.y + 15, { steps: 4 })
      await page.mouse.up()
      await expect(page.locator('.seed-chat')).toHaveCount(0)
      await page.getByRole('button', { name: 'Вернуть исходный ракурс' }).click()
      if (viewport.name === 'mobile') await page.touchscreen.tap(point.x, point.y)
      else await page.mouse.click(point.x, point.y)
      const seed = page.getByRole('region', { name: 'Диалог в пространстве' })
      await expect(seed).toHaveAttribute('data-expanded', 'false')
      const input = page.getByRole('textbox', { name: 'Сообщение в пространстве' })
      await expect(input).toBeFocused()
      await expect(page.locator('.pearl-study')).toHaveAttribute('data-workspace-artifacts', '0')
      await input.focus()
      await page.screenshot({ path: testInfo.outputPath('seed-' + viewport.name + '.png'), caret: 'initial' })
      const identity = await input.getAttribute('id')
      await input.fill('Расскажи, что сейчас происходит на ноде')
      await input.press('Enter')
      await input.pressSequentially('И какие задачи ожидают решения?')
      expect(requests.filter(item => item.chat)).toHaveLength(0)
      await expect(seed).toHaveAttribute('data-expanded', 'true')
      await expect(input).toHaveAttribute('id', identity!)
      await input.press('Control+Enter')
      await expect(seed.getByText('Тестовый ответ агента. Это синтетическая переписка для проверки интерфейса.')).toBeVisible({ timeout: 20_000 })
      await expect(page.locator('.pearl-study')).toHaveAttribute('data-workspace-artifacts', '1')
      await input.fill('Продолжим этот же разговор.')
      await page.getByRole('button', { name: 'Отправить в этот диалог' }).click()
      await expect(seed.getByText('Тестовый ответ: продолжаем в той же сессии.')).toBeVisible()
      await expect(input).toHaveAttribute('id', identity!)
      const chatRequests = requests.filter(item => item.chat?.action === 'message')
      expect(chatRequests).toHaveLength(2)
      expect(chatRequests[0]!.chat!.conversation_id).toBe(chatRequests[1]!.chat!.conversation_id)
      expect(archive.size).toBe(1)
      const bounds = (await seed.boundingBox())!
      expect(bounds.x).toBeGreaterThanOrEqual(0)
      expect(bounds.y).toBeGreaterThanOrEqual(0)
      expect(bounds.x + bounds.width).toBeLessThanOrEqual(viewport.width)
      expect(bounds.y + bounds.height).toBeLessThanOrEqual(viewport.height)
      await page.screenshot({ path: testInfo.outputPath('conversation-' + viewport.name + '.png') })
      const a11y = await new AxeBuilder({ page }).include('.seed-chat').analyze()
      expect(a11y.violations).toEqual([])
      await page.getByRole('button', { name: 'Свернуть этот диалог' }).click()
      await expect(seed).toHaveCount(0)

      // Exercise the physical cube hit path on desktop; portrait deliberately
      // crops the world, so its full-history navigator is the accessible fallback.
      if (viewport.name === 'desktop') {
        const cube = new WorkspaceArtifactEntity(workspace.artifacts[0]!, 0, false)
        const camera = new PerspectiveCamera(33, viewport.width / viewport.height, 0.1, 180)
        camera.position.set(-1.05, 3.72, 11.8)
        camera.lookAt(-1.1, 1.92, 0)
        camera.updateMatrixWorld()
        const projected = new Vector3(...cube.position).project(camera)
        await page.mouse.click((projected.x + 1) * viewport.width / 2, (1 - projected.y) * viewport.height / 2)
      } else {
        await page.getByRole('button', { name: 'Диалоги · 1', exact: true }).click()
        await page.getByRole('navigation', { name: 'Открыть сохранённый диалог' }).getByRole('button').click()
      }
      await expect(seed.getByText('Тестовый ответ: продолжаем в той же сессии.')).toBeVisible()
      expect(requests.filter(item => item.chat?.action === 'open')).toHaveLength(1)
      expect(archive.size).toBe(1)
      await page.getByRole('button', { name: 'Свернуть этот диалог' }).click()
      await page.reload()
      await expect(page.locator('.pearl-study')).toHaveAttribute('data-scene-ready', 'true', { timeout: 40_000 })
      await expect(page.locator('.pearl-study')).toHaveAttribute('data-workspace-artifacts', '1')
      // Keyboard opening also works if WebGL cannot be used.
      await page.keyboard.press('Control+i')
      await expect(seed).toHaveAttribute('data-expanded', 'false')
      await page.getByRole('textbox', { name: 'Сообщение в пространстве' }).fill('Второй тестовый диалог')
      await page.getByRole('button', { name: 'Отправить в этот диалог' }).click()
      await expect(page.locator('.pearl-study')).toHaveAttribute('data-workspace-artifacts', '2', { timeout: 20_000 })
      expect(archive.size).toBe(2)
      await page.getByRole('button', { name: 'Свернуть этот диалог' }).click()
      await page.screenshot({ path: testInfo.outputPath('artifact-field-' + viewport.name + '.png') })
      expect(unexpected).toEqual([])
      expect(pageErrors).toEqual([])
    })
  })
}
