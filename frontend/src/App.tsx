import { Route, Routes } from 'react-router'
import { RequireAuth, RequireRole } from '@/auth/guards'
import Layout from '@/layout/Layout'
import AcceptInvitationPage from '@/pages/AcceptInvitationPage'
import HomePage from '@/pages/HomePage'
import LoginPage from '@/pages/LoginPage'
import NotFoundPage from '@/pages/NotFoundPage'
import RegisterCompanyPage from '@/pages/RegisterCompanyPage'
import UsersPage from '@/pages/UsersPage'
import VerifyEmailPage from '@/pages/VerifyEmailPage'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<HomePage />} />
        <Route path="login" element={<LoginPage />} />
        <Route path="register" element={<RegisterCompanyPage />} />
        <Route path="accept-invitation" element={<AcceptInvitationPage />} />
        <Route path="verify-email" element={<VerifyEmailPage />} />
        <Route element={<RequireAuth />}>
          <Route element={<RequireRole roles={['company_admin']} />}>
            <Route path="users" element={<UsersPage />} />
          </Route>
        </Route>
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
