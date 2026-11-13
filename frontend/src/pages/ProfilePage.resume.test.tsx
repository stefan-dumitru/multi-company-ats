import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import { formatDate } from '@/lib/format'
import type { Reply } from '@/test-utils'
import { candidateUser, sessionFor, stubBackend } from '@/test-utils'
import { renderApp } from '@/test-render'

interface ResumeInfo {
  filename: string
  size_bytes: number
  uploaded_at: string
}

interface ProfileData {
  full_name: string
  email: string
  phone: string | null
  location: string | null
  resume: ResumeInfo | null
}

const EXISTING: ResumeInfo = {
  filename: 'Old CV.pdf',
  size_bytes: 1536,
  uploaded_at: '2026-11-05T12:00:00Z',
}
const FIVE_MB = 5 * 1024 * 1024

/** A candidate and their profile, answering the way the real server does. */
function startServer(resume: ResumeInfo | null = null) {
  const state = {
    profile: {
      full_name: candidateUser.full_name,
      email: candidateUser.email,
      phone: null,
      location: null,
      resume,
    } as ProfileData,
    failNext: {} as Record<string, Reply>,
  }

  const backend = stubBackend((call) => {
    const url = new URL(call.path, 'http://app.test')
    const key = `${call.method} ${url.pathname}`
    const planned = state.failNext[key]
    if (planned) {
      delete state.failNext[key]
      return planned
    }
    if (key === 'GET /api/auth/me') return { status: 200, body: sessionFor(candidateUser) }
    if (key === 'GET /health') return { status: 200, body: { status: 'ok' } }
    if (key === 'GET /api/profile') return { status: 200, body: state.profile }
    if (key === 'PUT /api/profile/resume') {
      const file = call.rawBody as File
      state.profile.resume = {
        filename: url.searchParams.get('filename') ?? '',
        size_bytes: file.size,
        uploaded_at: '2026-11-10T12:00:00Z',
      }
      return { status: 200, body: state.profile.resume }
    }
    throw new Error(`Unplanned request in test: ${key}`)
  })

  return { state, calls: backend.calls }
}

function pdf(name = 'cv.pdf', size = 20): File {
  return new File([new Uint8Array(size)], name, { type: 'application/pdf' })
}

function chooseFile(file: File) {
  fireEvent.change(screen.getByLabelText(/choose a pdf or word file/i), {
    target: { files: [file] },
  })
}

function uploads<Call extends { method: string }>(calls: Call[]): Call[] {
  return calls.filter((c) => c.method === 'PUT')
}

function resetBrowserState() {
  setCsrfToken(null)
  setUnauthorizedHandler(null)
}

describe('ProfilePage: the resume section', () => {
  beforeEach(resetBrowserState)
  afterEach(() => vi.unstubAllGlobals())

  it('asks for a resume when there is none, and cannot upload before a file is chosen', async () => {
    startServer()
    renderApp('/profile')

    expect(await screen.findByText(/no resume yet/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /upload resume/i })).toBeDisabled()
    chooseFile(pdf())
    expect(screen.getByRole('button', { name: /upload resume/i })).toBeEnabled()
  })

  it('only offers PDF and Word files in the file picker', async () => {
    startServer()
    renderApp('/profile')

    const input = await screen.findByLabelText(/choose a pdf or word file/i)
    expect(input).toHaveAttribute('type', 'file')
    expect(input.getAttribute('accept')).toContain('.pdf')
    expect(input.getAttribute('accept')).toContain('.docx')
  })

  it('shows the current resume: name, size, date and a way to download it', async () => {
    startServer(EXISTING)
    renderApp('/profile')

    expect(await screen.findByText('Old CV.pdf')).toBeInTheDocument()
    expect(screen.getByText(/1\.5 KB/)).toBeInTheDocument()
    expect(screen.getByText(new RegExp(formatDate(EXISTING.uploaded_at)))).toBeInTheDocument()
    const link = screen.getByRole('link', { name: /download/i })
    expect(link).toHaveAttribute('href', '/api/profile/resume')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link.getAttribute('rel')).toContain('noopener')
    expect(screen.queryByText(/no resume yet/i)).not.toBeInTheDocument()
  })

  it('shows a file name as text, never as HTML', async () => {
    startServer({ ...EXISTING, filename: '<img src=x onerror=alert(1)>.pdf' })
    renderApp('/profile')

    expect(await screen.findByText('<img src=x onerror=alert(1)>.pdf')).toBeInTheDocument()
    expect(document.querySelector('main img')).toBeNull()
  })

  it('says "Replace" when there already is a resume', async () => {
    startServer(EXISTING)
    renderApp('/profile')
    await screen.findByText('Old CV.pdf')

    expect(screen.getByRole('button', { name: /replace resume/i })).toBeDisabled()
    expect(screen.queryByRole('button', { name: /^upload resume$/i })).not.toBeInTheDocument()
  })
})

