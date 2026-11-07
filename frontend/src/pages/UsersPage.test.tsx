import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import type { Reply } from '@/test-utils'
import { adminUser, sessionFor, stubBackend } from '@/test-utils'
import { fillIn, press, renderApp } from '@/test-render'

interface Member {
  id: string
  email: string
  full_name: string
  role: string
  is_active: boolean
  deactivated_at: string | null
  last_login_at: string | null
  created_at: string
}

interface Invite {
  id: string
  email: string
  role: string
  status: 'pending' | 'accepted' | 'expired' | 'revoked'
  created_at: string
  expires_at: string
}

function member(id: string, name: string, role: string, extra: Partial<Member> = {}): Member {
  return {
    id,
    email: `${name.split(' ')[0].toLowerCase()}@acme.test`,
    full_name: name,
    role,
    is_active: true,
    deactivated_at: null,
    last_login_at: null,
    created_at: '2026-01-05T09:00:00Z',
    ...extra,
  }
}

function invite(id: string, email: string, status: Invite['status'], role = 'recruiter'): Invite {
  return {
    id,
    email,
    role,
    status,
    created_at: '2026-11-01T09:00:00Z',
    expires_at: '2026-11-08T09:00:00Z',
  }
}

/** A little in-memory company, answering the way the real server does. */
function startServer(options: { users?: Member[]; invitations?: Invite[] } = {}) {
  const state = {
    users: options.users ?? [
      member('u-admin', 'Ada Admin', 'company_admin'),
      member('u-rec', 'Rae Recruiter', 'recruiter'),
      member('u-boss', 'Bo Boss', 'company_admin'),
    ],
    invitations: options.invitations ?? [],
    // Make the next call to "METHOD /path" fail with this answer.
    failNext: {} as Record<string, Reply>,
    nextInvite: 1,
  }

  const backend = stubBackend((call) => {
    const key = `${call.method} ${call.path}`
    const planned = state.failNext[key]
    if (planned) {
      delete state.failNext[key]
      return planned
    }
    if (key === 'GET /api/auth/me') return { status: 200, body: sessionFor(adminUser) }
    if (key === 'GET /health') return { status: 200, body: { status: 'ok' } }
    if (key === 'GET /api/users') return { status: 200, body: state.users }
    if (key === 'GET /api/invitations') return { status: 200, body: state.invitations }

    const roleChange = call.path.match(/^\/api\/users\/([^/]+)\/role$/)
    if (call.method === 'PATCH' && roleChange) {
      const person = state.users.find((u) => u.id === roleChange[1])!
      person.role = (call.body as { role: string }).role
      return { status: 200, body: person }
    }
    const toggle = call.path.match(/^\/api\/users\/([^/]+)\/(deactivate|reactivate)$/)
    if (call.method === 'POST' && toggle) {
      const person = state.users.find((u) => u.id === toggle[1])!
      person.is_active = toggle[2] === 'reactivate'
      person.deactivated_at = person.is_active ? null : '2026-11-05T09:00:00Z'
      return { status: 200, body: person }
    }
    if (key === 'POST /api/invitations') {
      const { email, role } = call.body as { email: string; role: string }
      const created = invite(`i-${state.nextInvite++}`, email, 'pending', role)
      state.invitations = [created, ...state.invitations]
      return {
        status: 201,
        body: {
          invitation: created,
          token: 'join-link-for-tests',
          accept_path: '/accept-invitation?token=join-link-for-tests',
        },
      }
    }
    throw new Error(`Unplanned request in test: ${key}`)
  })

  return { state, calls: backend.calls }
}

/** The table row for a person, found by their name. */
function rowOf(name: string) {
  return within(screen.getByRole('row', { name: new RegExp(name) }))
}

