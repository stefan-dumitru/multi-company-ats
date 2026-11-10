import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import { formatDate } from '@/lib/format'
import type { Reply } from '@/test-utils'
import { adminUser, recruiterUser, sessionFor, stubBackend } from '@/test-utils'
import { fillIn, press, renderApp } from '@/test-render'

interface Person {
  id: string
  full_name: string
  email: string
  is_active: boolean
}

interface JobState {
  id: string
  title: string
  location: string
  description: string
  status: 'draft' | 'open' | 'closed'
  department: { id: string; name: string; is_archived: boolean }
  created_at: string
  opened_at: string | null
  closed_at: string | null
  version: number
  needs_reassignment: boolean
  recruiters: Person[]
}

const ENGINEERING = { id: 'dep-eng', name: 'Engineering', is_archived: false }
const SALES = { id: 'dep-sales', name: 'Sales', is_archived: false }
const RAE: Person = {
  id: 'u-rec',
  full_name: 'Rae Recruiter',
  email: 'rae@acme.test',
  is_active: true,
}
const REN: Person = {
  id: 'u-ren',
  full_name: 'Ren Recruiter',
  email: 'ren@acme.test',
  is_active: true,
}
const GONE: Person = {
  id: 'u-gone',
  full_name: 'Gone Away',
  email: 'gone@acme.test',
  is_active: false,
}

const VERSION_CONFLICT = {
  detail: 'This job was changed by someone else. Reload it and try again.',
  code: 'version_conflict',
}

function makeJob(extra: Partial<JobState> = {}): JobState {
  return {
    id: 'j1',
    title: 'Backend Engineer',
    location: 'Oslo',
    description: 'Build and run our services.',
    status: 'draft',
    department: ENGINEERING,
    created_at: '2026-11-01T12:00:00Z',
    opened_at: null,
    closed_at: null,
    version: 1,
    needs_reassignment: false,
    recruiters: [RAE],
    ...extra,
  }
}

/** One job and a little company around it, answering the way the real server does. */
function startServer(
  options: {
    job?: JobState | null
    user?: typeof adminUser
    departments?: { id: string; name: string; is_archived: boolean }[]
    recruiterPool?: Person[]
  } = {},
) {
  const state = {
    job: options.job === undefined ? makeJob() : options.job,
    departments: options.departments ?? [ENGINEERING, SALES],
    pool: options.recruiterPool ?? [RAE, REN, GONE],
    failNext: {} as Record<string, Reply>,
    // Another person changes the job behind the page's back: bump the version before the next call.
    changeBehindBack: false,
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
    if (key === 'GET /api/auth/me') return { status: 200, body: sessionFor(user) }
    if (key === 'GET /health') return { status: 200, body: { status: 'ok' } }
    if (key === 'GET /api/departments') {
      const items = state.departments
      return { status: 200, body: { items, total: items.length, page: 1, page_size: 100 } }
    }
    if (key === 'GET /api/recruiters') {
      const items = state.pool.filter((p) => p.is_active)
      return { status: 200, body: { items, total: items.length, page: 1, page_size: 100 } }
    }
    if (key === 'GET /api/jobs') {
      return { status: 200, body: { items: [], total: 0, page: 1, page_size: 20 } }
    }

    const match = url.pathname.match(/^\/api\/jobs\/([^/]+)(\/[a-z]+)?(?:\/([^/]+))?$/)
    if (!match) throw new Error(`Unplanned request in test: ${key}`)
    const job = state.job
    if (job === null || job.id !== match[1]) return { status: 404, body: { detail: 'Not found.' } }
    const [, , action, personId] = match

    if (state.changeBehindBack && call.method !== 'GET') {
      state.changeBehindBack = false
      job.version += 1
      job.title = 'Changed by a colleague'
    }
    const body = call.body as Record<string, unknown> | undefined

    if (call.method === 'GET') return { status: 200, body: job }
    if (call.method === 'DELETE' && !action) {
      state.job = null
      return { status: 204 }
    }
    if (call.method === 'PATCH') {
      if (body?.version !== job.version) return { status: 409, body: VERSION_CONFLICT }
      Object.assign(job, {
        title: body.title,
        location: body.location,
        description: body.description,
        department: state.departments.find((d) => d.id === body.department_id) ?? job.department,
      })
      job.version += 1
      return { status: 200, body: job }
    }
    if (action === '/publish') {
      if (job.status === 'open') return { status: 200, body: job }
      if (body?.version !== job.version) return { status: 409, body: VERSION_CONFLICT }
      if (!job.recruiters.some((r) => r.is_active)) {
        return {
          status: 409,
          body: {
            detail: 'Assign at least one active recruiter before publishing.',
            code: 'no_recruiter',
          },
        }
      }
      job.status = 'open'
      job.opened_at = '2026-11-05T12:00:00Z'
      job.version += 1
      return { status: 200, body: job }
    }
    if (action === '/close') {
      if (body?.version !== job.version) return { status: 409, body: VERSION_CONFLICT }
      job.status = 'closed'
      job.closed_at = '2026-11-09T12:00:00Z'
      job.version += 1
      return { status: 200, body: job }
    }
    if (action === '/recruiters' && call.method === 'POST') {
      const person = state.pool.find((p) => p.id === (body as { user_id: string }).user_id)!
      job.recruiters.push(person)
      return { status: 200, body: job }
    }
    if (action === '/recruiters' && call.method === 'DELETE') {
      const active = job.recruiters.filter((r) => r.is_active)
      const removing = job.recruiters.find((r) => r.id === personId)
      if (job.status === 'open' && removing?.is_active && active.length === 1) {
        return {
          status: 409,
          body: {
            detail: 'An open job must keep at least one active recruiter.',
            code: 'last_recruiter',
          },
        }
      }
      job.recruiters = job.recruiters.filter((r) => r.id !== personId)
      return { status: 204 }
    }
    throw new Error(`Unplanned request in test: ${key}`)
  })

  return { state, calls: backend.calls }
}