describe('ProfilePage: uploading', () => {
  beforeEach(resetBrowserState)
  afterEach(() => vi.unstubAllGlobals())

  it('sends the chosen file itself, with the CSRF token, and shows the new resume', async () => {
    const { calls } = startServer()
    renderApp('/profile')
    await screen.findByText(/no resume yet/i)
    const file = pdf('My CV.pdf', 2048)

    chooseFile(file)
    fireEvent.click(screen.getByRole('button', { name: /upload resume/i }))

    expect(await screen.findByText(/resume uploaded/i)).toBeInTheDocument()
    const put = uploads(calls)[0]
    expect(put.path).toBe('/api/profile/resume?filename=My%20CV.pdf')
    expect(put.rawBody).toBe(file)
    expect(put.headers['X-CSRF-Token']).toBe('csrf-token-1')
    expect(await screen.findByText('My CV.pdf')).toBeInTheDocument()
    expect(screen.getByText(/2\.0 KB/)).toBeInTheDocument()
    expect(screen.queryByText(/no resume yet/i)).not.toBeInTheDocument()
  })

  it('encodes a file name that has special characters', async () => {
    const { calls } = startServer()
    renderApp('/profile')
    await screen.findByText(/no resume yet/i)

    chooseFile(pdf('résumé & notes #1.pdf'))
    fireEvent.click(screen.getByRole('button', { name: /upload resume/i }))

    await screen.findByText(/resume uploaded/i)
    expect(uploads(calls)[0].path).toBe(
      '/api/profile/resume?filename=r%C3%A9sum%C3%A9%20%26%20notes%20%231.pdf',
    )
  })

  it('clears the chosen file after a successful upload', async () => {
    startServer()
    renderApp('/profile')
    await screen.findByText(/no resume yet/i)
    chooseFile(pdf())

    fireEvent.click(screen.getByRole('button', { name: /upload resume/i }))

    await screen.findByText(/resume uploaded/i)
    expect(screen.getByRole('button', { name: /replace resume/i })).toBeDisabled()
  })

  it('does not upload twice when submitted twice before the screen updates', async () => {
    const { calls } = startServer()
    renderApp('/profile')
    await screen.findByText(/no resume yet/i)
    chooseFile(pdf())

    const form = screen.getByLabelText(/choose a pdf or word file/i).closest('form')!
    act(() => {
      fireEvent.submit(form)
      fireEvent.submit(form)
    })

    await screen.findByText(/resume uploaded/i)
    expect(uploads(calls)).toHaveLength(1)
  })

  it('accepts a file of exactly 5 MB', async () => {
    const { calls } = startServer()
    renderApp('/profile')
    await screen.findByText(/no resume yet/i)

    chooseFile(pdf('big.pdf', FIVE_MB))
    fireEvent.click(screen.getByRole('button', { name: /upload resume/i }))

    await screen.findByText(/resume uploaded/i)
    expect(uploads(calls)).toHaveLength(1)
  })

  it('refuses a file over 5 MB before sending it anywhere', async () => {
    const { calls } = startServer()
    renderApp('/profile')
    await screen.findByText(/no resume yet/i)

    chooseFile(pdf('huge.pdf', FIVE_MB + 1))

    expect(await screen.findByRole('alert')).toHaveTextContent(/larger than 5 MB/i)
    expect(screen.getByRole('button', { name: /upload resume/i })).toBeDisabled()
    expect(uploads(calls)).toHaveLength(0)
  })

  it('forgets a too-large message when a good file is chosen next', async () => {
    startServer()
    renderApp('/profile')
    await screen.findByText(/no resume yet/i)
    chooseFile(pdf('huge.pdf', FIVE_MB + 1))
    await screen.findByRole('alert')

    chooseFile(pdf('fine.pdf'))

    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
    expect(screen.getByRole('button', { name: /upload resume/i })).toBeEnabled()
  })
})

describe('ProfilePage: when an upload is refused', () => {
  beforeEach(resetBrowserState)
  afterEach(() => vi.unstubAllGlobals())

  it.each([
    [422, 'resume_type_unsupported', 'Upload a PDF or a Word (.docx) file.'],
    [422, 'resume_empty', 'The file is empty.'],
    [413, 'resume_too_large', 'The file is too large. The limit is 5 MB.'],
    [429, 'upload_limit', 'You can upload at most 5 files per hour. Please try again later.'],
  ])('shows the server message for %i %s', async (status, code, detail) => {
    const server = startServer(EXISTING)
    server.state.failNext['PUT /api/profile/resume'] = { status, body: { detail, code } }
    renderApp('/profile')
    await screen.findByText('Old CV.pdf')
    chooseFile(pdf())

    fireEvent.click(screen.getByRole('button', { name: /replace resume/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(detail)
    // The resume that was there stays, and the same file can be tried again.
    expect(screen.getByText('Old CV.pdf')).toBeInTheDocument()
    expect(screen.queryByText(/resume uploaded/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /replace resume/i })).toBeEnabled()
  })

  it('explains that storage is unavailable, in its own words', async () => {
    const server = startServer()
    server.state.failNext['PUT /api/profile/resume'] = {
      status: 503,
      body: {
        detail: 'File storage is not available. Please try again later.',
        code: 'storage_unavailable',
      },
    }
    renderApp('/profile')
    await screen.findByText(/no resume yet/i)
    chooseFile(pdf())

    fireEvent.click(screen.getByRole('button', { name: /upload resume/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      /resume storage is not available right now/i,
    )
  })

  it('shows a plain message for any other failure', async () => {
    const server = startServer()
    server.state.failNext['PUT /api/profile/resume'] = { status: 500 }
    renderApp('/profile')
    await screen.findByText(/no resume yet/i)
    chooseFile(pdf())

    fireEvent.click(screen.getByRole('button', { name: /upload resume/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/something went wrong/i)
  })

  it('clears an old error when the next upload works', async () => {
    const server = startServer()
    server.state.failNext['PUT /api/profile/resume'] = {
      status: 422,
      body: { detail: 'Upload a PDF or a Word (.docx) file.', code: 'resume_type_unsupported' },
    }
    renderApp('/profile')
    await screen.findByText(/no resume yet/i)
    chooseFile(pdf())
    fireEvent.click(screen.getByRole('button', { name: /upload resume/i }))
    await screen.findByRole('alert')

    fireEvent.click(screen.getByRole('button', { name: /upload resume/i }))

    expect(await screen.findByText(/resume uploaded/i)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
