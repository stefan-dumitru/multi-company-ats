// Adds matchers such as toBeInTheDocument() to Vitest's expect.
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Vitest does not clean up rendered components between tests by default; without this, one
// test's output stays in the page and breaks the next.
afterEach(() => {
  cleanup()
})
