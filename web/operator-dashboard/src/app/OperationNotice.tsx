import { useEffect } from 'react'

import { useNotificationSink } from '@/app/notification-context'

/** Compatibility bridge: mutation results flow into the shell notification dock. */
export function OperationNotice({ message }: { message: string; onDismiss?: () => void }) {
  const pushNotification = useNotificationSink()

  useEffect(() => {
    pushNotification?.(message)
  }, [message, pushNotification])

  return null
}
