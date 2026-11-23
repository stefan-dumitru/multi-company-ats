// The codes the way back from Google can end with (backend services/google_login.py). The login
// page shows our own words for them, never text taken from the address.
const GOOGLE_ERROR_MESSAGES: Record<string, string> = {
  access_denied: 'Google did not allow access, so you were not signed in.',
  bad_state: 'That sign-in attempt expired or was not started here. Please try again.',
  missing_code: 'Google did not send what we needed. Please try again.',
  google_unavailable: 'Google could not be reached. Please try again in a few minutes.',
  google_refused: 'Google did not accept the sign-in. Please try again.',
  google_error: 'Google reported a problem. Please try again.',
  not_configured: 'Signing in with Google isn’t set up on this server.',
  email_not_verified:
    'Google has not verified that email address, so we cannot use it. Log in with your password instead.',
  account_unverified:
    'An account with this email exists but its email is not confirmed yet. Log in with your password first, confirm your email, then try Google again.',
  account_unavailable: 'This account cannot sign in.',
  try_again: 'That did not work this time. Please try again.',
}
const UNKNOWN_GOOGLE_ERROR = 'Signing in with Google did not work. Please try again.'

/** Our words for a code from the address; anything unrecognised gets the general sentence. */
export function googleErrorMessage(code: string): string {
  return GOOGLE_ERROR_MESSAGES[code] ?? UNKNOWN_GOOGLE_ERROR
}
