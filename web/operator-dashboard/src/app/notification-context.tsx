import { createContext, useContext } from 'react'

export type NotificationSink = (message: string) => void

/** Shared shell seam for transient mutation results and refresh notices. */
export const NotificationContext = createContext<NotificationSink | null>(null)

export function useNotificationSink(): NotificationSink | null {
  return useContext(NotificationContext)
}
