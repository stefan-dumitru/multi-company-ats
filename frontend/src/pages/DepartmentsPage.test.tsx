import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken, setUnauthorizedHandler } from '@/api/client'
import type { Reply } from '@/test-utils'
import { adminUser, recruiterUser, sessionFor, stubBackend } from '@/test-utils'
import { fillIn, press, renderApp } from '@/test-render'

interface Department {
  id: string
  name: string
  is_archived: boolean
}

function department(id: string, name: string, isArchived = false): Department {
  return { id, name, is_archived: isArchived }
}

const DUPLICATE = { detail: 'A department with this name already exists.' }
const IN_USE = {
  detail: 'This department is used by jobs. Archive it instead.',
  code: 'department_in_use',
}

/** A little in-memory company that answers the way the real server does. */
function startServer(initial: Department[] = [], user = adminUser) {
  const state = {
    departments: initial,
    failNext: {} as Record<string, Reply>,
    nextId: 100,
  }

  const backend = stubBackend((call) => {
    const key = `${call.method} ${call.path}`
    const planned = state.failNext[key.split('?')[0]]
    if (planned) {
      delete state.failNext[key.split('?')[0]]
      return planned
    }
    if (key === 'GET /api/auth/me') return { status: 200, body: sessionFor(user) }
    if (key === 'GET /health') return { status: 200, body: { status: 'ok' } }

    const url = new URL(call.path, 'http://app.test')
    if (call.method === 'GET' && url.pathname === '/api/departments') {
      const page = Number(url.searchParams.get('page') ?? '1')
      const pageSize = Number(url.searchParams.get('page_size') ?? '20')
      const start = (page - 1) * pageSize
      return {
        status: 200,
        body: {
          items: state.departments.slice(start, start + pageSize),
          total: state.departments.length,
          page,
          page_size: pageSize,
        },
      }
    }
    if (key === 'POST /api/departments') {
      const { name } = call.body as { name: string }
      if (state.departments.some((d) => d.name.toLowerCase() === name.toLowerCase())) {
        return { status: 409, body: DUPLICATE }
      }
      const created = department(`d-${state.nextId++}`, name)
      state.departments.push(created)
      return { status: 201, body: created }
    }
    const one = url.pathname.match(/^\/api\/departments\/([^/]+)(\/archive|\/unarchive)?$/)
    if (one) {
      const found = state.departments.find((d) => d.id === one[1])!
      if (call.method === 'PATCH') {
        const { name } = call.body as { name: string }
        if (
          state.departments.some(
            (d) => d.id !== found.id && d.name.toLowerCase() === name.toLowerCase(),
          )
        ) {
          return { status: 409, body: DUPLICATE }
        }
        found.name = name
        return { status: 200, body: found }
      }
      if (call.method === 'DELETE') {
        state.departments = state.departments.filter((d) => d.id !== found.id)
        return { status: 204 }
      }
      found.is_archived = one[2] === '/archive'
      return { status: 200, body: found }
    }
    throw new Error(`Unplanned request in test: ${key}`)
  })

  return { state, calls: backend.calls }
}

function rowOf(name: string) {
  return within(screen.getByRole('row', { name: new RegExp(name) }))
}

describe('DepartmentsPage', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('lists departments, archived ones too, with their status', async () => {
    startServer([department('d1', 'Engineering'), department('d2', 'Old team', true)])
    renderApp('/departments')

    expect(await screen.findByRole('heading', { name: 'Departments' })).toBeInTheDocument()
    await screen.findByRole('table', { name: /departments/i })
    expect(rowOf('Engineering').getByText('Active')).toBeInTheDocument()
    expect(rowOf('Old team').getByText('Archived')).toBeInTheDocument()
  })

  it('says so when there are no departments yet', async () => {
    startServer([])
    renderApp('/departments')

    expect(await screen.findByText(/no departments yet/i)).toBeInTheDocument()
  })

  it('shows names as text, never as HTML', async () => {
    startServer([department('d1', '<img src=x onerror=alert(1)>')])
    renderApp('/departments')

    expect(await screen.findByText('<img src=x onerror=alert(1)>')).toBeInTheDocument()
    expect(document.querySelector('main img')).toBeNull()
  })

  it('says so when the list cannot be loaded, and lets the admin try again', async () => {
    const server = startServer([department('d1', 'Engineering')])
    server.state.failNext['GET /api/departments'] = { status: 500 }
    renderApp('/departments')

    expect(await screen.findByRole('alert')).toHaveTextContent(/something went wrong/i)
    press(/try again/i)

    expect(await screen.findByRole('table', { name: /departments/i })).toBeInTheDocument()
  })
})

