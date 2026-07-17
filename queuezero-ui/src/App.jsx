import React, { useState, useRef, useEffect } from "react";

/**
 * QueueZero AI — chat UI
 *
 * Layout: chat on the left, live "Agent reasoning" panel on the right.
 * Style: clean medical light (teal palette) with glass surfaces.
 *
 * Point API_URL at the FastAPI backend. Defaults to local dev.
 */

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
const TOKEN_KEY = "queuezero_token";

const CANCEL_REASONS = [
  { value: "schedule_conflict", label: "Schedule conflict" },
  { value: "found_another_doctor", label: "Found another doctor" },
  { value: "recovered", label: "Recovered / no longer needed" },
  { value: "emergency", label: "Emergency arose" },
  { value: "booked_by_mistake", label: "Booked by mistake" },
  { value: "other", label: "Other" },
];

const STEP_LABELS = {
  resolve_location: "Located the area",
  search_hospitals: "Searched nearby hospitals",
  find_doctors: "Filtered matching doctors",
  find_available_slots: "Compared available slots",
  book_slot: "Booked the appointment",
  emergency_book: "Emergency priority booking",
  find_patient_by_name: "Looked up patient record",
  send_notification: "Sent confirmation",
};

const EXAMPLES = [
  "I need a female cardiologist after 3 PM today within 10 km of Mangalagiri",
  "Book a dermatologist tomorrow morning, my name is Ravi Kumar",
  "My father has severe chest pain, we are near Vijayawada",
];

// Matches the specialties in the Supabase seed data.
const SPECIALTIES = [
  "Cardiology",
  "Dermatology",
  "General Physician",
  "Pediatrics",
  "Orthopedics",
  "ENT",
  "Gynecology",
  "Neurology",
  "Dentistry",
];

const WHEN_OPTIONS = [
  { key: "today", label: "Today", phrase: "today" },
  { key: "week", label: "This week", phrase: "sometime this week" },
  { key: "next", label: "Next available", phrase: "next available slot" },
];

