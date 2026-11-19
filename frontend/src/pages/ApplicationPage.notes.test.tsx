import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import type { User } from '@/auth/types'
import { formatDate } from '@/lib/format'
import type { Reply } from '@/test-utils'
import { adminUser, recruiterUser, sessionFor, stubBackend } from '@/test-utils'
import { press, renderApp } from '@/test-render'
import type { ApplicationDetail } from './application/types'

interface Note {
  id: string
  author_name: string
  body: string
  created_at: string
}

const APPLICATION: ApplicationDetail = {
  id: 'a1',
  job_id: 'j1',
  job_title: 'Backend Engineer',
  candidate_name: 'Cara Candidate',
  candidate_email: 'cara@example.test',
  candidate_phone: null,
  candidate_location: null,
  stage: 'applied',
  next_stage: 'screening',
  version: 1,
  applied_at: '2026-11-10T09:00:00Z',
  rejection: null,
  history: [],
}

function note(overrides: Partial<Note> = {}): Note {
  return {
    id: 'n1',
    author_name: 'Rae Recruiter',
    body: 'Strong on systems.',
    created_at: '2026-11-11T09:00:00Z',
    ...overrides,
  }
}

/** The page's backend; `notes` is kept newest first, as the real server answers. */
function startServer(options: { user?: User; notes?: Note[] } = {}) {
  const user = options.user ?? recruiterUser
  const state = {
    notes: options.notes ?? [],
    failNext: {} as Record<string, Reply>,
    nextId: 100,
  }

  const backend = stubBackend((call) => {
    const url = new URL(call.path, 'http://app.test')
    const key = `${call.method} ${url.pathname}`
    const planned = state.failNext[key]
    if (planned) {
      delete state.failNext[key]
      return planned
    }
    if (key === 'GET /health') return { status: 200, body: { status: 'ok' } }
    if (key === 'GET /api/auth/me') return { status: 200, body: sessionFor(user) }
    if (key === 'GET /api/applications/a1') return { status: 200, body: APPLICATION }
    if (key === 'GET /api/applications/a1/interviews') return { status: 200, body: [] }
    if (key === 'GET /api/applications/a1/notes') {
      const page = Number(url.searchParams.get('page') ?? '1')
      const size = Number(url.searchParams.get('page_size') ?? '20')
      const items = state.notes.slice((page - 1) * size, page * size)
      return { status: 200, body: { items, total: state.notes.length, page, page_size: size } }
    }
    if (key === 'POST /api/applications/a1/notes') {
      const created = note({
        id: `n${state.nextId++}`,
        author_name: user.full_name,
        body: (call.body as { body: string }).body,
        created_at: '2026-11-12T10:00:00Z',
      })
      state.notes.unshift(created)
      return { status: 201, body: created }
    }
    throw new Error(`Unplanned request in test: ${key}`)
  })

  return { state, calls: backend.calls }
}

async function openPage() {
  renderApp('/manage/applications/a1')
  await screen.findByRole('heading', { name: 'Cara Candidate' })
}

function section() {
  return within(screen.getByRole('region', { name: 'Notes' }))
}