describe('DepartmentsPage: adding', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('adds a department, with the CSRF token, and shows it', async () => {
    const { calls } = startServer([])
    renderApp('/departments')
    await screen.findByText(/no departments yet/i)

    fillIn(/department name/i, 'Sales')
    press(/add department/i)

    expect(await screen.findByRole('table', { name: /departments/i })).toBeInTheDocument()
    expect(rowOf('Sales').getByText('Active')).toBeInTheDocument()
    expect(screen.getByLabelText(/department name/i)).toHaveValue('')
    const post = calls.find((c) => c.method === 'POST' && c.path === '/api/departments')
    expect(post?.body).toEqual({ name: 'Sales' })
    expect(post?.headers['X-CSRF-Token']).toBe('csrf-token-1')
  })

  it('shows the server message for a name that is taken, and keeps what was typed', async () => {
    startServer([department('d1', 'Sales')])
    renderApp('/departments')
    await screen.findByRole('table', { name: /departments/i })

    fillIn(/department name/i, 'sales')
    press(/add department/i)

    expect(await screen.findByRole('alert')).toHaveTextContent(/already exists/i)
    expect(screen.getByLabelText(/department name/i)).toHaveValue('sales')
  })
})

describe('DepartmentsPage: changing a department', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renames a department', async () => {
    const { calls } = startServer([department('d1', 'Eng')])
    renderApp('/departments')
    await screen.findByRole('table', { name: /departments/i })

    press(/rename eng/i)
    expect(screen.getByLabelText(/new name for eng/i)).toHaveValue('Eng')
    fillIn(/new name for eng/i, 'Engineering')
    press(/^save$/i)

    expect(await screen.findByText('Engineering')).toBeInTheDocument()
    expect(screen.queryByLabelText(/new name for/i)).not.toBeInTheDocument()
    const patch = calls.find((c) => c.method === 'PATCH')
    expect(patch?.path).toBe('/api/departments/d1')
    expect(patch?.body).toEqual({ name: 'Engineering' })
  })

  it('cancels a rename without asking the server', async () => {
    const { calls } = startServer([department('d1', 'Eng')])
    renderApp('/departments')
    await screen.findByRole('table', { name: /departments/i })

    press(/rename eng/i)
    fillIn(/new name for eng/i, 'Something else')
    press(/^cancel$/i)

    expect(screen.getByText('Eng')).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'PATCH')).toBe(false)
  })

  it('keeps the rename open and shows the message when the name is taken', async () => {
    startServer([department('d1', 'Eng'), department('d2', 'Sales')])
    renderApp('/departments')
    await screen.findByRole('table', { name: /departments/i })

    press(/rename eng/i)
    fillIn(/new name for eng/i, 'sales')
    press(/^save$/i)

    expect(await screen.findByRole('alert')).toHaveTextContent(/already exists/i)
    expect(screen.getByLabelText(/new name for eng/i)).toHaveValue('sales')
  })

  it('archives and brings back a department', async () => {
    const { calls } = startServer([department('d1', 'Engineering')])
    renderApp('/departments')
    await screen.findByRole('table', { name: /departments/i })

    press(/archive engineering/i)
    await waitFor(() => expect(rowOf('Engineering').getByText('Archived')).toBeInTheDocument())
    press(/unarchive engineering/i)
    await waitFor(() => expect(rowOf('Engineering').getByText('Active')).toBeInTheDocument())

    const paths = calls.filter((c) => c.method === 'POST').map((c) => c.path)
    expect(paths).toEqual(['/api/departments/d1/archive', '/api/departments/d1/unarchive'])
  })

  it('asks before deleting, and does nothing on cancel', async () => {
    const { calls } = startServer([department('d1', 'Typo dept')])
    renderApp('/departments')
    await screen.findByRole('table', { name: /departments/i })

    press(/delete typo dept/i)
    const dialog = within(await screen.findByRole('alertdialog'))
    expect(dialog.getByText(/delete typo dept\?/i)).toBeInTheDocument()
    fireEvent.click(dialog.getByRole('button', { name: 'Cancel' }))

    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
    expect(screen.getByText('Typo dept')).toBeInTheDocument()
  })

  it('deletes a department after confirmation', async () => {
    const { calls } = startServer([department('d1', 'Typo dept'), department('d2', 'Sales')])
    renderApp('/departments')
    await screen.findByRole('table', { name: /departments/i })

    press(/delete typo dept/i)
    const dialog = within(await screen.findByRole('alertdialog'))
    fireEvent.click(dialog.getByRole('button', { name: 'Delete' }))

    await waitFor(() => expect(screen.queryByText('Typo dept')).not.toBeInTheDocument())
    expect(calls.find((c) => c.method === 'DELETE')?.path).toBe('/api/departments/d1')
    expect(screen.getByText('Sales')).toBeInTheDocument()
  })

  it('shows the server message, and keeps the row, when a department is in use', async () => {
    const server = startServer([department('d1', 'Engineering')])
    server.state.failNext['DELETE /api/departments/d1'] = { status: 409, body: IN_USE }
    renderApp('/departments')
    await screen.findByRole('table', { name: /departments/i })

    press(/delete engineering/i)
    fireEvent.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Delete' }),
    )

    expect(await screen.findByRole('alert')).toHaveTextContent(/archive it instead/i)
    expect(screen.getByText('Engineering')).toBeInTheDocument()
  })
})