function resetBrowserState() {
  setCsrfToken(null)
  setUnauthorizedHandler(null)
}

describe('JobDetailPage: reading', () => {
  beforeEach(resetBrowserState)
  afterEach(() => vi.unstubAllGlobals())

  it('shows the job, its status and who works on it', async () => {
    startServer({ job: makeJob({ recruiters: [RAE, GONE] }) })
    renderApp('/manage/jobs/j1')

    expect(await screen.findByRole('heading', { name: 'Backend Engineer' })).toBeInTheDocument()
    expect(screen.getByText('Draft')).toBeInTheDocument()
    const people = within(screen.getByRole('region', { name: /recruiters/i }))
    expect(people.getByText('Rae Recruiter')).toBeInTheDocument()
    expect(people.getByText('rae@acme.test')).toBeInTheDocument()
    expect(people.getByText('Deactivated')).toBeInTheDocument()
  })

  it('links back to the list', async () => {
    startServer()
    renderApp('/manage/jobs/j1')

    const link = await screen.findByRole('link', { name: /back to jobs/i })
    expect(link).toHaveAttribute('href', '/manage/jobs')
  })

  it('shows "not found" for a job that does not exist or is not the user\'s to see', async () => {
    startServer({ job: null })
    renderApp('/manage/jobs/j1')

    expect(await screen.findByText(/page not found/i)).toBeInTheDocument()
  })

  it('shows an error with a way to try again when the job cannot be loaded', async () => {
    const server = startServer()
    server.state.failNext['GET /api/jobs/j1'] = { status: 500 }
    renderApp('/manage/jobs/j1')

    expect(await screen.findByRole('alert')).toHaveTextContent(/something went wrong/i)
    press(/try again/i)

    expect(await screen.findByRole('heading', { name: 'Backend Engineer' })).toBeInTheDocument()
  })

  it('shows the title and description as text, never as HTML', async () => {
    startServer({
      job: makeJob({
        title: '<img src=x onerror=alert(1)>',
        status: 'closed',
        description: '<b>bold</b>',
      }),
    })
    renderApp('/manage/jobs/j1')

    expect(await screen.findByText('<img src=x onerror=alert(1)>')).toBeInTheDocument()
    expect(screen.getByText('<b>bold</b>')).toBeInTheDocument()
    expect(document.querySelector('main img, main b')).toBeNull()
  })

  it('warns when the job has no active recruiter', async () => {
    startServer({ job: makeJob({ recruiters: [], needs_reassignment: true }) })
    renderApp('/manage/jobs/j1')

    expect(await screen.findByText(/no active recruiter/i)).toBeInTheDocument()
  })

  it('is not available to an interviewer', async () => {
    const interviewer = { ...recruiterUser, id: 'u-int', role: 'interviewer' as const }
    const { calls } = startServer({ user: interviewer })
    renderApp('/manage/jobs/j1')

    expect(await screen.findByText(/page not found/i)).toBeInTheDocument()
    expect(calls.some((c) => c.path.startsWith('/api/jobs/'))).toBe(false)
  })
})

