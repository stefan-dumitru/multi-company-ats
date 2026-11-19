import { Route, Routes } from 'react-router'
import { RequireAuth, RequireRole } from '@/auth/guards'
import Layout from '@/layout/Layout'
import AcceptInvitationPage from '@/pages/AcceptInvitationPage'
import ApplicationPage from '@/pages/ApplicationPage'
import ApplicationsPage from '@/pages/ApplicationsPage'
import DepartmentsPage from '@/pages/DepartmentsPage'
import ForgotPasswordPage from '@/pages/ForgotPasswordPage'
import HomePage from '@/pages/HomePage'
import JobDetailPage from '@/pages/JobDetailPage'
import JobsPage from '@/pages/JobsPage'
import LoginPage from '@/pages/LoginPage'
import MyInterviewPage from '@/pages/MyInterviewPage'
import MyInterviewsPage from '@/pages/MyInterviewsPage'
import NewJobPage from '@/pages/NewJobPage'
import PublicJobPage from '@/pages/PublicJobPage'
import PublicJobsPage from '@/pages/PublicJobsPage'
import NotFoundPage from '@/pages/NotFoundPage'
import RegisterCompanyPage from '@/pages/RegisterCompanyPage'
import ProfilePage from '@/pages/ProfilePage'
import RegisterCandidatePage from '@/pages/RegisterCandidatePage'
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
        <Route path="register/candidate" element={<RegisterCandidatePage />} />
        <Route path="accept-invitation" element={<AcceptInvitationPage />} />
        <Route path="verify-email" element={<VerifyEmailPage />} />
        <Route path="forgot-password" element={<ForgotPasswordPage />} />
        <Route path="reset-password" element={<ResetPasswordPage />} />
        <Route path="jobs" element={<PublicJobsPage />} />
        <Route path="jobs/:jobId" element={<PublicJobPage />} />
        <Route element={<RequireAuth />}>
          <Route element={<RequireRole roles={['candidate']} />}>
            <Route path="profile" element={<ProfilePage />} />
            <Route path="applications" element={<ApplicationsPage />} />
          </Route>
          <Route element={<RequireRole roles={['interviewer']} />}>
            <Route path="interviews" element={<MyInterviewsPage />} />
            <Route path="interviews/:interviewId" element={<MyInterviewPage />} />
          </Route>
          <Route element={<RequireRole roles={['company_admin', 'recruiter']} />}>
            <Route path="manage/jobs" element={<JobsPage />} />
            <Route path="manage/jobs/new" element={<NewJobPage />} />
            <Route path="manage/jobs/:jobId" element={<JobDetailPage />} />
            <Route path="manage/applications/:applicationId" element={<ApplicationPage />} />
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
