export type RefreshFeedback = {
  state: 'idle' | 'running' | 'success' | 'error'
  message: string
}

export type OperationNotification = {
  id: number
  message: string
  failed: boolean
  createdAt: number
}