describe('JobDetailPage: publishing, closing and deleting', () => {
  beforeEach(resetBrowserState)
  afterEach(() => vi.unstubAllGlobals())

  it('publishes a draft, quoting the version it was looking at', async () => {
    const { calls } = startServer()
    renderApp('/manage/jobs/j1')
    await screen.findByRole('heading', { name: 'Backend Engineer' })

    press(/^publish$/i)

    expect(await screen.findByText('Open')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^publish$/i })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /close job/i })).toBeInTheDocument()
    const post = calls.find((c) => c.path === '/api/jobs/j1/publish')!
    expect(post.method).toBe('POST')
    expect(post.body).toEqual({ version: 1 })
    expect(post.headers['X-CSRF-Token']).toBe('csrf-token-1')
  })

  it('shows the server message when a job cannot be published, and stays a draft', async () => {
    startServer({ job: makeJob({ recruiters: [GONE], needs_reassignment: true }) })
    renderApp('/manage/jobs/j1')
    await screen.findByRole('heading', { name: 'Backend Engineer' })

    press(/^publish$/i)

    expect(await screen.findByRole('alert')).toHaveTextContent(
      /assign at least one active recruiter/i,
    )
    expect(screen.getByText('Draft')).toBeInTheDocument()
  })

  it('asks before closing, and does nothing on cancel', async () => {
    const { calls } = startServer({
      job: makeJob({ status: 'open', opened_at: '2026-11-05T12:00:00Z' }),
    })
    renderApp('/manage/jobs/j1')
    await screen.findByRole('heading', { name: 'Backend Engineer' })

    press(/close job/i)
    const dialog = within(await screen.findByRole('alertdialog'))
    expect(dialog.getByText(/close this job\?/i)).toBeInTheDocument()
    fireEvent.click(dialog.getByRole('button', { name: 'Cancel' }))

    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(calls.some((c) => c.path.endsWith('/close'))).toBe(false)
  })

  it('closes an open job after confirmation, and then it can no longer be changed', async () => {
    const { calls } = startServer({
      job: makeJob({ status: 'open', opened_at: '2026-11-05T12:00:00Z' }),
    })
    renderApp('/manage/jobs/j1')
    await screen.findByRole('heading', { name: 'Backend Engineer' })

    press(/close job/i)
    fireEvent.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Close job' }),
    )

    expect(await screen.findByText('Closed')).toBeInTheDocument()
    expect(calls.find((c) => c.path.endsWith('/close'))?.body).toEqual({ version: 1 })
    expect(screen.getByText(/this job is closed/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/^title$/i)).not.toBeInTheDocument() // no edit form
    expect(
      screen.queryByRole('button', { name: /publish|close job|delete draft/i }),
    ).not.toBeInTheDocument()
  })

  it('deletes a draft after confirmation and returns to the list', async () => {
    const { calls } = startServer()
    renderApp('/manage/jobs/j1')
    await screen.findByRole('heading', { name: 'Backend Engineer' })

    press(/delete draft/i)
    fireEvent.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Delete draft' }),
    )

    expect(await screen.findByRole('heading', { name: 'Jobs' })).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'DELETE')?.path).toBe('/api/jobs/j1')
  })

  it('cannot delete a job that is open', async () => {
    startServer({ job: makeJob({ status: 'open', opened_at: '2026-11-05T12:00:00Z' }) })
    renderApp('/manage/jobs/j1')
    await screen.findByRole('heading', { name: 'Backend Engineer' })

    expect(screen.queryByRole('button', { name: /delete draft/i })).not.toBeInTheDocument()
  })

  it('shows when the job opened', async () => {
    startServer({ job: makeJob({ status: 'open', opened_at: '2026-11-05T12:00:00Z' }) })
    renderApp('/manage/jobs/j1')

    expect(await screen.findByText(formatDate('2026-11-05T12:00:00Z'))).toBeInTheDocument()
  })

  it('reloads and says so when someone else changed the job before a status change', async () => {
    const server = startServer()
    renderApp('/manage/jobs/j1')
    await screen.findByRole('heading', { name: 'Backend Engineer' })
    server.state.changeBehindBack = true

    press(/^publish$/i)

    expect(await screen.findByRole('alert')).toHaveTextContent(/changed by someone else/i)
    // The page now shows what is really there, so the next click quotes the right version.
    expect(
      await screen.findByRole('heading', { name: 'Changed by a colleague' }),
    ).toBeInTheDocument()
    expect(screen.getByText('Draft')).toBeInTheDocument()
  })
})

