import { useEffect, useRef, useState } from 'react'

/** Conexión WebSocket con reconexión automática. `onMessage` recibe cada evento. */
export function useRealtime(enabled, onMessage, onReconnect) {
  const [connected, setConnected] = useState(false)
  const handlers = useRef({ onMessage, onReconnect })
  handlers.current = { onMessage, onReconnect }

  useEffect(() => {
    if (!enabled) return undefined
    let ws = null
    let closed = false
    let retry = 1000
    let timer = null
    let ping = null
    let firstOpen = true

    const connect = () => {
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${window.location.host}/ws/ui`)
      ws.onopen = () => {
        setConnected(true)
        retry = 1000
        if (!firstOpen) handlers.current.onReconnect?.()
        firstOpen = false
        ping = setInterval(() => ws?.readyState === 1 && ws.send('ping'), 25000)
      }
      ws.onmessage = (e) => {
        try {
          handlers.current.onMessage(JSON.parse(e.data))
        } catch {
          /* mensaje inválido */
        }
      }
      ws.onclose = () => {
        setConnected(false)
        clearInterval(ping)
        if (!closed) {
          timer = setTimeout(connect, retry)
          retry = Math.min(retry * 2, 15000)
        }
      }
    }
    connect()
    return () => {
      closed = true
      clearTimeout(timer)
      clearInterval(ping)
      ws?.close()
    }
  }, [enabled])

  return connected
}
