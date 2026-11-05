import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { AuthProvider } from '@/auth/AuthContext'
import App from '@/App'

/** The whole app at an address, with the router and auth provider that main.tsx supplies. */
export function renderApp(path = '/', state?: unknown) {
  const [pathname, search = ''] = path.split('?')
  const entry = state === undefined ? path : { pathname, search: search && `?${search}`, state }
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

/** Type into a field found by its visible label, the way a person finds it. */
export function fillIn(label: string | RegExp, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } })
}

export function press(name: string | RegExp) {
  fireEvent.click(screen.getByRole('button', { name }))
}
