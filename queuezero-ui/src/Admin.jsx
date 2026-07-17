import React, { useState, useEffect, useRef } from 'react'
import { supabase } from './supabase.js'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const TOKEN_KEY = 'queuezero_token'

export default function Admin() {
  const [user, setUser]                     = useState(null)
  const [authChecking, setAuthChecking]     = useState(true)
  const [counters, setCounters]             = useState({ total: 0, booked: 0, available: 0, today: 0 })
  const [recentBookings, setRecentBookings] = useState([])
  const [hospitalCapacity, setHospitalCapacity] = useState([])
  const [connected, setConnected]           = useState(false)
  const [newIds, setNewIds]                 = useState(new Set())

  // Populated on first stats load; used to enrich Realtime INSERT payloads
  // (which carry doctor_id/hospital_id but not names)
  const doctorLookup   = useRef({}) // { doctor_id: { doctor_name, hospital_name } }
  const hospitalLookup = useRef({}) // { hospital_id: hospital_name }

  // ── Auth check ────────────────────────────────────────────────
  useEffect(() => {
    const token = localStorage.getItem(TOKEN_KEY)
    if (!token) { setAuthChecking(false); return }
    fetch(`${API_URL}/auth/verify`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(data => {
        if (!data.valid || !data.user?.is_admin) throw new Error('not admin')
        setUser(data.user)
      })
      .catch(() => localStorage.removeItem(TOKEN_KEY))
      .finally(() => setAuthChecking(false))
  }, [])

  // ── Initial stats load ────────────────────────────────────────
  useEffect(() => { if (user) loadStats() }, [user])

  const loadStats = async () => {
    const token = localStorage.getItem(TOKEN_KEY)
    try {
      const r = await fetch(`${API_URL}/admin/stats`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!r.ok) return
      const data = await r.json()
      setCounters(data.counters)
      setRecentBookings(data.recent_bookings || [])
      setHospitalCapacity(data.hospital_capacity || [])
      // Populate lookup caches so Realtime events can be enriched without extra fetches
      doctorLookup.current = data.doctor_lookup || {}
      const hmap = {}
      for (const h of data.hospital_capacity || []) hmap[h.hospital_id] = h.hospital_name
      hospitalLookup.current = hmap
    } catch (e) {
      console.error('Admin stats load failed:', e)
    }
  }

  // ── Supabase Realtime ─────────────────────────────────────────
  useEffect(() => {
    if (!user || !supabase) return

    const channel = supabase
      .channel('admin-dashboard')
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'appointments' }, ({ new: appt }) => {
        if (appt.status === 'cancelled') return

        // Enrich with names from lookup cache
        const info = doctorLookup.current[appt.doctor_id] || {}
        const enriched = {
          ...appt,
          doctor_name:   info.doctor_name   || '—',
          hospital_name: info.hospital_name || hospitalLookup.current[appt.hospital_id] || '—',
        }

        // Prepend to feed and trigger slide-in animation
        setRecentBookings(prev => [enriched, ...prev].slice(0, 30))
        setNewIds(prev => new Set([...prev, appt.id]))
        setTimeout(() => setNewIds(prev => { const s = new Set(prev); s.delete(appt.id); return s }), 2500)

        // Update counters
        const todayStr = new Date().toISOString().split('T')[0]
        setCounters(prev => ({
          ...prev,
          booked:    prev.booked + 1,
          available: Math.max(0, prev.available - 1),
          today:     appt.appointment_date === todayStr ? prev.today + 1 : prev.today,
        }))

        // Update hospital bar
        setHospitalCapacity(prev =>
          prev.map(h =>
            h.hospital_id === appt.hospital_id
              ? { ...h, booked: h.booked + 1, available: Math.max(0, h.available - 1) }
              : h
          )
        )
      })
      .on('postgres_changes', { event: 'UPDATE', schema: 'public', table: 'appointments' }, ({ new: appt }) => {
        // Reflect cancellations
        if (appt.status === 'cancelled') {
          setRecentBookings(prev => prev.filter(b => b.id !== appt.id))
          setCounters(prev => ({
            ...prev,
            booked:    Math.max(0, prev.booked - 1),
            available: prev.available + 1,
          }))
          setHospitalCapacity(prev =>
            prev.map(h =>
              h.hospital_id === appt.hospital_id
                ? { ...h, booked: Math.max(0, h.booked - 1), available: h.available + 1 }
                : h
            )
          )
        }
      })
      .subscribe(status => setConnected(status === 'SUBSCRIBED'))

    return () => { supabase.removeChannel(channel) }
  }, [user])

  // ── Render ────────────────────────────────────────────────────
  if (authChecking) {
    return (
      <div className="flex h-screen items-center justify-center bg-[#f2f8f6]">
        <span className="h-8 w-8 animate-spin rounded-full border-2 border-teal-600 border-t-transparent" />
      </div>
    )
  }

  if (!user) {
    return (
      <div className="flex h-screen flex-col items-center justify-center bg-[#f2f8f6]">
        <div className="rounded-2xl border border-white/70 bg-white/60 p-8 text-center shadow-lg backdrop-blur-xl">
          <p className="text-lg font-semibold text-slate-800">Admin access required</p>
          <p className="mt-1 text-sm text-slate-500">Sign in to an admin account to view this page.</p>
          <a
            href="/"
            className="mt-5 inline-block rounded-xl bg-gradient-to-br from-teal-600 to-emerald-600 px-5 py-2.5 text-sm font-semibold text-white shadow-md transition hover:from-teal-500 hover:to-emerald-500"
          >
            Back to app
          </a>
        </div>
      </div>
    )
  }

  if (!supabase) {
    return (
      <div className="flex h-screen flex-col items-center justify-center bg-[#f2f8f6] px-4">
        <div className="max-w-sm rounded-2xl border border-amber-200 bg-amber-50/80 p-8 text-center backdrop-blur-xl">
          <p className="font-semibold text-amber-900">Realtime not configured</p>
          <p className="mt-2 text-sm text-amber-800">
            Add <code className="rounded bg-amber-100 px-1">VITE_SUPABASE_URL</code> and{' '}
            <code className="rounded bg-amber-100 px-1">VITE_SUPABASE_ANON_KEY</code> to{' '}
            <code className="rounded bg-amber-100 px-1">queuezero-ui/.env</code>, then rebuild.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="relative min-h-screen bg-[#f2f8f6] text-slate-800">
      {/* Backdrop blobs */}
      <div aria-hidden className="pointer-events-none fixed inset-0 overflow-hidden">
        <div className="absolute -top-32 -left-24 h-96 w-96 rounded-full bg-teal-200/40 blur-3xl" />
        <div className="absolute top-1/3 -right-28 h-[28rem] w-[28rem] rounded-full bg-emerald-200/35 blur-3xl" />
        <div className="absolute -bottom-24 left-1/3 h-80 w-80 rounded-full bg-cyan-200/30 blur-3xl" />
      </div>

      <div className="relative z-10">
        {/* Header */}
        <header className="border-b border-white/70 bg-white/60 backdrop-blur-xl">
          <div className="mx-auto flex w-full max-w-7xl items-center justify-between px-6 py-3">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-teal-600 to-emerald-600 text-white shadow-md shadow-teal-600/25">
                <PulseIcon />
              </div>
              <div>
                <span className="text-base font-bold text-slate-800">QueueZero</span>
                <span className="ml-2 rounded-full bg-teal-100/80 px-2 py-0.5 text-[11px] font-semibold text-teal-800">
                  Admin
                </span>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <span className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium ${
                connected
                  ? 'border-emerald-200/80 bg-emerald-50/70 text-emerald-800'
                  : 'border-amber-200/80 bg-amber-50/70 text-amber-700'
              }`}>
                <span className={`h-1.5 w-1.5 rounded-full ${connected ? 'animate-pulse bg-emerald-500' : 'bg-amber-400'}`} />
                {connected ? 'Realtime connected' : 'Connecting…'}
              </span>
              <a
                href="/"
                className="rounded-full border border-teal-900/10 bg-white/70 px-3 py-1 text-xs font-medium text-slate-600 backdrop-blur transition hover:border-teal-400 hover:text-teal-800"
              >
                ← Back to app
              </a>
            </div>
          </div>
        </header>

        <main className="mx-auto max-w-7xl space-y-6 p-6">
          {/* Counter row */}
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <CounterCard label="Total Slots"   value={counters.total}     color="slate"   />
            <CounterCard label="Booked"        value={counters.booked}    color="red"     />
            <CounterCard label="Available"     value={counters.available} color="teal"    />
            <CounterCard label="Booked Today"  value={counters.today}     color="emerald" />
          </div>

          {/* Feed + capacity */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_340px]">
            {/* Live booking feed */}
            <div className="rounded-2xl border border-white/70 bg-white/55 shadow-[0_8px_32px_rgba(15,110,86,0.10)] backdrop-blur-xl">
              <div className="flex items-center gap-2 border-b border-white/70 px-5 py-3.5">
                <span className="relative flex h-2 w-2">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-teal-500 opacity-60" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-teal-600" />
                </span>
                <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Live Booking Feed
                </h2>
                <span className="ml-auto text-xs text-slate-400">{recentBookings.length} shown</span>
              </div>
              <div className="overflow-hidden">
                {recentBookings.length === 0 ? (
                  <p className="py-12 text-center text-sm text-slate-400">
                    Waiting for bookings… book through the agent to see them appear here.
                  </p>
                ) : (
                  <div className="divide-y divide-white/50">
                    {recentBookings.map(b => (
                      <BookingRow key={b.id} booking={b} isNew={newIds.has(b.id)} />
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Per-hospital capacity */}
            <div className="rounded-2xl border border-white/70 bg-white/55 shadow-[0_8px_32px_rgba(15,110,86,0.08)] backdrop-blur-xl">
              <div className="border-b border-white/70 px-5 py-3.5">
                <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Hospital Capacity
                </h2>
              </div>
              <div className="space-y-5 p-5">
                {hospitalCapacity.length === 0 ? (
                  <p className="text-sm text-slate-400">Loading…</p>
                ) : (
                  hospitalCapacity.map(h => (
                    <HospitalBar key={h.hospital_id} hospital={h} />
                  ))
                )}
              </div>
            </div>
          </div>
        </main>
      </div>
    </div>
  )
}

// ── Sub-components ─────────────────────────────────────────────

function CounterCard({ label, value, color }) {
  const colorMap = {
    slate:   'text-slate-800',
    red:     'text-red-600',
    teal:    'text-teal-700',
    emerald: 'text-emerald-700',
  }
  return (
    <div className="rounded-2xl border border-white/70 bg-white/55 p-5 shadow-[0_8px_32px_rgba(15,110,86,0.10)] backdrop-blur-xl">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">{label}</p>
      <p className={`mt-1 text-4xl font-bold tabular-nums transition-all duration-500 ${colorMap[color] || colorMap.slate}`}>
        {value}
      </p>
    </div>
  )
}

function BookingRow({ booking, isNew }) {
  return (
    <div className={`flex items-center gap-4 px-5 py-3.5 transition-colors duration-300 ${
      isNew ? 'bg-teal-50/80 animate-[slideDown_350ms_ease-out]' : 'hover:bg-white/40'
    }`}>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-slate-800">
          {booking.patient_name || 'Anonymous'}
          {booking.is_emergency && (
            <span className="ml-2 rounded-full bg-red-100 px-1.5 py-0.5 text-[10px] font-semibold text-red-700">
              Emergency
            </span>
          )}
        </p>
        <p className="truncate text-xs text-slate-500">
          {booking.doctor_name} · {booking.hospital_name}
        </p>
      </div>
      <div className="shrink-0 text-right">
        <p className="text-xs font-medium text-slate-700">{booking.appointment_date}</p>
        <p className="text-xs text-slate-400">{booking.appointment_time}</p>
      </div>
    </div>
  )
}

function HospitalBar({ hospital }) {
  const pct = hospital.total > 0 ? Math.round((hospital.booked / hospital.total) * 100) : 0
  const barColor =
    pct > 80 ? 'from-red-400 to-red-500' :
    pct > 60 ? 'from-amber-400 to-orange-400' :
               'from-teal-500 to-emerald-500'
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <p className="truncate text-sm font-medium text-slate-700">{hospital.hospital_name}</p>
        <p className="shrink-0 tabular-nums text-xs text-slate-500">
          {hospital.booked}/{hospital.total}
        </p>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-100">
        <div
          className={`h-full rounded-full bg-gradient-to-r transition-all duration-700 ${barColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="mt-1 text-[11px] text-slate-400">{hospital.available} slots available</p>
    </div>
  )
}

function PulseIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 12h4l2-7 4 14 2-7h6" />
    </svg>
  )
}
