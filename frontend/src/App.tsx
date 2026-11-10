import { Route, Routes } from 'react-router'
import { RequireAuth, RequireRole } from '@/auth/guards'
import Layout from '@/layout/Layout'
import AcceptInvitationPage from '@/pages/AcceptInvitationPage'
import DepartmentsPage from '@/pages/DepartmentsPage'
import ForgotPasswordPage from '@/pages/ForgotPasswordPage'
import HomePage from '@/pages/HomePage'
import JobDetailPage from '@/pages/JobDetailPage'
import JobsPage from '@/pages/JobsPage'
import LoginPage from '@/pages/LoginPage'
import NewJobPage from '@/pages/NewJobPage'
import NotFoundPage from '@/pages/NotFoundPage'
import RegisterCompanyPage from '@/pages/RegisterCompanyPage'
import ResetPasswordPage from '@/pages/ResetPasswordPage'
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
        <Route path="forgot-password" element={<ForgotPasswordPage />} />
        <Route path="reset-password" element={<ResetPasswordPage />} />
        <Route element={<RequireAuth />}>
          <Route element={<RequireRole roles={['company_admin', 'recruiter']} />}>
            <Route path="manage/jobs" element={<JobsPage />} />
            <Route path="manage/jobs/new" element={<NewJobPage />} />
            <Route path="manage/jobs/:jobId" element={<JobDetailPage />} />
          </Route>
          <Route element={<RequireRole roles={['company_admin']} />}>
            <Route path="users" element={<UsersPage />} />
            <Route path="departments" element={<DepartmentsPage />} />
          </Route>
        </Route>
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
