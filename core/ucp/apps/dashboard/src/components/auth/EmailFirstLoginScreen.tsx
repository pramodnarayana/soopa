import { Button } from '@soopa/ui';
import { type FormEvent, useId, useState } from 'react';
import { config } from '@/lib/config';
import { consumeAuthCallbackError, discoverHomeRealm, startHrdSignIn } from '@/lib/hrd';

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/**
 * Gold-Standard Identifier-First (Email-First) Sign-In Screen.
 *
 * Never collects raw passwords in the SPA (OAuth 2.1 Authorization Code + PKCE).
 * Resolves the user's verified realm/IdP via POST /api/v1/auth/hrd and redirects
 * to the hosted IdP with `login_hint` pre-filled.
 */
export function EmailFirstLoginScreen() {
  const emailInputId = useId();
  const errorMessageId = useId();
  const [email, setEmail] = useState('');
  const [errorMessage, setErrorMessage] = useState<string | null>(() => consumeAuthCallbackError());
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = email.trim();

    if (!EMAIL_PATTERN.test(trimmed)) {
      setErrorMessage('Please enter a valid work email address.');
      return;
    }

    setErrorMessage(null);
    setStatusMessage('Checking your organization sign-in settings...');
    setIsSubmitting(true);

    const hrdResponse = await discoverHomeRealm(trimmed);
    if (!hrdResponse.ok) {
      setIsSubmitting(false);
      setStatusMessage(null);
      setErrorMessage(hrdResponse.message);
      return;
    }

    setStatusMessage(
      hrdResponse.value.requireSso
        ? "Redirecting to your organization's SSO provider..."
        : 'Redirecting to secure sign-in...',
    );

    const redirectOutcome = await startHrdSignIn(hrdResponse.value, [config.identity.authority]);
    if (!redirectOutcome.ok) {
      setIsSubmitting(false);
      setStatusMessage(null);
      setErrorMessage(redirectOutcome.message);
    }
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-md rounded-2xl border border-slate-200/80 bg-white p-8 shadow-sm">
        <div className="mx-auto mb-6 flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-indigo-600 shadow-md shadow-indigo-500/20">
          <svg
            aria-hidden="true"
            xmlns="http://www.w3.org/2000/svg"
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            stroke="white"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z" />
          </svg>
        </div>

        <div className="mb-6 text-center">
          <h1 className="mb-1.5 text-2xl font-bold tracking-tight text-slate-900">
            Sign in to Soopa
          </h1>
          <p className="text-sm text-slate-500">
            Enter your work email to continue with password, passkey, or enterprise SSO.
          </p>
        </div>

        <form onSubmit={(event) => void handleSubmit(event)} noValidate className="space-y-4">
          <div className="space-y-1.5 text-left">
            <label htmlFor={emailInputId} className="block text-sm font-medium text-slate-700">
              Work email
            </label>
            <input
              id={emailInputId}
              name="email"
              type="email"
              inputMode="email"
              autoComplete="username email"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              required
              disabled={isSubmitting}
              value={email}
              onChange={(event) => {
                setEmail(event.target.value);
                if (errorMessage) setErrorMessage(null);
              }}
              placeholder="name@company.com"
              aria-invalid={Boolean(errorMessage)}
              aria-describedby={errorMessage ? errorMessageId : undefined}
              className="block w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm text-slate-900 placeholder:text-slate-400 shadow-xs transition-colors focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-500"
            />
          </div>

          {errorMessage ? (
            <p
              id={errorMessageId}
              role="alert"
              className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-left text-xs font-medium text-red-700"
            >
              {errorMessage}
            </p>
          ) : null}

          {statusMessage ? (
            <p aria-live="polite" className="text-center text-xs font-medium text-indigo-600">
              {statusMessage}
            </p>
          ) : null}

          <Button
            type="submit"
            disabled={isSubmitting}
            className="w-full rounded-xl bg-indigo-600 px-4 py-2.5 font-semibold text-white shadow-sm transition-colors hover:bg-indigo-700 disabled:opacity-60"
          >
            {isSubmitting ? 'Continuing...' : 'Continue'}
          </Button>
        </form>
      </div>
    </main>
  );
}
