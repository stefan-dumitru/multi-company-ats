import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

interface FormFieldProps {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  type?: string
  autoComplete?: string
  /** Help shown under the field and read out by screen readers with it. */
  hint?: string
}

/** A label tied to its input, so clicking the label focuses it and screen readers announce it. */
export default function FormField({
  id,
  label,
  value,
  onChange,
  type = 'text',
  autoComplete,
  hint,
}: FormFieldProps) {
  const hintId = hint ? `${id}-hint` : undefined
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        autoComplete={autoComplete}
        aria-describedby={hintId}
        required
      />
      {hint && (
        <p id={hintId} className="text-sm text-muted-foreground">
          {hint}
        </p>
      )}
    </div>
  )
}