describe('JobDetailPage: editing', () => {
  beforeEach(resetBrowserState)
  afterEach(() => vi.unstubAllGlobals())

  it('shows the current values in the form, with the departments a job may use', async () => {
    startServer()
    renderApp('/manage/jobs/j1')

    expect(await screen.findByLabelText(/^title$/i)).toHaveValue('Backend Engineer')
    expect(screen.getByLabelText(/^location$/i)).toHaveValue('Oslo')
    expect(screen.getByLabelText(/^description$/i)).toHaveValue('Build and run our services.')
    await waitFor(() => expect(screen.getByRole('option', { name: 'Sales' })).toBeInTheDocument())
    expect(screen.getByLabelText(/^department$/i)).toHaveValue('dep-eng')
  })

  it('keeps a department that was archived after the job chose it', async () => {
    const archived = { id: 'dep-old', name: 'Old team', is_archived: true }
    startServer({ job: makeJob({ department: archived }) })
    renderApp('/manage/jobs/j1')

    const select = await screen.findByLabelText(/^department$/i)
    await waitFor(() => expect(screen.getByRole('option', { name: 'Sales' })).toBeInTheDocument())
    expect(select).toHaveValue('dep-old')
    expect(screen.getByRole('option', { name: /old team/i })).toBeInTheDocument()
  })

  it('saves changes with the version, and the next change uses the new version', async () => {
    const { calls } = startServer()
    renderApp('/manage/jobs/j1')
    await screen.findByLabelText(/^title$/i)
    await waitFor(() => expect(screen.getByRole('option', { name: 'Sales' })).toBeInTheDocument())

    fillIn(/^title$/i, 'Staff Engineer')
    fireEvent.change(screen.getByLabelText(/^department$/i), { target: { value: 'dep-sales' } })
    press(/save changes/i)

    expect(await screen.findByText(/changes saved/i)).toBeInTheDocument()
    const patch = calls.find((c) => c.method === 'PATCH')!
    expect(patch.path).toBe('/api/jobs/j1')
    expect(patch.body).toEqual({
      version: 1,
      title: 'Staff Engineer',
      location: 'Oslo',
      description: 'Build and run our services.',
      department_id: 'dep-sales',
    })
    expect(await screen.findByRole('heading', { name: 'Staff Engineer' })).toBeInTheDocument()

    press(/^publish$/i)
    await screen.findByText('Open')
    expect(calls.find((c) => c.path.endsWith('/publish'))?.body).toEqual({ version: 2 })
  })

  it('does not save twice when submitted twice before the screen updates', async () => {
    const { calls } = startServer()
    renderApp('/manage/jobs/j1')
    await screen.findByLabelText(/^title$/i)
    await waitFor(() => expect(screen.getByRole('option', { name: 'Sales' })).toBeInTheDocument())
    fillIn(/^title$/i, 'Staff Engineer')

    const form = screen.getByLabelText(/^title$/i).closest('form')!
    act(() => {
      fireEvent.submit(form)
      fireEvent.submit(form)
    })

    await screen.findByText(/changes saved/i)
    expect(calls.filter((c) => c.method === 'PATCH')).toHaveLength(1)
  })

  it('on a version conflict keeps what was typed and offers the latest version', async () => {
    const server = startServer()
    renderApp('/manage/jobs/j1')
    await screen.findByLabelText(/^title$/i)
    await waitFor(() => expect(screen.getByRole('option', { name: 'Sales' })).toBeInTheDocument())
    server.state.changeBehindBack = true
    fillIn(/^title$/i, 'My careful edit')

    press(/save changes/i)

    expect(await screen.findByRole('alert')).toHaveTextContent(/changed by someone else/i)
    expect(screen.getByLabelText(/^title$/i)).toHaveValue('My careful edit')

    press(/load the latest version/i)

    await waitFor(() =>
      expect(screen.getByLabelText(/^title$/i)).toHaveValue('Changed by a colleague'),
    )
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows the server message and keeps the values when a change is refused', async () => {
    const server = startServer()
    server.state.failNext['PATCH /api/jobs/j1'] = {
      status: 422,
      body: { detail: 'That department is archived. Choose another.', code: 'department_archived' },
    }
    renderApp('/manage/jobs/j1')
    await screen.findByLabelText(/^title$/i)
    fillIn(/^title$/i, 'Changed')

    press(/save changes/i)

    expect(await screen.findByRole('alert')).toHaveTextContent(/department is archived/i)
    expect(screen.getByLabelText(/^title$/i)).toHaveValue('Changed')
    expect(screen.queryByText(/changes saved/i)).not.toBeInTheDocument()
  })
})

