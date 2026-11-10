import { useState } from 'react'
import type { FormEvent } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

// The same limit as the server (which is the one that enforces it).
const MAX_TEXT = 200

interface SearchFormProps {
  keywords: string
  location: string
  onSearch: (keywords: string, location: string) => void
}

/**
 * The search boxes. The search runs when the form is sent, not on every key, so typing does not
 * make a request per letter. The parent gives this form a new `key` when the address changes
 * (the back button), which starts it again from the address.
 */
export default function SearchForm({ keywords, location, onSearch }: SearchFormProps) {
  const [keywordsDraft, setKeywordsDraft] = useState(keywords)
  const [locationDraft, setLocationDraft] = useState(location)

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    onSearch(keywordsDraft.trim(), locationDraft.trim())
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
      <div className="min-w-56 flex-1 space-y-2">
        <Label htmlFor="search-keywords">Keywords</Label>
        <Input
          id="search-keywords"
          value={keywordsDraft}
          onChange={(event) => setKeywordsDraft(event.target.value)}
          maxLength={MAX_TEXT}
          placeholder="Job title or skill"
        />
      </div>
      <div className="min-w-44 flex-1 space-y-2">
        <Label htmlFor="search-location">Location</Label>
        <Input
          id="search-location"
          value={locationDraft}
          onChange={(event) => setLocationDraft(event.target.value)}
          maxLength={MAX_TEXT}
          placeholder="City or country"
        />
      </div>
      <Button type="submit">Search</Button>
    </form>
  )
}
