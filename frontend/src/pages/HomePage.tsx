import HealthStatus from '@/HealthStatus'

export default function HomePage() {
  return (
    <section className="space-y-3">
      <h1 className="text-2xl font-semibold">Applicant Tracking System</h1>
      <HealthStatus />
    </section>
  )
}
