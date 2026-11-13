import { api } from '@/api/client'
import { useResource } from '@/api/useResource'
import { useAuth } from '@/auth/AuthContext'
import { Button } from '@/components/ui/button'
import ProfileForm from './profile/ProfileForm'
import type { ProfileValues } from './profile/ProfileForm'
import ResumeSection from './profile/ResumeSection'
import type { ResumeInfo } from './profile/ResumeSection'

/** What the server says about the candidate's own profile. */
interface Profile {
  full_name: string
  email: string
  phone: string | null
  location: string | null
  resume: ResumeInfo | null
}

export default function ProfilePage() {
  const { refreshUser } = useAuth()
  const profile = useResource<Profile>('/api/profile')

  async function save(values: ProfileValues) {
    await api('/api/profile', {
      method: 'PATCH',
      body: {
        full_name: values.full_name,
        // Blank means "none": null clears the field on the server.
        phone: values.phone.trim() || null,
        location: values.location.trim() || null,
      },
    })
    profile.reload()
    try {
      await refreshUser() // the name in the menu follows the profile
    } catch {
      // The save itself worked; the menu keeps the old name until the next page load.
    }
  }

  if (profile.loading && !profile.data) return <p role="status">Loading…</p>
  if (!profile.data) {
    return (
      <div className="space-y-2">
        <p role="alert" className="text-sm text-destructive">
          {profile.error}
        </p>
        <Button variant="outline" size="sm" onClick={profile.reload}>
          Try again
        </Button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Your profile</h1>
      <ProfileForm
        initial={{
          full_name: profile.data.full_name,
          phone: profile.data.phone ?? '',
          location: profile.data.location ?? '',
        }}
        email={profile.data.email}
        onSave={save}
      />
      <ResumeSection resume={profile.data.resume} onUploaded={profile.reload} />
    </div>
  )
}
