import { useState } from 'react'
import type { FormEvent } from 'react'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'
import { Textarea } from '@/components/ui/textarea'
import { RECOMMENDATION_LABELS } from './types'
import type { Recommendation, ScorecardSubmission } from './types'

// The same limit as the server, which is the one that enforces it.
const MAX_FEEDBACK = 4000

const RATING_HINTS = ['1 – Poor', '2 – Weak', '3 – Fine', '4 – Good', '5 – Excellent']

type RatingKey =
  | 'overall_rating'
  | 'technical_rating'
  | 'communication_rating'
  | 'problem_solving_rating'
  | 'culture_fit_rating'

// The fixed criteria (functional.md > Submit a scorecard), in the order the form asks for them.
const CRITERIA: { key: RatingKey; label: string }[] = [
  { key: 'overall_rating', label: 'Overall rating' },
  { key: 'technical_rating', label: 'Technical skills' },
  { key: 'communication_rating', label: 'Communication' },
  { key: 'problem_solving_rating', label: 'Problem solving' },
  { key: 'culture_fit_rating', label: 'Culture and team fit' },
]

interface ScorecardFormProps {
  /** A request is running; the form is switched off meanwhile. */
  busy: boolean
  /** What the server said when it refused, if it did. What was typed is kept. */
  error: string
  onSubmit: (submission: ScorecardSubmission) => void
}

/**
 * The form for the interviewer's one scorecard. A scorecard is final, so sending asks first. The
 * server checks everything again; the checks here only save a round trip.
 */
export default function ScorecardForm({ busy, error, onSubmit }: ScorecardFormProps) {
  const [ratings, setRatings] = useState<Record<RatingKey, string>>({
    overall_rating: '',
    technical_rating: '',
    communication_rating: '',
    problem_solving_rating: '',
    culture_fit_rating: '',
  })
  const [recommendation, setRecommendation] = useState<Recommendation | ''>('')
  const [feedback, setFeedback] = useState('')
  const [problem, setProblem] = useState('')
  const [confirming, setConfirming] = useState(false)

  function check(event: FormEvent) {
    event.preventDefault()
    for (const criterion of CRITERIA) {
      if (ratings[criterion.key] === '') {
        return setProblem(`Choose a rating for ${criterion.label.toLowerCase()}.`)
      }
    }
    if (recommendation === '') return setProblem('Choose a recommendation.')
    if (feedback.trim() === '') return setProblem('Write some feedback.')
    setProblem('')
    setConfirming(true)
  }

  function send() {
    if (recommendation === '') return
    onSubmit({
      overall_rating: Number(ratings.overall_rating),
      technical_rating: Number(ratings.technical_rating),
      communication_rating: Number(ratings.communication_rating),
      problem_solving_rating: Number(ratings.problem_solving_rating),
      culture_fit_rating: Number(ratings.culture_fit_rating),
      feedback: feedback.trim(),
      recommendation,
    })
  }

  return (
    <form onSubmit={check} className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        {CRITERIA.map((criterion) => (
          <div key={criterion.key} className="space-y-2">
            <Label htmlFor={criterion.key}>{criterion.label}</Label>
            <NativeSelect
              id={criterion.key}
              className="w-full"
              value={ratings[criterion.key]}
              onChange={(event) => setRatings({ ...ratings, [criterion.key]: event.target.value })}
            >
              <NativeSelectOption value="">Choose</NativeSelectOption>
              {RATING_HINTS.map((hint, index) => (
                <NativeSelectOption key={hint} value={String(index + 1)}>
                  {hint}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </div>
        ))}
        <div className="space-y-2">
          <Label htmlFor="recommendation">Recommendation</Label>
          <NativeSelect
            id="recommendation"
            className="w-full"
            value={recommendation}
            onChange={(event) => setRecommendation(event.target.value as Recommendation | '')}
          >
            <NativeSelectOption value="">Choose</NativeSelectOption>
            {(Object.keys(RECOMMENDATION_LABELS) as Recommendation[]).map((value) => (
              <NativeSelectOption key={value} value={value}>
                {RECOMMENDATION_LABELS[value]}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </div>
      </div>
      <div className="space-y-2">
        <Label htmlFor="feedback">Feedback</Label>
        <Textarea
          id="feedback"
          value={feedback}
          maxLength={MAX_FEEDBACK}
          onChange={(event) => setFeedback(event.target.value)}
        />
      </div>

      {(problem || error) && (
        <p role="alert" className="text-sm text-destructive">
          {problem || error}
        </p>
      )}
      <Button type="submit" disabled={busy}>
        Submit scorecard
      </Button>

      <AlertDialog open={confirming} onOpenChange={setConfirming}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Submit your scorecard?</AlertDialogTitle>
            <AlertDialogDescription>
              Once submitted it cannot be changed. You will then see your colleagues' scorecards for
              this interview.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep editing</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                setConfirming(false)
                send()
              }}
            >
              Yes, submit
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </form>
  )
}