export default function QueueZeroApp() {
  const [user, setUser] = useState(null);
  const [authChecking, setAuthChecking] = useState(true);
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState("");
  const [sessionId, setSessionId] = useState(null);
  const [patientName, setPatientName] = useState("");
  const [patientEmail, setPatientEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [isEmergency, setIsEmergency] = useState(false);
  const [health, setHealth] = useState({ status: "checking" });
  const [quickSpec, setQuickSpec] = useState("");
  const [quickWhen, setQuickWhen] = useState("next");
  const [streamingSteps, setStreamingSteps] = useState([]);
  const [streamingActive, setStreamingActive] = useState(false);
  const [liveMode, setLiveMode] = useState(true);

  // Bookings panel state
  const [showBookings, setShowBookings] = useState(false);
  const [bookings, setBookings] = useState([]);
  const [bookingsLoading, setBookingsLoading] = useState(false);
  const [cancelModal, setCancelModal] = useState(null); // {id, doctor_name, appointment_date, appointment_time}
  const [cancelReason, setCancelReason] = useState("");
  const [cancelDetail, setCancelDetail] = useState("");
  const [cancelError, setCancelError] = useState("");
  const [cancelSubmitting, setCancelSubmitting] = useState(false);
  const [cancelCount, setCancelCount] = useState(null);

  const messagesEndRef = useRef(null);
  const timelineEndRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    setSessionId(`sess_${Date.now()}`);
    fetch(`${API_URL}/health`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => setHealth({ status: "up", mode: d.mode }))
      .catch(() => setHealth({ status: "down" }));
  }, []);

  // Restore a persisted session on load by verifying the stored token with the
  // backend, so a refresh doesn't bounce a logged-in user back to AuthScreen.
  useEffect(() => {
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) {
      setAuthChecking(false);
      return;
    }
    fetch(`${API_URL}/auth/verify`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((data) => {
        if (!data.valid) throw new Error("invalid token");
        setUser(data.user);
        setPatientName(data.user.name || "");
        setPatientEmail(data.user.email || "");
      })
      .catch(() => {
        localStorage.removeItem(TOKEN_KEY);
      })
      .finally(() => setAuthChecking(false));
  }, []);

  useEffect(() => {
    if (showBookings) loadBookings();
  }, [showBookings]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  useEffect(() => {
    timelineEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [streamingSteps]);

  const loadBookings = async () => {
    setBookingsLoading(true);
    setCancelCount(null);
    try {
      const token = localStorage.getItem(TOKEN_KEY);
      const r = await fetch(`${API_URL}/api/bookings/mine`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await r.json();
      setBookings(data.bookings || []);
    } catch {
      // silently fail — panel will show empty state
    } finally {
      setBookingsLoading(false);
    }
  };

  const openCancelModal = (booking) => {
    setCancelModal(booking);
    setCancelReason("");
    setCancelDetail("");
    setCancelError("");
  };

  const submitCancel = async () => {
    if (!cancelModal || !cancelReason) return;
    if (cancelReason === "other" && !cancelDetail.trim()) {
      setCancelError("Please describe the reason.");
      return;
    }
    setCancelSubmitting(true);
    setCancelError("");
    try {
      const token = localStorage.getItem(TOKEN_KEY);
      const r = await fetch(`${API_URL}/api/bookings/${cancelModal.id}/cancel`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          reason: cancelReason,
          reason_detail: cancelDetail || undefined,
        }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || "Cancellation failed.");
      setCancelCount(data.cancellation_count);
      setCancelModal(null);
      loadBookings();
    } catch (err) {
      setCancelError(err.message);
    } finally {
      setCancelSubmitting(false);
    }
  };

  const sendMessage = async (text) => {
    const userMessage = (text ?? inputValue).trim();
    if (!userMessage || loading) return;

    setInputValue("");
    setQuickSpec("");
    setLoading(true);
    setMessages((prev) => [...prev, { role: "user", content: userMessage }]);

    try {
      const token = localStorage.getItem(TOKEN_KEY);
      const response = await fetch(`${API_URL}/book`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          user_message: userMessage,
          patient_name: patientName || undefined,
          patient_email: patientEmail.trim() || undefined,
          session_id: sessionId,
        }),
      });

      if (!response.ok) {
        const body = await response.text();
        throw new Error(`${response.status} ${response.statusText} — ${body}`);
      }

      const data = await response.json();
      if (data.session_id) setSessionId(data.session_id);
      if (data.is_emergency) setIsEmergency(true);

      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.reply,
          steps: data.steps || [],
          appointment: data.appointment || null,
        },
      ]);
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", isError: true, content: `Request failed: ${error.message}` },
      ]);
    } finally {
      setLoading(false);
    }
  };

  // Live streaming path — same payload/session semantics as sendMessage, but
  // consumes POST /api/chat/stream (SSE) so the reasoning panel can animate
  // each tool step as it actually happens instead of all at once at the end.
  // sendMessage above is left fully intact as the non-streaming fallback.
  const streamBooking = async (text) => {
    const userMessage = (text ?? inputValue).trim();
    if (!userMessage || streamingActive || loading) return;

    setInputValue("");
    setQuickSpec("");
    setStreamingSteps([]);
    setStreamingActive(true);
    setMessages((prev) => [...prev, { role: "user", content: userMessage }]);

    try {
      const token = localStorage.getItem(TOKEN_KEY);
      const response = await fetch(`${API_URL}/api/chat/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          user_message: userMessage,
          patient_name: patientName || undefined,
          patient_email: patientEmail.trim() || undefined,
          session_id: sessionId,
        }),
      });

      if (!response.ok || !response.body) {
        const body = await response.text().catch(() => "");
        throw new Error(`${response.status} ${response.statusText} — ${body}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let done = false;

      while (!done) {
        const { value, done: readerDone } = await reader.read();
        if (readerDone) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const rawLine of lines) {
          const line = rawLine.trim();
          if (!line) continue;
          const payload = line.startsWith("data: ") ? line.slice(6) : line;
          if (payload === "[DONE]") {
            done = true;
            break;
          }

          let event;
          try {
            event = JSON.parse(payload);
          } catch {
            continue;
          }

          if (event.id != null) {
            setStreamingSteps((prev) => {
              const i = prev.findIndex((s) => s.id === event.id);
              if (i === -1) return [...prev, event];
              const next = prev.slice();
              next[i] = event;
              return next;
            });
          } else if (event.type === "final") {
            if (event.session_id) setSessionId(event.session_id);
            if (event.is_emergency) setIsEmergency(true);
            setMessages((prev) => [
              ...prev,
              {
                role: "assistant",
                content: event.reply,
                steps: event.steps || [],
                appointment: event.appointment || null,
              },
            ]);
          } else if (event.type === "error") {
            setMessages((prev) => [
              ...prev,
              { role: "assistant", isError: true, content: `Request failed: ${event.message}` },
            ]);
          }
        }
      }
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", isError: true, content: `Request failed: ${error.message}` },
      ]);
    } finally {
      setStreamingActive(false);
    }
  };

  const submit = (t) => {
    if (liveMode) {
      streamBooking(t);
    } else {
      setStreamingSteps([]);
      sendMessage(t);
    }
  };

  const onKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const composeQuickBook = (spec, whenKey) => {
    setQuickSpec(spec);
    setQuickWhen(whenKey);
    if (!spec) return;
    const when = WHEN_OPTIONS.find((w) => w.key === whenKey) || WHEN_OPTIONS[2];
    setInputValue(`I need a ${spec} appointment near me, ${when.phrase}.`);
    inputRef.current?.focus();
  };

  const handleLogout = () => {
    localStorage.removeItem(TOKEN_KEY);
    window.location.replace("/login");
  };

  if (authChecking) {
    return (
      <div className="flex h-screen items-center justify-center bg-[#f2f8f6]">
        <span className="h-8 w-8 animate-spin rounded-full border-2 border-teal-600 border-t-transparent" />
      </div>
    );
  }

  if (!user) {
    window.location.replace("/login");
    return null;
  }

  const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant" && m.steps?.length);
  const panelSteps = lastAssistant?.steps || [];

  return (
    <div className="relative h-screen overflow-hidden bg-[#f2f8f6] text-slate-800">
      <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -top-32 -left-24 h-96 w-96 rounded-full bg-teal-200/50 blur-3xl" />
        <div className="absolute top-1/3 -right-28 h-[28rem] w-[28rem] rounded-full bg-emerald-200/45 blur-3xl" />
        <div className="absolute -bottom-24 left-1/3 h-80 w-80 rounded-full bg-cyan-200/40 blur-3xl" />
      </div>

      <div className="relative z-10 flex h-full flex-col">
        <Header
          health={health}
          user={user}
          onLogout={handleLogout}
          onShowBookings={() => setShowBookings(true)}
        />

        {isEmergency && (
          <div className="mx-auto mt-3 w-full max-w-6xl px-4">
            <div className="flex items-center gap-3 rounded-xl border border-red-300/70 bg-red-50/80 px-4 py-2.5 backdrop-blur-xl">
              <span className="relative flex h-2.5 w-2.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-red-500 opacity-60" />
                <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-red-600" />
              </span>
              <p className="text-sm text-red-800">
                <span className="font-semibold">Emergency mode active</span> — priority booking,
                nearest suitable doctor, no extra questions
              </p>
            </div>
          </div>
        )}

        <main className="mx-auto grid w-full max-w-6xl flex-1 min-h-0 grid-cols-1 gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_340px]">
          {/* Chat card */}
          <section className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-white/70 bg-white/55 shadow-[0_8px_32px_rgba(15,110,86,0.10)] backdrop-blur-xl">
            <div className="flex-1 space-y-4 overflow-y-auto p-5">
              {messages.length === 0 ? (
                <EmptyState onPick={(t) => submit(t)} />
              ) : (
                <>
                  {messages.map((msg, idx) => (
                    <MessageRow key={idx} msg={msg} />
                  ))}
                  {loading && <TypingIndicator />}
                  <div ref={messagesEndRef} />
                </>
              )}
            </div>

            {/* Input bar */}
            <div className="border-t border-white/70 bg-white/50 p-4 backdrop-blur-xl">
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <select
                  value={quickSpec}
                  onChange={(e) => composeQuickBook(e.target.value, quickWhen)}
                  aria-label="Quick book by specialty"
                  className="h-8 rounded-lg border border-teal-900/10 bg-white/60 px-2 text-xs text-slate-600 outline-none transition hover:border-teal-400 focus:border-teal-500"
                >
                  <option value="">Quick book by specialty…</option>
                  {SPECIALTIES.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
                {WHEN_OPTIONS.map((w) => (
                  <button
                    key={w.key}
                    onClick={() => composeQuickBook(quickSpec, w.key)}
                    disabled={!quickSpec}
                    className={`h-8 rounded-full border px-3 text-xs transition disabled:cursor-default disabled:opacity-40 ${
                      quickSpec && quickWhen === w.key
                        ? "border-teal-500/50 bg-teal-100/80 font-medium text-teal-800"
                        : "border-teal-900/10 bg-white/50 text-slate-500 hover:border-teal-400 hover:text-teal-700"
                    }`}
                  >
                    {w.label}
                  </button>
                ))}
                <span className="hidden text-[11px] text-slate-400 sm:inline">
                  drops a draft below — edit before sending
                </span>
              </div>
              <div className="flex flex-col gap-2 lg:flex-row lg:items-end">
                <div className="flex flex-1 gap-2">
                  <textarea
                    ref={inputRef}
                    value={inputValue}
                    onChange={(e) => setInputValue(e.target.value)}
                    onKeyDown={onKeyDown}
                    placeholder="Describe the appointment you need…"
                    rows={1}
                    className="max-h-32 min-h-[42px] flex-1 resize-none rounded-xl border border-teal-900/10 bg-white/80 px-4 py-2.5 text-sm outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-500/25"
                  />
                  <button
                    onClick={() => submit()}
                    disabled={loading || streamingActive || !inputValue.trim()}
                    aria-label="Send message"
                    className="flex h-[42px] w-[42px] shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-teal-600 to-emerald-600 text-white shadow-md shadow-teal-600/25 transition hover:from-teal-500 hover:to-emerald-500 active:scale-95 disabled:from-slate-300 disabled:to-slate-300 disabled:shadow-none"
                  >
                    <SendIcon />
                  </button>
                </div>
              </div>
              <div className="mt-2 flex items-center justify-between">
                <p className="text-xs text-slate-400">
                  Enter to send · Shift+Enter for a new line
                </p>
                <button
                  type="button"
                  onClick={() => setLiveMode((v) => !v)}
                  aria-pressed={liveMode}
                  className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium transition ${
                    liveMode
                      ? "border-teal-500/50 bg-teal-100/80 text-teal-800"
                      : "border-teal-900/10 bg-white/50 text-slate-400 hover:border-teal-400 hover:text-teal-700"
                  }`}
                >
                  <span
                    className={`flex h-3.5 w-6 items-center rounded-full transition ${
                      liveMode ? "justify-end bg-teal-600" : "justify-start bg-slate-300"
                    }`}
                  >
                    <span className="h-2.5 w-2.5 rounded-full bg-white shadow-sm" />
                  </span>
                  Live reasoning
                </button>
              </div>
            </div>
          </section>

          {/* Reasoning panel */}
          <aside className="flex min-h-0 max-h-64 flex-col overflow-hidden rounded-2xl border border-white/70 bg-white/45 shadow-[0_8px_32px_rgba(15,110,86,0.08)] backdrop-blur-xl lg:max-h-none">
            <div className="flex items-center gap-2 border-b border-white/70 px-4 py-3">
              <BrainIcon />
              <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Agent reasoning
              </h2>
              {(loading || streamingActive) && (
                <span className="ml-auto flex items-center gap-1.5 text-xs text-teal-700">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-teal-600" />
                  {streamingActive ? "streaming…" : "working"}
                </span>
              )}
            </div>
            <div className="flex-1 overflow-y-auto p-4">
              {streamingActive || streamingSteps.length > 0 ? (
                <LiveTimelinePanel
                  steps={streamingSteps}
                  active={streamingActive}
                  endRef={timelineEndRef}
                />
              ) : panelSteps.length === 0 && !loading ? (
                <p className="text-sm leading-relaxed text-slate-400">
                  Each step the agent takes — locating you, comparing doctors, booking the slot —
                  will appear here live.
                </p>
              ) : (
                <ol className="flex flex-col">
                  {panelSteps.map((step, i) => (
                    <StepItem
                      key={i}
                      step={step}
                      isLast={i === panelSteps.length - 1 && !loading}
                    />
                  ))}
                  {loading && (
                    <li className="flex gap-3">
                      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-teal-300 bg-white/80">
                        <span className="h-2 w-2 animate-pulse rounded-full bg-teal-500" />
                      </span>
                      <p className="pt-0.5 text-sm text-slate-500">Thinking…</p>
                    </li>
                  )}
                </ol>
              )}
            </div>
          </aside>
        </main>
      </div>

      {/* My Bookings slide-over */}
      {showBookings && (
        <BookingsPanel
          bookings={bookings}
          loading={bookingsLoading}
          cancelCount={cancelCount}
          onClose={() => setShowBookings(false)}
          onCancel={openCancelModal}
        />
      )}

      {/* Cancel modal — sits above the slide-over */}
      {cancelModal && (
        <CancelModal
          booking={cancelModal}
          reason={cancelReason}
          detail={cancelDetail}
          error={cancelError}
          submitting={cancelSubmitting}
          onReasonChange={setCancelReason}
          onDetailChange={setCancelDetail}
          onConfirm={submitCancel}
          onClose={() => setCancelModal(null)}
        />
      )}
    </div>
  );
}

function Header({ health, user, onLogout, onShowBookings }) {
  const pill =
    health.status === "up"
      ? {
          dot: "bg-emerald-500",
          text: health.mode === "live" ? "Agent live" : "Agent live · mock mode",
          cls: "border-emerald-200/80 bg-emerald-50/70 text-emerald-800",
        }
      : health.status === "down"
        ? { dot: "bg-red-500", text: "Backend offline", cls: "border-red-200/80 bg-red-50/70 text-red-700" }
        : { dot: "bg-amber-400", text: "Connecting…", cls: "border-amber-200/80 bg-amber-50/70 text-amber-700" };

  const displayName = user?.name?.trim();

  return (
    <header className="border-b border-white/70 bg-white/60 backdrop-blur-xl">
      <div className="mx-auto flex w-full max-w-6xl items-center justify-between px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-teal-600 to-emerald-600 text-white shadow-md shadow-teal-600/25">
            <PulseIcon />
          </div>
          <div>
            <h1 className="text-lg font-bold leading-tight text-slate-800">
              QueueZero
              <span className="ml-2 rounded-full bg-teal-100/80 px-2 py-0.5 align-middle text-[11px] font-semibold text-teal-800">
                AI
              </span>
            </h1>
            <p className="text-xs text-slate-500">
              {displayName ? `Welcome, ${displayName}` : "Skip the queue. Let AI book it."}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`hidden items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium backdrop-blur sm:flex ${pill.cls}`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${pill.dot}`} />
            {pill.text}
          </span>
          {displayName && (
            <span className="hidden items-center gap-1.5 rounded-full border border-teal-900/10 bg-white/70 px-3 py-1 text-xs font-medium text-slate-600 backdrop-blur sm:flex">
              <UserIcon />
              {displayName}
            </span>
          )}
          {user && (
            <button
              onClick={onShowBookings}
              className="flex items-center gap-1.5 rounded-full border border-teal-900/10 bg-white/70 px-3 py-1 text-xs font-medium text-slate-600 backdrop-blur transition hover:border-teal-400 hover:text-teal-800"
            >
              <CalendarIcon />
              My bookings
            </button>
          )}
          {user && (
            <button
              onClick={onLogout}
              className="flex items-center gap-1.5 rounded-full border border-teal-900/10 bg-white/70 px-3 py-1 text-xs font-medium text-slate-600 backdrop-blur transition hover:border-teal-400 hover:text-teal-800"
            >
              <LogoutIcon />
              Log out
            </button>
          )}
        </div>
      </div>
    </header>
  );
}