describe('JobDetailPage: recruiters', () => {
  beforeEach(resetBrowserState)
  afterEach(() => vi.unstubAllGlobals())

  it('offers only active recruiters who are not on the job yet', async () => {
    startServer({ job: makeJob({ recruiters: [RAE] }) })
    renderApp('/manage/jobs/j1')

    const picker = await screen.findByLabelText(/add a recruiter/i)
    await waitFor(() => expect(within(picker).getAllByRole('option').length).toBeGreaterThan(1))
    expect(
      within(picker)
        .getAllByRole('option')
        .map((o) => o.textContent),
    ).toEqual(['Choose a recruiter', 'Ren Recruiter'])
  })

  it('adds a recruiter', async () => {
    const { calls } = startServer({ job: makeJob({ recruiters: [RAE] }) })
    renderApp('/manage/jobs/j1')
    const picker = await screen.findByLabelText(/add a recruiter/i)
    await waitFor(() => expect(within(picker).getAllByRole('option').length).toBe(2))

    fireEvent.change(picker, { target: { value: 'u-ren' } })
    press(/add recruiter/i)

    const people = within(screen.getByRole('region', { name: /recruiters/i }))
    // The email only appears in the list of people on the job, not in the picker's options.
    expect(await people.findByText('ren@acme.test')).toBeInTheDocument()
    const post = calls.find((c) => c.path === '/api/jobs/j1/recruiters')!
    expect(post.body).toEqual({ user_id: 'u-ren' })
    expect(post.headers['X-CSRF-Token']).toBe('csrf-token-1')
  })

  it('says so when everyone is already on the job', async () => {
    startServer({ job: makeJob({ recruiters: [RAE, REN] }) })
    renderApp('/manage/jobs/j1')

    expect(await screen.findByText(/every recruiter is already on this job/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/add a recruiter/i)).not.toBeInTheDocument()
  })

  it('removes a recruiter', async () => {
    const { calls } = startServer({ job: makeJob({ recruiters: [RAE, REN] }) })
    renderApp('/manage/jobs/j1')
    await screen.findByRole('heading', { name: 'Backend Engineer' })

    press(/remove ren recruiter/i)

    await waitFor(() => expect(screen.queryByText('ren@acme.test')).not.toBeInTheDocument())
    expect(calls.find((c) => c.method === 'DELETE')?.path).toBe('/api/jobs/j1/recruiters/u-ren')
  })

  it('shows the server message and keeps the recruiter when the last one is refused', async () => {
    startServer({
      job: makeJob({ status: 'open', opened_at: '2026-11-05T12:00:00Z', recruiters: [RAE] }),
    })
    renderApp('/manage/jobs/j1')
    await screen.findByRole('heading', { name: 'Backend Engineer' })

    press(/remove rae recruiter/i)

    expect(await screen.findByRole('alert')).toHaveTextContent(
      /keep at least one active recruiter/i,
    )
    expect(screen.getByText('rae@acme.test')).toBeInTheDocument()
  })

  it('asks before a recruiter removes themselves, then returns to the list', async () => {
    const { calls } = startServer({ user: recruiterUser, job: makeJob({ recruiters: [RAE, REN] }) })
    renderApp('/manage/jobs/j1')
    await screen.findByRole('heading', { name: 'Backend Engineer' })

    press(/remove rae recruiter/i)
    const dialog = within(await screen.findByRole('alertdialog'))
    expect(dialog.getByText(/remove yourself from this job\?/i)).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
    fireEvent.click(dialog.getByRole('button', { name: 'Remove me' }))

    expect(await screen.findByRole('heading', { name: 'My jobs' })).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'DELETE')?.path).toBe('/api/jobs/j1/recruiters/u-rec')
  })

  it('lets a recruiter who is on the job see and use the whole page', async () => {
    startServer({ user: recruiterUser })
    renderApp('/manage/jobs/j1')

    expect(await screen.findByRole('heading', { name: 'Backend Engineer' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^publish$/i })).toBeInTheDocument()
  })
})