describe('UsersPage: the member list', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('lists everyone in the company with a readable role and status', async () => {
    startServer({
      users: [
        member('u-admin', 'Ada Admin', 'company_admin'),
        member('u-rec', 'Rae Recruiter', 'recruiter'),
        member('u-int', 'Ivy Interviewer', 'interviewer', { is_active: false }),
      ],
    })
    renderApp('/users')

    expect(await screen.findByRole('heading', { name: 'Users' })).toBeInTheDocument()
    const table = within(await screen.findByRole('table', { name: /company members/i }))
    expect(table.getByText('rae@acme.test')).toBeInTheDocument()
    expect(rowOf('Rae Recruiter').getByRole('combobox')).toHaveValue('recruiter')
    expect(rowOf('Ivy Interviewer').getByText('Deactivated')).toBeInTheDocument()
    expect(rowOf('Rae Recruiter').getByText('Active')).toBeInTheDocument()
  })

  it('marks the current user, and does not let them demote or deactivate themselves here', async () => {
    startServer()
    renderApp('/users')
    await screen.findByRole('table', { name: /company members/i })

    const mine = rowOf('Ada Admin')

    expect(mine.getByText('(you)')).toBeInTheDocument()
    expect(mine.getByRole('combobox')).toBeDisabled()
    expect(mine.queryByRole('button', { name: /deactivate/i })).not.toBeInTheDocument()
  })

  it('shows names as text, never as HTML', async () => {
    startServer({
      users: [
        member('u-admin', 'Ada Admin', 'company_admin'),
        member('u-x', '<img src=x onerror=alert(1)>', 'recruiter'),
      ],
    })
    renderApp('/users')

    expect(await screen.findByText('<img src=x onerror=alert(1)>')).toBeInTheDocument()
    expect(document.querySelector('main img')).toBeNull()
  })

  it('says so when the list cannot be loaded, and lets the admin try again', async () => {
    const server = startServer()
    server.state.failNext['GET /api/users'] = { status: 500 }
    renderApp('/users')

    expect(await screen.findByRole('alert')).toHaveTextContent(/something went wrong/i)
    press(/try again/i)

    expect(await screen.findByRole('table', { name: /company members/i })).toBeInTheDocument()
  })
})

describe('UsersPage: changing roles', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('changes a role, with the CSRF token, and shows the result', async () => {
    const { calls } = startServer()
    renderApp('/users')
    await screen.findByRole('table', { name: /company members/i })

    fireEvent.change(rowOf('Rae Recruiter').getByRole('combobox'), {
      target: { value: 'interviewer' },
    })

    await waitFor(() =>
      expect(rowOf('Rae Recruiter').getByRole('combobox')).toHaveValue('interviewer'),
    )
    const change = calls.find((c) => c.method === 'PATCH')
    expect(change?.path).toBe('/api/users/u-rec/role')
    expect(change?.body).toEqual({ role: 'interviewer' })
    expect(change?.headers['X-CSRF-Token']).toBe('csrf-token-1')
  })

  it('shows the server message when a role change is refused, and the old role stays', async () => {
    const server = startServer()
    server.state.failNext['PATCH /api/users/u-boss/role'] = {
      status: 409,
      body: { detail: 'A company must keep at least one active admin.' },
    }
    renderApp('/users')
    await screen.findByRole('table', { name: /company members/i })

    fireEvent.change(rowOf('Bo Boss').getByRole('combobox'), { target: { value: 'recruiter' } })

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'A company must keep at least one active admin.',
    )
    await waitFor(() => expect(rowOf('Bo Boss').getByRole('combobox')).toHaveValue('company_admin'))
  })

  it('offers only staff roles, never "candidate"', async () => {
    startServer()
    renderApp('/users')
    await screen.findByRole('table', { name: /company members/i })

    const options = within(rowOf('Rae Recruiter').getByRole('combobox'))
      .getAllByRole('option')
      .map((option) => option.textContent)

    expect(options).toEqual(['Company admin', 'Recruiter', 'Interviewer'])
  })
})