// ------------------------------------------------------------------
// Bookings panel (slide-over from right)
// ------------------------------------------------------------------
function BookingsPanel({ bookings, loading, cancelCount, onClose, onCancel }) {
  const today = new Date().toISOString().split("T")[0];
  const upcoming = bookings.filter((b) => b.status !== "cancelled" && b.appointment_date >= today);
  const past = bookings.filter((b) => b.status === "cancelled" || b.appointment_date < today);

  return (
    <div className="fixed inset-0 z-50 flex">
      <div
        className="absolute inset-0 bg-slate-900/20 backdrop-blur-sm"
        onClick={onClose}
      />
      <div className="relative ml-auto h-full w-full max-w-md overflow-y-auto border-l border-white/70 bg-white/90 shadow-2xl backdrop-blur-xl">
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-white/70 bg-white/80 px-5 py-4 backdrop-blur">
          <h2 className="font-semibold text-slate-800">My Bookings</h2>
          <button
            onClick={onClose}
            className="rounded-lg p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
          >
            <XIcon />
          </button>
        </div>

        {cancelCount != null && (
          <div className="mx-4 mt-4 rounded-xl border border-amber-200 bg-amber-50/80 px-4 py-2.5 text-sm text-amber-800">
            Cancellation recorded. You have cancelled{" "}
            <span className="font-semibold">{cancelCount}</span> booking
            {cancelCount !== 1 ? "s" : ""} total.
          </div>
        )}

        {loading ? (
          <div className="flex justify-center py-16">
            <span className="h-6 w-6 animate-spin rounded-full border-2 border-teal-600 border-t-transparent" />
          </div>
        ) : (
          <div className="space-y-6 p-4">
            {bookings.length === 0 ? (
              <p className="py-12 text-center text-sm text-slate-400">
                No bookings yet. Book your first appointment to see it here.
              </p>
            ) : (
              <>
                <BookingSection title="Upcoming" items={upcoming} onCancel={onCancel} showCancel />
                <BookingSection title="Past & Cancelled" items={past} />
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function BookingSection({ title, items, onCancel, showCancel }) {
  if (items.length === 0) return null;
  return (
    <div>
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">
        {title}
      </h3>
      <div className="space-y-3">
        {items.map((b) => (
          <BookingCard key={b.id} booking={b} onCancel={onCancel} showCancel={showCancel} />
        ))}
      </div>
    </div>
  );
}

function BookingCard({ booking, onCancel, showCancel }) {
  const isCancelled = booking.status === "cancelled";
  return (
    <div
      className={`rounded-xl border p-4 ${
        isCancelled
          ? "border-slate-200 bg-slate-50/80"
          : "border-teal-200/80 bg-teal-50/60"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-slate-800">
            {booking.doctor_name || "Doctor"}
          </p>
          <p className="text-xs text-slate-500">{booking.hospital_name || "—"}</p>
        </div>
        {isCancelled ? (
          <span className="shrink-0 rounded-full bg-slate-200 px-2 py-0.5 text-[11px] font-medium text-slate-500">
            Cancelled
          </span>
        ) : booking.is_emergency ? (
          <span className="shrink-0 rounded-full bg-red-100 px-2 py-0.5 text-[11px] font-semibold text-red-700">
            Emergency
          </span>
        ) : null}
      </div>
      <div className="mt-2 flex gap-3 text-xs text-slate-500">
        <span>{booking.appointment_date}</span>
        <span>{booking.appointment_time}</span>
      </div>
      {showCancel && !isCancelled && (
        <button
          onClick={() => onCancel(booking)}
          className="mt-3 w-full rounded-lg border border-red-200 py-1.5 text-xs font-medium text-red-600 transition hover:bg-red-50 active:scale-[0.99]"
        >
          Cancel booking
        </button>
      )}
    </div>
  );
}

// ------------------------------------------------------------------
// Cancel modal
// ------------------------------------------------------------------
function CancelModal({
  booking, reason, detail, error, submitting,
  onReasonChange, onDetailChange, onConfirm, onClose,
}) {
  const canSubmit = reason && (reason !== "other" || detail.trim());

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center px-4">
      <div className="absolute inset-0 bg-slate-900/30 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-sm rounded-2xl border border-white/70 bg-white/90 p-6 shadow-2xl backdrop-blur-xl">
        <h3 className="mb-1 text-base font-semibold text-slate-800">Cancel booking</h3>
        <p className="mb-4 text-sm text-slate-500">
          {booking.doctor_name} · {booking.appointment_date} {booking.appointment_time}
        </p>

        <label className="mb-1 block text-xs font-medium text-slate-500">
          Reason <span className="text-red-500">*</span>
        </label>
        <select
          value={reason}
          onChange={(e) => onReasonChange(e.target.value)}
          className="mb-3 w-full rounded-xl border border-teal-900/10 bg-white/80 px-3.5 py-2.5 text-sm outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-500/25"
        >
          <option value="">Select a reason…</option>
          {CANCEL_REASONS.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </select>

        {reason === "other" && (
          <>
            <label className="mb-1 block text-xs font-medium text-slate-500">
              Please specify <span className="text-red-500">*</span>
            </label>
            <textarea
              value={detail}
              onChange={(e) => onDetailChange(e.target.value)}
              rows={2}
              placeholder="Tell us more…"
              className="mb-3 w-full resize-none rounded-xl border border-teal-900/10 bg-white/80 px-3.5 py-2.5 text-sm outline-none transition focus:border-teal-500 focus:ring-2 focus:ring-teal-500/25"
            />
          </>
        )}

        {error && <p className="mb-3 text-xs text-red-600">{error}</p>}

        <div className="flex gap-2">
          <button
            onClick={onClose}
            className="flex-1 rounded-xl border border-teal-900/10 py-2.5 text-sm font-medium text-slate-600 transition hover:bg-slate-50"
          >
            Keep booking
          </button>
          <button
            onClick={onConfirm}
            disabled={!canSubmit || submitting}
            className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-red-500 py-2.5 text-sm font-semibold text-white transition hover:bg-red-600 active:scale-[0.99] disabled:opacity-50"
          >
            {submitting && (
              <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/60 border-t-transparent" />
            )}
            Confirm cancel
          </button>
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------
// Existing chat components (unchanged)
// ------------------------------------------------------------------

function MessageRow({ msg }) {
  if (msg.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-teal-700 px-4 py-2.5 text-sm leading-relaxed text-white shadow-sm">
          <p className="whitespace-pre-wrap">{msg.content}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex justify-start">
        <div
          className={`max-w-[88%] rounded-2xl rounded-bl-md border px-4 py-2.5 text-sm leading-relaxed shadow-sm backdrop-blur ${
            msg.isError
              ? "border-red-200 bg-red-50/80 text-red-800"
              : "border-teal-900/5 bg-white/80 text-slate-700"
          }`}
        >
          <p className="whitespace-pre-wrap">{msg.content}</p>
        </div>
      </div>
      {msg.appointment && <AppointmentCard appt={msg.appointment} />}
    </div>
  );
}

function AppointmentCard({ appt }) {
  return (
    <div className="max-w-[88%] rounded-xl border border-emerald-300/70 bg-emerald-50/80 p-4 backdrop-blur">
      <div className="mb-2 flex items-center gap-2 text-emerald-800">
        <CheckBadgeIcon />
        <h3 className="text-sm font-semibold">Appointment confirmed</h3>
        {appt.is_emergency && (
          <span className="ml-auto rounded-full bg-red-100 px-2 py-0.5 text-[11px] font-semibold text-red-700">
            Emergency priority
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
        <Field label="Doctor" value={appt.doctor_name} />
        <Field label="Hospital" value={appt.hospital_name} />
        <Field label="Date" value={appt.appointment_date} />
        <Field label="Time" value={appt.appointment_time} />
        {appt.estimated_wait_mins != null && (
          <Field label="Est. wait" value={`${appt.estimated_wait_mins} min`} />
        )}
      </div>
    </div>
  );
}

function Field({ label, value }) {
  return (
    <div>
      <p className="text-[11px] font-semibold uppercase tracking-wide text-emerald-700/80">{label}</p>
      <p className="text-emerald-950">{value ?? "—"}</p>
    </div>
  );
}

function StepItem({ step, isLast }) {
  const hasError = step.output && step.output.error;
  let inputPreview = "";
  try {
    inputPreview = JSON.stringify(step.input);
  } catch {
    inputPreview = String(step.input);
  }
  if (inputPreview && inputPreview.length > 80) inputPreview = inputPreview.slice(0, 80) + "…";
  if (inputPreview === "{}" || inputPreview === "undefined") inputPreview = "";

  return (
    <li className="flex gap-3">
      <div className="flex flex-col items-center">
        <span
          className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full ${
            hasError
              ? "bg-red-100 text-red-600"
              : isLast
                ? "bg-gradient-to-br from-teal-600 to-emerald-600 text-white"
                : "bg-teal-100 text-teal-700"
          }`}
        >
          {hasError ? <XSmallIcon /> : <CheckSmallIcon />}
        </span>
        {!isLast && <span className="w-px flex-1 bg-teal-900/10" />}
      </div>
      <div className={isLast ? "" : "pb-4"}>
        <p className="text-sm font-medium leading-5 text-slate-700">
          {STEP_LABELS[step.tool] || step.tool}
        </p>
        <p className="font-mono text-[11px] text-slate-400">{step.tool}</p>
        {inputPreview && (
          <p className="mt-0.5 break-all font-mono text-[11px] text-slate-400/90">{inputPreview}</p>
        )}
        {hasError && <p className="mt-1 text-xs text-red-600">Error: {String(step.output.error)}</p>}
      </div>
    </li>
  );
}

function LiveTimelinePanel({ steps, active, endRef }) {
  if (steps.length === 0) {
    return (
      <p className="text-sm leading-relaxed text-slate-400">
        Each step the agent takes — locating you, comparing doctors, booking the slot — will
        appear here live.
      </p>
    );
  }

  return (
    <ol className="flex flex-col">
      {steps.map((step, i) => (
        <LiveStepItem key={step.id} step={step} isLast={i === steps.length - 1 && !active} />
      ))}
      {active && (
        <li className="flex gap-3">
          <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-teal-300 bg-white/80">
            <span className="h-2 w-2 animate-pulse rounded-full bg-teal-500" />
          </span>
          <p className="pt-0.5 text-sm text-slate-500">Thinking…</p>
        </li>
      )}
      <div ref={endRef} />
    </ol>
  );
}

function LiveStepItem({ step, isLast }) {
  const isError = step.status === "error";
  const isPending = step.status === "pending";

  return (
    <li className="flex gap-3 animate-[fadeIn_150ms_ease-out]">
      <div className="flex flex-col items-center">
        <span
          className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full transition-transform duration-150 ${
            isError
              ? "bg-red-100 text-red-600"
              : isPending
                ? "border border-teal-300 bg-white/80"
                : "scale-110 bg-gradient-to-br from-teal-600 to-emerald-600 text-white"
          }`}
        >
          {isError ? (
            <XSmallIcon />
          ) : isPending ? (
            <span className="h-2 w-2 animate-pulse rounded-full bg-teal-500" />
          ) : (
            <CheckSmallIcon />
          )}
        </span>
        {!isLast && <span className="w-px flex-1 bg-teal-900/10" />}
      </div>
      <div className={isLast ? "" : "pb-4"}>
        <p className="text-sm font-medium leading-5 text-slate-700">{step.step}</p>
        {step.details && (
          <p className="mt-0.5 break-all font-mono text-[11px] text-slate-400/90">
            {step.details}
          </p>
        )}
      </div>
    </li>
  );
}

function EmptyState({ onPick }) {
  return (
    <div className="flex h-full flex-col items-center justify-center px-4 text-center">
      <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-teal-600 to-emerald-600 text-white shadow-lg shadow-teal-600/25">
        <PulseIcon large />
      </div>
      <h2 className="mb-1 text-xl font-bold text-slate-800">Ready to book your appointment?</h2>
      <p className="mb-6 max-w-md text-sm text-slate-500">
        Tell me the specialty, time and location you need — I'll compare doctors, wait times and
        distance, then book the best slot for you.
      </p>
      <div className="flex w-full max-w-lg flex-col gap-2">
        {EXAMPLES.map((ex) => (
          <button
            key={ex}
            onClick={() => onPick(ex)}
            className="rounded-xl border border-teal-900/10 bg-white/70 px-4 py-2.5 text-left text-sm text-slate-600 backdrop-blur transition hover:border-teal-400 hover:bg-white hover:text-teal-800"
          >
            {ex}
          </button>
        ))}
      </div>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="flex items-center gap-2.5">
      <div className="flex items-center gap-1 rounded-2xl rounded-bl-md border border-teal-900/5 bg-white/80 px-4 py-3 backdrop-blur">
        <span className="h-2 w-2 animate-bounce rounded-full bg-teal-600 [animation-delay:-0.3s]" />
        <span className="h-2 w-2 animate-bounce rounded-full bg-teal-600 [animation-delay:-0.15s]" />
        <span className="h-2 w-2 animate-bounce rounded-full bg-teal-600" />
      </div>
      <span className="text-xs text-slate-400">Agent is working…</span>
    </div>
  );
}

/* --- inline icons (stroke inherits currentColor) --- */

function LogoutIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <path d="m16 17 5-5-5-5" />
      <path d="M21 12H9" />
    </svg>
  );
}

function CalendarIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
      <line x1="16" y1="2" x2="16" y2="6" />
      <line x1="8" y1="2" x2="8" y2="6" />
      <line x1="3" y1="10" x2="21" y2="10" />
    </svg>
  );
}

function XIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M18 6 6 18M6 6l12 12" />
    </svg>
  );
}

function PulseIcon({ large }) {
  const s = large ? 28 : 20;
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 12h4l2-7 4 14 2-7h6" />
    </svg>
  );
}

function SendIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M22 2 11 13" />
      <path d="M22 2 15 22l-4-9-9-4Z" />
    </svg>
  );
}

function BrainIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-teal-700" aria-hidden="true">
      <path d="M12 4.5a2.5 2.5 0 0 0-4.96-.46 2.5 2.5 0 0 0-1.98 3 2.5 2.5 0 0 0-1.32 4.24 3 3 0 0 0 .34 5.58 2.5 2.5 0 0 0 2.96 3.08A2.5 2.5 0 0 0 12 19.5Z" />
      <path d="M12 4.5a2.5 2.5 0 0 1 4.96-.46 2.5 2.5 0 0 1 1.98 3 2.5 2.5 0 0 1 1.32 4.24 3 3 0 0 1-.34 5.58 2.5 2.5 0 0 1-2.96 3.08A2.5 2.5 0 0 1 12 19.5Z" />
    </svg>
  );
}

function UserIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </svg>
  );
}

function CheckBadgeIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3.85 8.62a4 4 0 0 1 4.78-4.77 4 4 0 0 1 6.74 0 4 4 0 0 1 4.78 4.78 4 4 0 0 1 0 6.74 4 4 0 0 1-4.77 4.78 4 4 0 0 1-6.75 0 4 4 0 0 1-4.78-4.77 4 4 0 0 1 0-6.76Z" />
      <path d="m9 12 2 2 4-4" />
    </svg>
  );
}

function CheckSmallIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}

function XSmallIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M18 6 6 18M6 6l12 12" />
    </svg>
  );
}
