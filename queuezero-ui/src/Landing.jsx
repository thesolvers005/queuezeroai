import React, { useState, useEffect, useRef } from 'react'

const DEMO_STEPS = [
  { id: 'resolve_location',     label: 'Located Mangalagiri',               detail: 'Lat 16.4307 · Lng 80.5674'         },
  { id: 'find_doctors',         label: 'Found 8 dermatologists nearby',     detail: 'Filtered by rating ≥ 4.5'           },
  { id: 'find_available_slots', label: 'Checked availability',              detail: 'Dr. Ananya Sharma — 09:30 open'     },
  { id: 'book_slot',            label: 'Booked slot',                       detail: 'Dr. Ananya Sharma · 09:30 tomorrow' },
  { id: 'send_notification',    label: 'Confirmation sent',                 detail: 'Email delivered to patient'          },
]

const STEPS_HOW = [
  {
    n: '01',
    title: 'Describe what you need',
    body: 'Type a single sentence — specialty, location, time preference, gender preference — anything. The AI handles the rest.',
  },
  {
    n: '02',
    title: 'Agent searches in real time',
    body: 'Watch the reasoning timeline as the agent finds nearby hospitals, filters doctors by rating and wait time, and checks live slot availability.',
  },
  {
    n: '03',
    title: 'Appointment confirmed',
    body: 'The slot is locked instantly. A confirmation email lands in your inbox. No forms, no phone queues, no hold music.',
  },
]

// --- Motion utilities ---

const prefersReduced = () =>
  typeof window !== 'undefined' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches

function useTilt() {
  const ref = useRef(null)
  useEffect(() => {
    if (prefersReduced()) return
    const el = ref.current
    if (!el) return
    const LIFT = '0 20px 48px rgba(15,110,86,0.16),0 8px 20px rgba(15,110,86,0.10)'
    const onMove = (e) => {
      const r  = el.getBoundingClientRect()
      const dx = ((e.clientX - r.left) / r.width  - 0.5) * 2
      const dy = ((e.clientY - r.top)  / r.height - 0.5) * 2
      el.style.transition = 'box-shadow 0.15s ease'
      el.style.transform  = `perspective(900px) rotateY(${dx * 8}deg) rotateX(${-dy * 8}deg) translateY(-4px)`
      el.style.boxShadow  = LIFT
    }
    const onLeave = () => {
      el.style.transition = 'transform 0.45s cubic-bezier(0.23,1,0.32,1),box-shadow 0.45s ease'
      el.style.transform  = ''
      el.style.boxShadow  = ''
    }
    el.style.willChange = 'transform'
    el.addEventListener('mousemove', onMove)
    el.addEventListener('mouseleave', onLeave)
    return () => {
      el.removeEventListener('mousemove', onMove)
      el.removeEventListener('mouseleave', onLeave)
    }
  }, [])
  return ref
}

function useStaggerReveal() {
  const ref = useRef(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (prefersReduced()) {
      Array.from(el.children).forEach(c => c.classList.add('revealed'))
      return
    }
    const obs = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return
      Array.from(el.children).forEach((c, i) => {
        c.style.transitionDelay = `${i * 80}ms`
        c.classList.add('revealed')
      })
      obs.disconnect()
    }, { threshold: 0.1 })
    obs.observe(el)
    return () => obs.disconnect()
  }, [])
  return ref
}

function useReveal() {
  const ref = useRef(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (prefersReduced()) { el.classList.add('revealed'); return }
    const obs = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return
      el.classList.add('revealed')
      obs.disconnect()
    }, { threshold: 0.12 })
    obs.observe(el)
    return () => obs.disconnect()
  }, [])
  return ref
}

function TiltCard({ children, className = '' }) {
  const ref = useTilt()
  return (
    <div ref={ref} className={className} style={{ transformStyle: 'preserve-3d' }}>
      {children}
    </div>
  )
}

// --- Main component ---