describe('UsersPage: deactivating and reactivating', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('asks before deactivating, and does nothing if the admin cancels', async () => {
    const { calls } = startServer()
    renderApp('/users')
    await screen.findByRole('table', { name: /company members/i })

    fireEvent.click(
      rowOf('Rae Recruiter').getByRole('button', { name: /deactivate rae recruiter/i }),
    )
    const dialog = await screen.findByRole('alertdialog')
    expect(dialog).toHaveTextContent(/rae recruiter/i)
    expect(dialog).toHaveTextContent(/logged out/i)
    fireEvent.click(within(dialog).getByRole('button', { name: /cancel/i }))

    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(calls.some((c) => c.path.endsWith('/deactivate'))).toBe(false)
    expect(rowOf('Rae Recruiter').getByText('Active')).toBeInTheDocument()
  })

  it('deactivates after confirmation and then offers to reactivate', async () => {
    const { calls } = startServer()
    renderApp('/users')
    await screen.findByRole('table', { name: /company members/i })

    fireEvent.click(
      rowOf('Rae Recruiter').getByRole('button', { name: /deactivate rae recruiter/i }),
    )
    const dialog = await screen.findByRole('alertdialog')
    fireEvent.click(within(dialog).getByRole('button', { name: /^deactivate$/i }))

    expect(await rowOf('Rae Recruiter').findByText('Deactivated')).toBeInTheDocument()
    const call = calls.find((c) => c.path === '/api/users/u-rec/deactivate')
    expect(call?.method).toBe('POST')
    expect(call?.headers['X-CSRF-Token']).toBe('csrf-token-1')
    expect(
      rowOf('Rae Recruiter').getByRole('button', { name: /reactivate rae recruiter/i }),
    ).toBeInTheDocument()
  })

  it('reactivates straight away, without a dialog', async () => {
    const { calls } = startServer({
      users: [
        member('u-admin', 'Ada Admin', 'company_admin'),
        member('u-rec', 'Rae Recruiter', 'recruiter', { is_active: false }),
      ],
    })
    renderApp('/users')
    await screen.findByRole('table', { name: /company members/i })

    fireEvent.click(
      rowOf('Rae Recruiter').getByRole('button', { name: /reactivate rae recruiter/i }),
    )

    expect(await rowOf('Rae Recruiter').findByText('Active')).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/api/users/u-rec/reactivate')).toBe(true)
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })

  it('explains it when the server refuses to deactivate the last admin', async () => {
    const server = startServer()
    server.state.failNext['POST /api/users/u-boss/deactivate'] = {
      status: 409,
      body: { detail: 'A company must keep at least one active admin.' },
    }
    renderApp('/users')
    await screen.findByRole('table', { name: /company members/i })

    fireEvent.click(rowOf('Bo Boss').getByRole('button', { name: /deactivate bo boss/i }))
    fireEvent.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', { name: /^deactivate$/i }),
    )

    expect(await screen.findByRole('alert')).toHaveTextContent(/at least one active admin/i)
    expect(rowOf('Bo Boss').getByText('Active')).toBeInTheDocument()
  })
})

