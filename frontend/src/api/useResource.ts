import { useCallback, useEffect, useRef, useState } from 'react'
import { api, messageOf } from './client'

/**
 * Loads one thing from the API (a GET) and lets the page load it again after a change.
 *
 * While a reload is under way the old data stays on screen, so the page does not flicker back to
 * "Loading…" after every click. If answers arrive out of order, only the newest request counts.
 */
export function useResource<T>(path: string) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  // Counts requests; an answer is used only if no newer request has been started since.
  const newestRequest = useRef(0)

  const reload = useCallback(() => {
    const mine = ++newestRequest.current
    api<T>(path)
      .then((answer) => {
        if (mine !== newestRequest.current) return
        setData(answer)
        setError('')
        setLoading(false)
      })
      .catch((failure) => {
        if (mine !== newestRequest.current) return
        setError(messageOf(failure))
        setLoading(false)
      })
  }, [path])

  // Called when the page goes away or the address changes: any answer still on its way is stale.
  const ignoreAnswersInFlight = useCallback(() => {
    newestRequest.current++
  }, [])

  useEffect(() => {
    reload()
    return ignoreAnswersInFlight
  }, [reload, ignoreAnswersInFlight])

  return { data, error, loading, reload }
}
