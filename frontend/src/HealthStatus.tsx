import { useEffect, useState } from 'react'

type BackendState = 'checking' | 'healthy' | 'unreachable'

const messages: Record<BackendState, string> = {
  checking: 'Checking the backend…',
  healthy: 'Backend is healthy.',
  unreachable: 'Backend is unreachable.',
}

export default function HealthStatus() {
  const [state, setState] = useState<BackendState>('checking')

  useEffect(() => {
    // If the component unmounts before the answer arrives, do not update state on it.
    let ignoreAnswer = false

    async function checkBackend() {
      let result: BackendState
      try {
        const response = await fetch('/health')
        const body = await response.json()
        // Both must hold: an HTTP 200 alone is not enough if the body says otherwise.
        result = response.ok && body.status === 'ok' ? 'healthy' : 'unreachable'
      } catch {
        // Network failure, or a non-JSON answer from a proxy: either way the backend is not usable.
        result = 'unreachable'
      }
      if (!ignoreAnswer) {
        setState(result)
      }
    }

    void checkBackend()
    return () => {
      ignoreAnswer = true
    }
  }, [])

  return <p role="status">{messages[state]}</p>
}