describe('DepartmentsPage: many departments', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows one page at a time and moves between pages', async () => {
    const many = Array.from({ length: 45 }, (_, n) =>
      department(`d${n}`, `Dept ${String(n).padStart(2, '0')}`),
    )
    const { calls } = startServer(many)
    renderApp('/departments')

    expect(await screen.findByText('Dept 00')).toBeInTheDocument()
    expect(screen.queryByText('Dept 20')).not.toBeInTheDocument()
    expect(screen.getByText(/page 1 of 3/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /previous/i })).toBeDisabled()

    press(/next/i)

    expect(await screen.findByText('Dept 20')).toBeInTheDocument()
    expect(screen.queryByText('Dept 00')).not.toBeInTheDocument()
    expect(screen.getByText(/page 2 of 3/i)).toBeInTheDocument()
    expect(calls.some((c) => c.path.includes('page=2'))).toBe(true)
  })

  it('steps back a page when the last department on it is deleted', async () => {
    const twentyOne = Array.from({ length: 21 }, (_, n) =>
      department(`d${n}`, `Dept ${String(n).padStart(2, '0')}`),
    )
    startServer(twentyOne)
    renderApp('/departments')
    await screen.findByText('Dept 00')
    press(/next/i)
    await screen.findByText('Dept 20')

    press(/delete dept 20/i)
    fireEvent.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Delete' }),
    )

    expect(await screen.findByText('Dept 00')).toBeInTheDocument()
    expect(screen.queryByText(/page \d of/i)).not.toBeInTheDocument()
  })

  it('offers a way back when the page being viewed no longer exists', async () => {
    const twentyOne = Array.from({ length: 21 }, (_, n) =>
      department(`d${n}`, `Dept ${String(n).padStart(2, '0')}`),
    )
    const server = startServer(twentyOne)
    renderApp('/departments')
    await screen.findByText('Dept 00')
    // Page 1 still says there are two pages when another admin deletes the 21st department.
    server.state.departments = twentyOne.slice(0, 20)

    press(/next/i)

    expect(await screen.findByText(/no departments on this page any more/i)).toBeInTheDocument()
    expect(screen.queryByRole('table', { name: /departments/i })).not.toBeInTheDocument()
    press(/back to the first page/i)
    expect(await screen.findByText('Dept 00')).toBeInTheDocument()
  })

  it('shows no pager when everything fits on one page', async () => {
    startServer([department('d1', 'Engineering')])
    renderApp('/departments')
    await screen.findByRole('table', { name: /departments/i })

    expect(screen.queryByText(/page 1 of/i)).not.toBeInTheDocument()
  })
})

describe('DepartmentsPage: who may open it', () => {
  beforeEach(() => {
    setCsrfToken(null)
    setUnauthorizedHandler(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows a recruiter "not found" and never asks for the list', async () => {
    const { calls } = startServer([department('d1', 'Engineering')], recruiterUser)
    renderApp('/departments')

    expect(await screen.findByText(/page not found/i)).toBeInTheDocument()
    expect(calls.some((c) => c.path.startsWith('/api/departments'))).toBe(false)
  })

  it('gives an admin a Departments link in the menu', async () => {
    startServer([])
    renderApp('/')

    const link = await screen.findByRole('link', { name: 'Departments' })
    expect(link).toHaveAttribute('href', '/departments')
  })
})