export default function Landing() {
  const [activeStep, setActiveStep] = useState(0)
  const [completed,  setCompleted]  = useState(new Set())

  const blobRef  = useRef(null)
  const howRef   = useStaggerReveal()
  const videoRef = useReveal()

  // Demo steps loop
  useEffect(() => {
    let step = 0
    let done = new Set()
    const TICK = 1300

    const advance = () => {
      done = new Set([...done, DEMO_STEPS[step].id])
      setCompleted(new Set(done))
      step++
      if (step < DEMO_STEPS.length) {
        setActiveStep(step)
        timer = setTimeout(advance, TICK)
      } else {
        timer = setTimeout(() => {
          step = 0
          done = new Set()
          setCompleted(new Set())
          setActiveStep(0)
          timer = setTimeout(advance, TICK)
        }, 2200)
      }
    }

    let timer = setTimeout(advance, TICK)
    return () => clearTimeout(timer)
  }, [])

  // Scroll parallax — blob layer drifts at 0.15× page scroll speed
  useEffect(() => {
    if (prefersReduced()) return
    let ticking = false
    const onScroll = () => {
      if (ticking) return
      ticking = true
      requestAnimationFrame(() => {
        if (blobRef.current) blobRef.current.style.transform = `translateY(${window.scrollY * 0.15}px)`
        ticking = false
      })
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <div className="relative min-h-screen overflow-x-hidden bg-white text-slate-800 antialiased">

      {/* Parallax blob layer — ambient CSS drift + scroll offset via JS */}
      <div ref={blobRef} aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
        <div className="blob-1 absolute -top-40 -left-28 h-[28rem] w-[28rem] rounded-full bg-teal-100/60 blur-3xl" />
        <div className="blob-2 absolute top-1/2 -right-32 h-[32rem] w-[32rem] rounded-full bg-emerald-100/50 blur-3xl" />
        <div className="blob-3 absolute -bottom-28 left-1/4 h-72 w-72 rounded-full bg-cyan-100/40 blur-3xl" />
      </div>

      {/* Sticky nav */}
      <nav className="sticky top-0 z-50 border-b border-slate-100 bg-white/80 backdrop-blur-xl">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-teal-600 to-emerald-600 text-white shadow-sm shadow-teal-600/20">
              <PulseIcon />
            </div>
            <span className="text-base font-bold text-slate-800">
              QueueZero
              <span className="ml-1.5 rounded-full bg-teal-50 px-2 py-0.5 align-middle text-[11px] font-semibold text-teal-700">
                AI
              </span>
            </span>
          </div>
          <div className="flex items-center gap-3">
            <a
              href="https://github.com/thesolvers005/queuezeroai"
              target="_blank"
              rel="noreferrer"
              className="hidden text-sm text-slate-500 hover:text-slate-800 sm:block"
            >
              GitHub
            </a>
            <a
              href="/login"
              className="rounded-xl bg-gradient-to-br from-teal-600 to-emerald-600 px-4 py-2 text-sm font-semibold text-white shadow-sm shadow-teal-600/20 transition hover:from-teal-500 hover:to-emerald-500"
            >
              Get started
            </a>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="mx-auto grid max-w-6xl grid-cols-1 gap-12 px-6 pb-16 pt-20 lg:grid-cols-2 lg:items-center lg:gap-16 lg:pt-28">
        {/* Left copy */}
        <div>
          <span className="mb-4 inline-flex items-center gap-1.5 rounded-full border border-teal-200 bg-teal-50 px-3 py-1 text-xs font-semibold text-teal-700">
            <span className="h-1.5 w-1.5 rounded-full bg-teal-500" />
            AI-powered · Real-time availability
          </span>
          <h1 className="mt-3 text-4xl font-extrabold leading-tight tracking-tight text-slate-900 sm:text-5xl lg:text-[3.25rem]">
            Book a doctor<br />
            <span className="bg-gradient-to-r from-teal-600 to-emerald-600 bg-clip-text text-transparent">
              in one sentence.
            </span>
          </h1>
          <p className="mt-5 max-w-md text-lg leading-relaxed text-slate-500">
            Describe what you need. Our AI agent finds nearby doctors, checks live
            queue times, and locks a slot — in seconds, not phone-hold minutes.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-4">
            <a
              href="/login"
              className="rounded-xl bg-gradient-to-br from-teal-600 to-emerald-600 px-6 py-3 text-sm font-semibold text-white shadow-md shadow-teal-600/25 transition hover:from-teal-500 hover:to-emerald-500 active:scale-[0.98]"
            >
              Try it now — it&apos;s free
            </a>
            <a href="#how" className="text-sm font-medium text-slate-500 hover:text-teal-700">
              See how it works ↓
            </a>
          </div>
        </div>

        {/* Right — animated demo card */}
        <div className="rounded-2xl border border-slate-100 bg-slate-50/80 p-6 shadow-[0_20px_60px_rgba(15,110,86,0.12)] backdrop-blur-sm">
          <div className="mb-4 rounded-xl border border-teal-900/10 bg-white px-4 py-3 text-sm text-slate-700 shadow-sm">
            "I need a dermatologist tomorrow near Mangalagiri, before noon"
          </div>

          <p className="mb-3 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            Agent reasoning
          </p>

          <div className="space-y-2">
            {DEMO_STEPS.map((s, i) => {
              const isDone   = completed.has(s.id)
              const isActive = activeStep === i && !isDone
              return (
                <div
                  key={s.id}
                  className={`flex items-start gap-3 rounded-xl px-3 py-2.5 transition-all duration-500 ${
                    isDone   ? 'bg-teal-50/80'  :
                    isActive ? 'bg-white shadow-sm ring-1 ring-teal-200' :
                               'opacity-40'
                  }`}
                >
                  <span className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold transition-all duration-300 ${
                    isDone   ? 'bg-teal-500 text-white'                          :
                    isActive ? 'border-2 border-teal-500 bg-white text-teal-600' :
                               'border border-slate-200 bg-white text-slate-300'
                  }`}>
                    {isDone ? '✓' : i + 1}
                  </span>
                  <div className="min-w-0">
                    <p className={`text-xs font-semibold leading-snug ${isDone || isActive ? 'text-slate-800' : 'text-slate-400'}`}>
                      {s.label}
                      {isActive && (
                        <span className="ml-1.5 inline-flex gap-0.5">
                          {[0, 1, 2].map(d => (
                            <span key={d} className="inline-block h-1 w-1 animate-bounce rounded-full bg-teal-500" style={{ animationDelay: `${d * 150}ms` }} />
                          ))}
                        </span>
                      )}
                    </p>
                    {(isDone || isActive) && (
                      <p className="mt-0.5 text-[11px] text-slate-400">{s.detail}</p>
                    )}
                  </div>
                </div>
              )
            })}
          </div>

          {completed.size === DEMO_STEPS.length && (
            <div className="mt-4 rounded-xl bg-gradient-to-br from-teal-600 to-emerald-600 px-4 py-3 text-center text-sm font-semibold text-white shadow-sm">
              Appointment confirmed — Dr. Ananya Sharma · 09:30
            </div>
          )}
        </div>
      </section>

      {/* How it works */}
      <section id="how" className="bg-slate-50/60 px-6 py-20 backdrop-blur-sm">
        <div className="mx-auto max-w-6xl">
          <h2 className="text-center text-3xl font-bold text-slate-900">How it works</h2>
          <p className="mx-auto mt-3 max-w-xl text-center text-slate-500">
            Three steps from pain to appointment. No app download, no sign-up maze.
          </p>
          <div ref={howRef} className="mt-12 grid gap-8 sm:grid-cols-3">
            {STEPS_HOW.map(s => (
              <TiltCard key={s.n} className="reveal-item rounded-2xl border border-white bg-white p-7 shadow-sm">
                <span className="text-4xl font-extrabold text-teal-100">{s.n}</span>
                <h3 className="mt-3 text-base font-semibold text-slate-800">{s.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-slate-500">{s.body}</p>
              </TiltCard>
            ))}
          </div>
        </div>
      </section>

      {/* Video */}
      <section id="demo" className="px-6 py-20">
        <div className="mx-auto max-w-3xl">
          <h2 className="text-center text-3xl font-bold text-slate-900">See it in action</h2>
          <p className="mx-auto mt-3 max-w-lg text-center text-slate-500">
            A 90-second demo of the full booking flow — from natural language request to confirmed appointment.
          </p>
          <div ref={videoRef} className="reveal-item mt-10 aspect-video overflow-hidden rounded-2xl border border-slate-100 shadow-xl">
            <iframe
              src="https://www.youtube.com/embed/ViiwdQrSLR8"
              title="QueueZero AI demo"
              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
              allowFullScreen
              className="h-full w-full"
            />
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-slate-100 bg-white">
        <div className="mx-auto grid max-w-6xl grid-cols-1 gap-8 px-6 py-12 sm:grid-cols-3">
          {/* Left: logo + tagline */}
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2">
              <div className="flex h-7 w-7 items-center justify-center rounded-xl bg-gradient-to-br from-teal-600 to-emerald-600 text-white">
                <PulseIcon />
              </div>
              <span className="font-bold text-slate-800">QueueZero AI</span>
            </div>
            <p className="text-sm leading-relaxed text-slate-400">
              AI-powered hospital booking in one sentence.
            </p>
          </div>

          {/* Middle: nav links */}
          <div className="flex flex-col gap-2 sm:items-center">
            <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Links</p>
            <a href="#how"  className="text-sm text-slate-500 hover:text-teal-700">How it works</a>
            <a href="#demo" className="text-sm text-slate-500 hover:text-teal-700">Demo</a>
            <a
              href="https://github.com/thesolvers005/queuezeroai"
              target="_blank"
              rel="noreferrer"
              className="text-sm text-slate-500 hover:text-teal-700"
            >
              GitHub
            </a>
          </div>

          {/* Right: contact */}
          <div className="flex flex-col gap-2 sm:items-end">
            <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Contact</p>
            <a
              href="mailto:thesolvers005@gmail.com"
              className="text-sm text-slate-500 hover:text-teal-700"
            >
              thesolvers005@gmail.com
            </a>
          </div>
        </div>

        {/* Bottom bar */}
        <div className="border-t border-slate-100 px-6 py-4">
          <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-1 text-[11px] text-slate-400 sm:flex-row">
            <p>Built by The Solvers — Abdul Bashith Rompicherla, Vasireddi Nithya Santhoshini, Pallerla Devasena Reddy</p>
            <p>© {new Date().getFullYear()} QueueZero AI</p>
          </div>
        </div>
      </footer>
    </div>
  )
}

function PulseIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 12h4l2-7 4 14 2-7h6" />
    </svg>
  )
}
