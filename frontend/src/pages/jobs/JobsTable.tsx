import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { formatDate } from '@/lib/format'
import { STATUS_LABELS } from './types'
import type { JobStatus, JobSummary } from './types'

const STATUS_BADGE: Record<JobStatus, 'secondary' | 'default' | 'outline'> = {
  draft: 'secondary',
  open: 'default',
  closed: 'outline',
}

export default function JobsTable({ jobs }: { jobs: JobSummary[] }) {
  return (
    <Table aria-label="Jobs">
      <TableHeader>
        <TableRow>
          <TableHead>Title</TableHead>
          <TableHead>Department</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Opened</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {jobs.map((job) => (
          <TableRow key={job.id}>
            <TableCell className="font-medium">
              {job.title}
              <span className="block text-sm font-normal text-muted-foreground">
                {job.location}
              </span>
            </TableCell>
            <TableCell>{job.department_name}</TableCell>
            <TableCell className="space-x-2">
              <Badge variant={STATUS_BADGE[job.status]}>{STATUS_LABELS[job.status]}</Badge>
              {job.needs_reassignment && <Badge variant="destructive">Needs a recruiter</Badge>}
            </TableCell>
            <TableCell>{job.opened_at ? formatDate(job.opened_at) : ''}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