describe('ApplicationPage: notes', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })
  afterEach(() => vi.unstubAllGlobals())

  it('lists the notes as the server sends them, with who wrote them and when', async () => {
    startServer({
      notes: [
        note({ id: 'n2', author_name: 'Ren Recruiter', body: 'Second call went well.' }),
        note({
          id: 'n1',
          body: 'First impression: promising.',
          created_at: '2026-11-01T09:00:00Z',
        }),
      ],
    })
    await openPage()

    await section().findByText('Second call went well.')
    const items = section().getAllByRole('listitem')
    expect(items[0]).toHaveTextContent('Ren Recruiter')
    expect(items[0]).toHaveTextContent('Second call went well.')
    expect(items[1]).toHaveTextContent('First impression: promising.')
    expect(items[1]).toHaveTextContent(formatDate('2026-11-01T09:00:00Z'))
  })

  it('shows a note as text, with its line breaks, never as markup', async () => {
    startServer({ notes: [note({ body: '<b>Bold</b> claim\nsecond line' })] })
    await openPage()

    const text = await section().findByText(/Bold.*claim/)

    expect(text.textContent).toBe('<b>Bold</b> claim\nsecond line')
    expect(text).toHaveClass('whitespace-pre-wrap')
    expect(document.querySelector('main b')).toBeNull()
  })

  it('says so when there are no notes yet', async () => {
    startServer()
    await openPage()

    expect(await section().findByText(/no notes yet/i)).toBeInTheDocument()
  })

  it('lets a recruiter add a note, which then appears first, and empties the box', async () => {
    const server = startServer({ notes: [note()] })
    await openPage()
    await section().findByText('Strong on systems.')

    fireEvent.change(section().getByLabelText(/add a note/i), {
      target: { value: '  Call back on Friday.  ' },
    })
    fireEvent.click(section().getByRole('button', { name: 'Add note' }))

    await waitFor(() =>
      expect(section().getAllByRole('listitem')[0]).toHaveTextContent('Call back on Friday.'),
    )
    expect(section().getByLabelText(/add a note/i)).toHaveValue('')
    const post = server.calls.find((call) => call.method === 'POST')
    expect(post?.path).toBe('/api/applications/a1/notes')
    expect(post?.body).toEqual({ body: 'Call back on Friday.' }) // trimmed, and only the words
  })

  it('does not let a blank note be sent', async () => {
    const server = startServer()
    await openPage()
    await section().findByText(/no notes yet/i)
    const add = section().getByRole('button', { name: 'Add note' })

    expect(add).toBeDisabled()
    fireEvent.change(section().getByLabelText(/add a note/i), { target: { value: '   \n ' } })
    expect(add).toBeDisabled()
    fireEvent.click(add)

    expect(server.calls.some((call) => call.method === 'POST')).toBe(false)
  })

  it('limits a note to the length the server accepts', async () => {
    startServer()
    await openPage()

    expect(await section().findByLabelText(/add a note/i)).toHaveAttribute('maxlength', '4000')
  })

  it('keeps what was typed and says why when a note could not be added', async () => {
    const server = startServer()
    await openPage()
    await section().findByText(/no notes yet/i)
    server.state.failNext['POST /api/applications/a1/notes'] = {
      status: 500,
      body: {},
    }

    fireEvent.change(section().getByLabelText(/add a note/i), {
      target: { value: 'Do not lose me' },
    })
    fireEvent.click(section().getByRole('button', { name: 'Add note' }))

    expect(await section().findByRole('alert')).toBeInTheDocument()
    expect(section().getByLabelText(/add a note/i)).toHaveValue('Do not lose me')
    expect(section().queryByText('Do not lose me', { selector: 'p' })).not.toBeInTheDocument()
  })

  it('switches the button off while a note is being sent', async () => {
    startServer()
    await openPage()
    await section().findByText(/no notes yet/i)
    fireEvent.change(section().getByLabelText(/add a note/i), { target: { value: 'Once only' } })

    fireEvent.click(section().getByRole('button', { name: 'Add note' }))

    // Straight after the click, while the request is still running and the text is still there.
    expect(section().getByRole('button', { name: 'Add note' })).toBeDisabled()
    await section().findByText('Once only')
  })

  it('shows a company admin the notes but no way to add one', async () => {
    startServer({ user: adminUser, notes: [note()] })
    await openPage()

    expect(await section().findByText('Strong on systems.')).toBeInTheDocument()
    expect(section().queryByLabelText(/add a note/i)).not.toBeInTheDocument()
    expect(section().queryByRole('button', { name: 'Add note' })).not.toBeInTheDocument()
  })

  it('pages through a long list', async () => {
    const many = Array.from({ length: 21 }, (_, index) =>
      note({ id: `n${index}`, body: `Note number ${index}` }),
    )
    startServer({ notes: many })
    await openPage()
    await section().findByText('Note number 0')
    expect(section().queryByText('Note number 20')).not.toBeInTheDocument()

    press('Next')

    expect(await section().findByText('Note number 20')).toBeInTheDocument()
  })

  it('keeps the rest of the page working when the notes fail to load, and can retry', async () => {
    const server = startServer({ notes: [note()] })
    server.state.failNext['GET /api/applications/a1/notes'] = { status: 500, body: {} }
    await openPage()

    expect(await section().findByRole('alert')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Move to Screening' })).toBeInTheDocument()

    fireEvent.click(section().getByRole('button', { name: /try again/i }))

    expect(await section().findByText('Strong on systems.')).toBeInTheDocument()
  })
})
