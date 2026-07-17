import React, { useState, useEffect } from 'react'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const TOKEN_KEY = 'queuezero_token'

export default function Login() {
  const [mode, setMode]           = useState('signin')
  const [name, setName]           = useState('')
  const [email, setEmail]         = useState('')
  const [password, setPassword]   = useState('')
  const [error, setError]         = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [checking, setChecking]   = useState(true)

  // If already logged in, skip straight to the app
  useEffect(() => {
    const token = localStorage.getItem(TOKEN_KEY)
    if (!token) { setChecking(false); return }
    fetch(`${API_URL}/auth/verify`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(data => { if (data.valid) window.location.replace('/app') })
      .catch(() => localStorage.removeItem(TOKEN_KEY))
      .finally(() => setChecking(false))
  }, [])

  const isSignup = mode === 'signup'

  const submit = async (e) => {
    e.preventDefault()
    if (submitting) return

    const n  = name.trim()
    const em = email.trim()
    if (isSignup && !n)                             return setError('Please enter your name.')
    if (!em || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(em)) return setError('Please enter a valid email address.')
    if (password.length < 8)                        return setError('Password must be at least 8 characters.')

    setError('')
    setSubmitting(true)
    try {
      const path = isSignup ? '/auth/signup' : '/auth/login'
      const body = isSignup ? { email: em, name: n, password } : { email: em, password }
      const res  = await fetch(`${API_URL}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) { setError(data.detail || 'Something went wrong.'); return }
      localStorage.setItem(TOKEN_KEY, data.access_token)
      window.location.replace('/app')
    } catch {
      setError('Could not reach the server. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  const swap = (next) => { setMode(next); setError('') }

  if (checking) {
    return (
      <div className="flex h-screen items-center justify-center bg-[#f2f8f6]">
        <span className="h-8 w-8 animate-spin rounded-full border-2 border-teal-600 border-t-transparent" />
      </div>
    )
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[#f2f8f6] px-4 text-slate-800">
      {/* Backdrop blobs */}
      <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -top-32 -left-24 h-96 w-96 rounded-full bg-teal-200/50 blur-3xl" />
        <div className="absolute top-1/3 -right-28 h-[28rem] w-[28rem] rounded-full bg-emerald-200/45 blur-3xl" />
        <div className="absolute -bottom-24 left-1/3 h-80 w-80 rounded-full bg-cyan-200/40 blur-3xl" />
      </div>

      <div className="relative z-10 w-full max-w-sm">
        {/* Logo */}
        <div className="mb-6 flex flex-col items-center text-center">
          <a href="/" className="mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-teal-600 to-emerald-600 text-white shadow-lg shadow-teal-600/25">
            <PulseIcon />
          </a>
          <h1 className="text-2xl font-bold text-slate-800">
            QueueZero
            <span className="ml-2 rounded-full bg-teal-100/80 px-2 py-0.5 align-middle text-xs font-semibold text-teal-800">
              AI
            </span>
          </h1>
          <p className="mt-1 text-sm text-slate-500">Skip the queue. Let AI book it.</p>
        </div>

        {/* Card */}
        <div className="rounded-2xl border border-white/70 bg-white/55 p-6 shadow-[0_8px_32px_rgba(15,110,86,0.10)] backdrop-blur-xl">
          {/* Tab switcher */}
          <div className="mb-5 grid grid-cols-2 gap-1 rounded-xl border border-teal-900/10 bg-white/50 p-1">
            {[{ key: 'signin', label: 'Sign in' }, { key: 'signup', label: 'Sign up' }].map(t => (
              <button
                key={t.key}
                type="button"
                onClick={() => swap(t.key)}
                className={`rounded-lg py-2 text-sm font-medium transition ${
                  mode === t.key
                    ? 'bg-gradient-to-br from-teal-600 to-emerald-600 text-white shadow-sm'
                    : 'text-slate-500 hover:text-teal-700'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          <form onSubmit={submit} className="flex flex-col gap-3">
            {isSignup && (
              <label className="flex flex-col gap-1">
                <span className="text-xs font-medium text-slate-500">Name</span>
                <input
                  type="text"
                  value={name}
                  onChange={e => setName(e.target.value)}
                  placeholder="Jane Doe"
                  autoFocus
                  className="w-full rounded-xl border border-teal-900/10 bg-white/80 px-3.5 py-2.5 text-sm outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-500/25"
                />
              </label>
            )}
            <label className="flex flex-col gap-1">
              <span className="text-xs font-medium text-slate-500">Email</span>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                placeholder="jane@example.com"
                autoFocus={!isSignup}
                className="w-full rounded-xl border border-teal-900/10 bg-white/80 px-3.5 py-2.5 text-sm outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-500/25"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs font-medium text-slate-500">Password</span>
              <input
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full rounded-xl border border-teal-900/10 bg-white/80 px-3.5 py-2.5 text-sm outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-500/25"
              />
            </label>

            {error && <p className="text-xs text-red-600">{error}</p>}

            <button
              type="submit"
              disabled={submitting}
              className="mt-1 flex items-center justify-center gap-2 rounded-xl bg-gradient-to-br from-teal-600 to-emerald-600 py-2.5 text-sm font-semibold text-white shadow-md shadow-teal-600/25 transition hover:from-teal-500 hover:to-emerald-500 active:scale-[0.99] disabled:cursor-default disabled:opacity-60"
            >
              {submitting && (
                <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/60 border-t-transparent" />
              )}
              {isSignup ? 'Create account' : 'Sign in'}
            </button>
          </form>

          <p className="mt-4 text-center text-xs text-slate-400">
            {isSignup ? 'Already have an account? ' : 'New to QueueZero? '}
            <button
              type="button"
              onClick={() => swap(isSignup ? 'signin' : 'signup')}
              className="font-medium text-teal-700 hover:text-teal-800"
            >
              {isSignup ? 'Sign in' : 'Create one'}
            </button>
          </p>
        </div>

        <p className="mt-4 text-center text-[11px] text-slate-400">
          Your details are used only to book and confirm appointments.{' '}
          <a href="/" className="underline underline-offset-2 hover:text-teal-700">Back to home</a>
        </p>
      </div>
    </div>
  )
}

function PulseIcon() {
  return (
    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 12h4l2-7 4 14 2-7h6" />
    </svg>
  )
}