describe('UsersPage: inviting', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  async function openPage() {
    const server = startServer()
    renderApp('/users')
    await screen.findByRole('table', { name: /company members/i })
    return server
  }

  it('creates an invitation, says it was emailed, and shows the full link once', async () => {
    const { calls } = await openPage()

    fillIn(/invite by email/i, 'newbie@acme.test')
    fireEvent.change(screen.getByLabelText(/^role$/i), { target: { value: 'interviewer' } })
    press(/create invitation/i)

    const link = await screen.findByLabelText(/invitation link/i)
    expect(link).toHaveValue(
      `${window.location.origin}/accept-invitation?token=join-link-for-tests`,
    )
    expect(screen.getByText(/we have emailed the invitation to/i)).toBeInTheDocument()
    expect(screen.getByText(/shown only once/i)).toBeInTheDocument()
    const post = calls.find((c) => c.method === 'POST' && c.path === '/api/invitations')
    expect(post?.body).toEqual({ email: 'newbie@acme.test', role: 'interviewer' })
    expect(post?.headers['X-CSRF-Token']).toBe('csrf-token-1')
  })

  it('copies the link to the clipboard', async () => {
    await openPage()
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
    fillIn(/invite by email/i, 'newbie@acme.test')
    press(/create invitation/i)
    await screen.findByLabelText(/invitation link/i)

    press(/copy link/i)

    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(
        `${window.location.origin}/accept-invitation?token=join-link-for-tests`,
      ),
    )
    expect(await screen.findByText(/copied/i)).toBeInTheDocument()
  })

  it('removes the link from the screen when dismissed', async () => {
    await openPage()
    fillIn(/invite by email/i, 'newbie@acme.test')
    press(/create invitation/i)
    await screen.findByLabelText(/invitation link/i)

    press(/done/i)

    expect(screen.queryByLabelText(/invitation link/i)).not.toBeInTheDocument()
    expect(document.body).not.toHaveTextContent('join-link-for-tests')
  })

  it('lists the new invitation as pending and empties the form', async () => {
    await openPage()

    fillIn(/invite by email/i, 'newbie@acme.test')
    press(/create invitation/i)

    const table = within(await screen.findByRole('table', { name: /invitations/i }))
    expect(await table.findByText('newbie@acme.test')).toBeInTheDocument()
    expect(table.getByText('Pending')).toBeInTheDocument()
    expect(screen.getByLabelText(/invite by email/i)).toHaveValue('')
  })

  it('shows the server message when the email already has an account', async () => {
    const server = await openPage()
    server.state.failNext['POST /api/invitations'] = {
      status: 409,
      body: { detail: 'That email already has an account.' },
    }
    fillIn(/invite by email/i, 'rae@acme.test')

    press(/create invitation/i)

    expect(await screen.findByRole('alert')).toHaveTextContent('That email already has an account.')
    expect(screen.queryByLabelText(/invitation link/i)).not.toBeInTheDocument()
  })

  it('cannot be submitted twice while the first request runs', async () => {
    await openPage()
    fillIn(/invite by email/i, 'newbie@acme.test')
    const slow = vi.fn().mockReturnValue(new Promise(() => {}))
    vi.stubGlobal('fetch', slow)

    press(/create invitation/i)

    expect(screen.getByRole('button', { name: /creating/i })).toBeDisabled()
    expect(slow).toHaveBeenCalledTimes(1)
  })

  it('offers the three staff roles when inviting', async () => {
    await openPage()

    const options = within(screen.getByLabelText(/^role$/i))
      .getAllByRole('option')
      .map((option) => option.textContent)

    expect(options).toEqual(['Recruiter', 'Interviewer', 'Company admin'])
  })
})

describe('UsersPage: the invitation list', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows each invitation with its status, and never any link or token', async () => {
    startServer({
      invitations: [
        invite('i-1', 'a@acme.test', 'pending'),
        invite('i-2', 'b@acme.test', 'accepted'),
        invite('i-3', 'c@acme.test', 'expired'),
        invite('i-4', 'd@acme.test', 'revoked'),
      ],
    })
    renderApp('/users')

    const table = within(await screen.findByRole('table', { name: /invitations/i }))
    expect(table.getByText('Pending')).toBeInTheDocument()
    expect(table.getByText('Accepted')).toBeInTheDocument()
    expect(table.getByText('Expired')).toBeInTheDocument()
    expect(table.getByText('Revoked')).toBeInTheDocument()
    expect(document.body).not.toHaveTextContent(/token/i)
  })

  it('says so when there are no invitations yet', async () => {
    startServer({ invitations: [] })
    renderApp('/users')

    expect(await screen.findByText(/no invitations yet/i)).toBeInTheDocument()
  })

  it('sends a new link for an expired invitation, replacing the old one', async () => {
    const { calls } = startServer({
      invitations: [invite('i-3', 'c@acme.test', 'expired', 'interviewer')],
    })
    renderApp('/users')
    await screen.findByRole('table', { name: /invitations/i })

    fireEvent.click(screen.getByRole('button', { name: /send a new link to c@acme.test/i }))

    expect(await screen.findByLabelText(/invitation link/i)).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST' && c.path === '/api/invitations')?.body).toEqual({
      email: 'c@acme.test',
      role: 'interviewer',
    })
  })

  it('offers no new link for an invitation that was already accepted', async () => {
    startServer({ invitations: [invite('i-2', 'b@acme.test', 'accepted')] })
    renderApp('/users')
    await screen.findByRole('table', { name: /invitations/i })

    expect(screen.queryByRole('button', { name: /send a new link/i })).not.toBeInTheDocument()
  })
})
