import { fireEvent, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import type { User } from '@/auth/types'
import { formatDate } from '@/lib/format'
import type { Reply } from '@/test-utils'
import { adminUser, recruiterUser, sessionFor, stubBackend } from '@/test-utils'
import { press, renderApp } from '@/test-render'

interface Applicant {
  id: string
  candidate_name: string
  candidate_email: string
  stage: string
  applied_at: string
}

function applicant(overrides: Partial<Applicant> = {}): Applicant {
  return {
    id: 'a1',
    candidate_name: 'Cara Candidate',
    candidate_email: 'cara@example.test',
    stage: 'applied',
    applied_at: '2026-11-10T09:00:00Z',
    ...overrides,
  }
}

function jobWith(status: 'draft' | 'open' | 'closed') {
  return {
    id: 'j1',
    title: 'Backend Engineer',
    location: 'Oslo',
    description: 'Build and run our services.',
    status,
    department: { id: 'dep-eng', name: 'Engineering', is_archived: false },
    created_at: '2026-11-01T12:00:00Z',
    opened_at: status === 'draft' ? null : '2026-11-02T12:00:00Z',
    closed_at: status === 'closed' ? '2026-11-09T12:00:00Z' : null,
    version: 1,
    needs_reassignment: false,
    recruiters: [
      { id: 'u-rec', full_name: 'Rae Recruiter', email: 'rae@acme.test', is_active: true },
    ],
  }
}

function startServer(
  options: {
    status?: 'draft' | 'open' | 'closed'
    applicants?: Applicant[]
    user?: User
  } = {},
) {
  const state = {
    applicants: options.applicants ?? [],
    failNext: {} as Record<string, Reply>,
  }
  const user = options.user ?? adminUser

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
    if (key === 'GET /api/departments' || key === 'GET /api/recruiters') {
      return { status: 200, body: { items: [], total: 0, page: 1, page_size: 100 } }
    }
    if (key === 'GET /api/jobs/j1') return { status: 200, body: jobWith(options.status ?? 'open') }
    if (key === 'GET /api/jobs/j1/applications') {
      const page = Number(url.searchParams.get('page') ?? '1')
      const size = Number(url.searchParams.get('page_size') ?? '20')
      const items = state.applicants.slice((page - 1) * size, page * size)
      return { status: 200, body: { items, total: state.applicants.length, page, page_size: size } }
    }
    throw new Error(`Unplanned request in test: ${key}`)
  })

  return { state, calls: backend.calls }
}

function row(name: string): HTMLElement {
  return screen.getByText(name).closest('li') as HTMLElement
}

async function openJob() {
  renderApp('/manage/jobs/j1')
  await screen.findByRole('heading', { name: 'Backend Engineer' })
}

describe('JobDetailPage: applicants', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })
  afterEach(() => vi.unstubAllGlobals())

  it('lists who applied, newest first as the server sends them', async () => {
    startServer({
      applicants: [
        applicant({
          id: 'a2',
          candidate_name: 'Dan Candidate',
          candidate_email: 'dan@example.test',
        }),
        applicant(),
      ],
    })
    await openJob()

    await screen.findByText('Dan Candidate')
    const section = screen.getByRole('region', { name: /applicants/i })
    const names = within(section)
      .getAllByRole('listitem')
      .map((item) => item.textContent)
    expect(names[0]).toContain('Dan Candidate')
    expect(names[1]).toContain('Cara Candidate')
    const cara = within(row('Cara Candidate'))
    expect(cara.getByText('cara@example.test')).toBeInTheDocument()
    expect(cara.getByText('Applied')).toBeInTheDocument() // the stage badge
    expect(cara.getByText(`Applied ${formatDate('2026-11-10T09:00:00Z')}`)).toBeInTheDocument()
  })

  it('links each name to that application’s own page', async () => {
    startServer({ applicants: [applicant()] })
    await openJob()

    const link = await screen.findByRole('link', { name: 'Cara Candidate' })

    expect(link).toHaveAttribute('href', '/manage/applications/a1')
  })

  it('offers each resume as a download that opens in a new tab', async () => {
    startServer({ applicants: [applicant()] })
    await openJob()
    await screen.findByText('Cara Candidate')

    const link = within(row('Cara Candidate')).getByRole('link', { name: /download resume/i })

    expect(link).toHaveAttribute('href', '/api/applications/a1/resume')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', expect.stringContaining('noreferrer'))
  })

  it('shows withdrawn and rejected applications with the words staff use', async () => {
    startServer({
      applicants: [
        applicant({ id: 'a1', candidate_name: 'Wendy', stage: 'withdrawn' }),
        applicant({ id: 'a2', candidate_name: 'Rex', stage: 'rejected' }),
      ],
    })
    await openJob()
    await screen.findByText('Wendy')

    expect(within(row('Wendy')).getByText('Withdrawn')).toBeInTheDocument()
    // Candidates read "Not selected"; staff read what happened.
    expect(within(row('Rex')).getByText('Rejected')).toBeInTheDocument()
  })

  it('says so when nobody has applied yet', async () => {
    startServer()
    await openJob()

    expect(await screen.findByText(/no one has applied yet/i)).toBeInTheDocument()
  })

  it('shows a name or email as text, never as markup', async () => {
    startServer({
      applicants: [applicant({ candidate_name: '<b>Bold</b> Bob', candidate_email: 'b@x.test' })],
    })
    await openJob()

    expect(await screen.findByText('<b>Bold</b> Bob')).toBeInTheDocument()
    expect(document.querySelector('b')).toBeNull()
  })

  it('has no applicants section, and asks for nothing, on a draft', async () => {
    const server = startServer({ status: 'draft' })
    await openJob()

    expect(screen.queryByRole('heading', { name: /applicants/i })).not.toBeInTheDocument()
    expect(server.calls.some((call) => call.path.includes('/applications'))).toBe(false)
  })

  it('still lists the applicants of a closed job', async () => {
    startServer({ status: 'closed', applicants: [applicant()] })
    await openJob()

    expect(await screen.findByText('Cara Candidate')).toBeInTheDocument()
  })

  it('shows a recruiter the section too', async () => {
    startServer({ user: recruiterUser, applicants: [applicant()] })
    await openJob()

    expect(await screen.findByText('Cara Candidate')).toBeInTheDocument()
  })

  it('pages through a long list', async () => {
    const many = Array.from({ length: 21 }, (_, index) =>
      applicant({ id: `a${index}`, candidate_name: `Person ${index}` }),
    )
    startServer({ applicants: many })
    await openJob()
    await screen.findByText('Person 0')
    expect(screen.queryByText('Person 20')).not.toBeInTheDocument()

    press('Next')

    expect(await screen.findByText('Person 20')).toBeInTheDocument()
  })

  it('keeps the rest of the page working when the applicants fail to load, and can retry', async () => {
    const server = startServer({ applicants: [applicant()] })
    server.state.failNext['GET /api/jobs/j1/applications'] = { status: 500, body: {} }
    await openJob()

    const alert = await screen.findByRole('alert')
    expect(alert).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Close job' })).toBeInTheDocument() // page intact

    fireEvent.click(screen.getByRole('button', { name: /try again/i }))

    expect(await screen.findByText('Cara Candidate')).toBeInTheDocument()
  })
})
