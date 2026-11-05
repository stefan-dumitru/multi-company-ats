import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { stubFetch } from '@/test-utils'
import { useResource } from './useResource'

function Probe({ path }: { path: string }) {
  const { data, error, loading, reload } = useResource<string[]>(path)
  return (
    <div>
      {loading && <p>loading</p>}
      {error && <p>error: {error}</p>}
      {data && <p>data: {data.join(',')}</p>}
      <button onClick={() => reload()}>reload</button>
    </div>
  )
}

describe('useResource', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('is loading first, then has the data', async () => {
    stubFetch({ 'GET /api/things': { status: 200, body: ['a', 'b'] } })

    render(<Probe path="/api/things" />)

    expect(screen.getByText('loading')).toBeInTheDocument()
    expect(await screen.findByText('data: a,b')).toBeInTheDocument()
    expect(screen.queryByText('loading')).not.toBeInTheDocument()
  })

  it('reports a failure as a message instead of throwing', async () => {
    stubFetch({ 'GET /api/things': { status: 500 } })

    render(<Probe path="/api/things" />)

    expect(
      await screen.findByText('error: Something went wrong. Please try again.'),
    ).toBeInTheDocument()
  })

  it('asks again on reload and shows the newer answer', async () => {
    let answer = ['a']
    stubFetch({ 'GET /api/things': () => ({ status: 200, body: answer }) })
    render(<Probe path="/api/things" />)
    await screen.findByText('data: a')

    answer = ['a', 'b']
    fireEvent.click(screen.getByRole('button', { name: 'reload' }))

    expect(await screen.findByText('data: a,b')).toBeInTheDocument()
  })

  it('keeps showing the old data while a reload is under way (no flicker to "loading")', async () => {
    let finish: (value: unknown) => void = () => {}
    let first = true
    vi.stubGlobal(
      'fetch',
      vi.fn(() => {
        if (first) {
          first = false
          return Promise.resolve({ ok: true, status: 200, json: async () => ['a'] })
        }
        return new Promise((resolve) => {
          finish = resolve
        })
      }),
    )
    render(<Probe path="/api/things" />)
    await screen.findByText('data: a')

    fireEvent.click(screen.getByRole('button', { name: 'reload' }))

    expect(screen.getByText('data: a')).toBeInTheDocument()
    expect(screen.queryByText('loading')).not.toBeInTheDocument()
    await act(async () => finish({ ok: true, status: 200, json: async () => ['a', 'b'] }))
    expect(await screen.findByText('data: a,b')).toBeInTheDocument()
  })

  it('ignores a slow old answer that arrives after a newer one', async () => {
    const resolvers: Array<(value: unknown) => void> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise((resolve) => resolvers.push(resolve))),
    )
    render(<Probe path="/api/things" />)
    fireEvent.click(screen.getByRole('button', { name: 'reload' }))

    // The second request answers first; then the first, older one answers late with stale data.
    await act(async () => resolvers[1]({ ok: true, status: 200, json: async () => ['new'] }))
    await act(async () => resolvers[0]({ ok: true, status: 200, json: async () => ['old'] }))

    expect(screen.getByText('data: new')).toBeInTheDocument()
    expect(screen.queryByText('data: old')).not.toBeInTheDocument()
  })

  it('clears an earlier error once a reload succeeds', async () => {
    let healthy = false
    stubFetch({
      'GET /api/things': () => (healthy ? { status: 200, body: ['ok'] } : { status: 500 }),
    })
    render(<Probe path="/api/things" />)
    await screen.findByText(/error:/)

    healthy = true
    fireEvent.click(screen.getByRole('button', { name: 'reload' }))

    expect(await screen.findByText('data: ok')).toBeInTheDocument()
    expect(screen.queryByText(/error:/)).not.toBeInTheDocument()
  })
})
