import { Link } from 'react-router'

export default function NotFoundPage() {
  return (
    <section className="space-y-3">
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <p className="text-muted-foreground">This page does not exist, or you cannot open it.</p>
      <Link to="/" className="text-primary underline underline-offset-4">
        Go to the home page
      </Link>
    </section>
  )
}
