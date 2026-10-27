import { useEffect, useMemo, useRef, useState } from "react";
import QRCode from "qrcode";
import MapView from "./MapView";
import { WS, SearchGone, accept, getCenters, getHealth, getStatus, startTransfer, type Card, type Ticket, type Twin } from "./api";

const CASES: { key: string; label: string; detail: string }[] = [
  { key: "cardiac_icu", label: "Heart attack", detail: "needs a cath lab and cardiac ICU" },
  { key: "stroke_thrombectomy", label: "Stroke", detail: "needs a thrombectomy team" },
  { key: "trauma_adult", label: "Trauma", detail: "needs a Level I or II trauma center" },
  { key: "trauma_burn", label: "Burn", detail: "needs a verified burn center" },
  { key: "trauma_pediatric", label: "Pediatric", detail: "needs a pediatric trauma center" },
  { key: "childbirth", label: "Childbirth", detail: "needs labor and delivery, an emergency C-section team and a NICU" },
];

/** "2026-09-26T18:22:00Z" -> "1:22 PM" in the viewer's time zone. */
function clock(iso?: string): string {
  const d = iso ? new Date(iso) : undefined;
  return d && !Number.isNaN(d.getTime()) ? d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }) : "—";
}
/** "482913" -> "482 913", easier to read aloud. */

/** The tab remembers its search so Back (e.g. from the ticket page) brings it back; a refresh or a new visit still starts fresh. */
const SEARCH_KEY = "uzima-search";
function rememberSearch(tid: string) {
  try { sessionStorage.setItem(SEARCH_KEY, tid); } catch { /* storage blocked: Back starts fresh */ }
}
function searchToReopen(): string | null {
  const nav = performance.getEntriesByType?.("navigation")[0] as PerformanceNavigationTiming | undefined;
  try { return nav?.type === "back_forward" ? sessionStorage.getItem(SEARCH_KEY) : null; } catch { return null; }
}

export default function App() {
  const [specialty, setSpecialty] = useState("cardiac_icu");
  const [sending, setSending] = useState<{ lat: number; lng: number; name: string; short_name?: string }>();
  const [names, setNames] = useState<Record<string, string>>({});
  const [windows, setWindows] = useState<Record<string, any>>({});
  const [tid, setTid] = useState<string>();
  const [cards, setCards] = useState<Record<string, Card>>({});
  const [startedAt, setStartedAt] = useState<number>();
  const [stoppedAt, setStoppedAt] = useState<number>();
  const [now, setNow] = useState(Date.now());
  const [rec, setRec] = useState<any>();
  const [twin, setTwin] = useState<Twin>();
  const [qr, setQr] = useState<string>();
  const [bridgeMode, setBridgeMode] = useState<string>();
  const [bridgeStatus, setBridgeStatus] = useState<string>();
  const bridgeLabel: Record<string, string> = {
    calling_accepting_doctor: "Calling accepting doctor; referral summary will play first",
    calling_sending_doctor: "Calling referring doctor; waiting for both doctors to join",
    connected: "Doctors connected — call in progress",
    ended: "Doctor call ended",
    failed: "Doctor connection ended before both doctors joined",
  };
  const [busy, setBusy] = useState(false);
  const [starting, setStarting] = useState(false);
  const [windowMin, setWindowMin] = useState<number>();
  const [error, setError] = useState<string>();
  const [liveCalls, setLiveCalls] = useState(false);   // real phone calls only when the Twilio gateway is live
  const [visitorCalls, setVisitorCalls] = useState(false);   // public demo: a visitor can answer the first hospital call
  const [phone, setPhone] = useState("");
  const [askCall, setAskCall] = useState(false);       // the "take the first call yourself" popup
  const [callerId, setCallerId] = useState<string>();
  const [callNote, setCallNote] = useState<string>();
  const [doctorPopup, setDoctorPopup] = useState(true);
  const [ended, setEnded] = useState(false);
  const [awake, setAwake] = useState(false);           // the backend answered; after a quiet period it needs ~30 s to start           // the server no longer has this search (e.g. it restarted)
  const tidRef = useRef<string>();

  function restoreStatus(s: any) {
    setRec(s.recommendation);
    setCards((cards) => {
      const next = { ...cards };
      for (const h of s.headers ?? []) if (!next[h.agent_id]) next[h.agent_id] = { ...h, status: "calling" };
      for (const r of s.results ?? []) next[r.agent_id] = { ...next[r.agent_id], ...r, live: r.source === "live",
        status: s.twin?.hospital === r.hospital ? "accepted" : s.twin && r.status === "available" ? "released" : r.status,
        last_line: r.error ?? r.transcript?.at(-1)?.text };
      return next;
    });
    if (s.twin) {
      setTwin(s.twin); setBridgeMode(s.bridge?.mode); setBridgeStatus(s.bridge?.status);
      const restoredAt = Date.now();
      setStartedAt(restoredAt - s.elapsed_s * 1000); setStoppedAt(restoredAt);
    }
  }

  useEffect(() => {
    // Every visit and every refresh starts a fresh dashboard. Older links carried ?transfer=…; drop it.
    if (new URLSearchParams(window.location.search).has("transfer")) window.history.replaceState(null, "", window.location.pathname);
    // Back from another page reopens this tab's search from the server.
    const saved = searchToReopen();
    if (!saved) return;
    getStatus(saved).then((s) => {
      if (tidRef.current) return;   // a new search started meanwhile
      tidRef.current = saved; setTid(saved);
      if (s.case?.specialty) setSpecialty(s.case.specialty);
      if (s.case?.window_min) setWindowMin(s.case.window_min);
      if (!s.twin) setStartedAt(Date.now() - s.elapsed_s * 1000);
      restoreStatus(s);
    }).catch((e) => { if (e instanceof SearchGone) { setEnded(true); setStoppedAt(Date.now()); } });
  }, []);

  useEffect(() => {
    getCenters().then((d) => {
      setSending(d.sending);
      setNames(Object.fromEntries(d.centers.map((c: any) => [c.id, c.short_name ?? c.name])));
      setWindows(Object.fromEntries(Object.entries(d.demo_cases).map(([k, v]: [string, any]) => [k, d.windows[v.window]])));
    }).catch(() => setError("The demo backend is unavailable. Please try again shortly."));
    // Nothing starts until the backend has answered, so the phone popup is never skipped.
    const wake = (tries: number) => getHealth()
      .then((h) => { setLiveCalls(h?.integrations?.twilio === "live"); setVisitorCalls(!!h?.visitor_calls); setCallerId(h?.demo_caller_id ?? undefined); setAwake(true); })
      .catch(() => (tries > 0 ? setTimeout(() => wake(tries - 1), 3000) : setAwake(true)));
    wake(20);
  }, []);
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 250); return () => clearInterval(t); }, []);

  useEffect(() => {
    if (!WS) return; // Hosted demo uses the existing status polling instead.
    const ws = new WebSocket(WS);
    ws.onmessage = (m) => {
      const e = JSON.parse(m.data);
      if (e.transfer_id !== tidRef.current) return;
      if (e.kind === "result") setCards((c) => ({ ...c, [e.agent_id]: { ...c[e.agent_id], ...e, live: e.source === "live", last_line: e.error ?? e.transcript?.at(-1)?.text } }));
      if (e.kind === "transfer") {
        const set = (hid: string, status: string) => setCards((c) => Object.fromEntries(Object.entries(c).map(([k, v]) => [k, v.hospital_id === hid ? { ...v, status } : v])));
        if (e.type === "held" || e.type === "accepted") set(e.hospital_id, e.type);
        if (e.type === "released") set(e.hospital_id, "released");
        if (e.type === "twin_ready") setTwin(e.data);
      }
    };
    return () => ws.close();
  }, []);

  useEffect(() => {
    if (!tid) return;
    const t = setInterval(async () => {
      try { restoreStatus(await getStatus(tid)); }
      catch (e) {
        if (!(e instanceof SearchGone)) return;   // network blips: keep polling
        clearInterval(t); setEnded(true); setStoppedAt((s) => s ?? Date.now());
      }
    }, 1000);
    return () => clearInterval(t);
  }, [tid]);

  // The QR opens the transfer ticket on a phone; older backends without a ticket get the handoff record link instead.
  useEffect(() => {
    if (!twin) return setQr(undefined);
    let live = true;
    const text = twin.ticket?.url ?? twin.shlink;
    QRCode.toDataURL(text, { margin: 1, width: 224, errorCorrectionLevel: twin.ticket ? "M" : "L", color: { dark: "#0A0B0D", light: "#FFFFFF" } })
      .then((u) => { if (live) setQr(u); }).catch(() => { if (live) setQr(undefined); });
    return () => { live = false; };
  }, [twin]);

  async function onStart(withPhone?: string) {
    setAskCall(false);
    if (starting) return;
    setStarting(true);
    setError(undefined); setBridgeMode(undefined); setBridgeStatus(undefined); setTwin(undefined); setRec(undefined); setStoppedAt(undefined);
    setCallNote(undefined); setDoctorPopup(true); setEnded(false);
    try {
      const r = await startTransfer(specialty, windowMin, withPhone?.trim() || undefined);   // untouched slider = the case default window
      if (r.visitor_call_problem) setCallNote({
        limit: "Today's demo calls are used up, so every hospital is simulated this time.",
        unavailable: "Live demo calls are limited to approved numbers right now, so every hospital is simulated this time.",
        invalid: "That doesn't look like a US phone number, so every hospital is simulated this time.",
      }[r.visitor_call_problem]);
      tidRef.current = r.transfer_id; setTid(r.transfer_id); setStartedAt(Date.now()); rememberSearch(r.transfer_id);
      setCards(Object.fromEntries(r.agents.map((a) => [a.agent_id, { ...a, live: a.live && liveCalls, status: "calling" }])));   // no LIVE tag in a simulated run
    } catch { setError("Could not start the search. Check that the services are running."); }
    finally { setStarting(false); }
  }
  async function onAccept() {
    if (!tid) return;
    setBusy(true);
    try {
      const r = await accept(tid, rec?.hospital_id);
      setBridgeMode(r.bridge?.mode); setBridgeStatus(r.bridge?.status);
      setStoppedAt(Date.now());
      if (r?.twin && tidRef.current === tid) setTwin(r.twin);   // same twin as the websocket twin_ready event, in case that is missed
    } catch (e: any) {
      if (e instanceof SearchGone) { setEnded(true); setStoppedAt((s) => s ?? Date.now()); }
      else setError("Could not connect the doctors. Please try again.");
    }
    setBusy(false);
  }

  const list = useMemo(() => Object.values(cards), [cards]);
  const n = list.length;
  const count = (...s: string[]) => list.filter((c) => s.includes(c.status)).length;
  const calling = count("calling"), callback = count("callback_requested"), yes = count("available", "held", "accepted", "released"), no = count("declined"), none = count("no_answer");
  const searching = n > 0 && !twin && calling > 0 && !ended;
  const finished = n > 0 && calling === 0 && callback === 0;   // every hospital has given its final answer
  const elapsed = startedAt ? Math.floor(((stoppedAt ?? now) - startedAt) / 1000) : 0;
  const perCall = 90;
  const fmt = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  const w0 = windows[specialty];
  const w = w0 && windowMin ? { ...w0, transport_budget_min: windowMin, hard_max_min: windowMin } : w0;
  const caseInfo = CASES.find((c) => c.key === specialty)!;
  const patientLabel = specialty === "trauma_pediatric" ? "8-year-old boy" : specialty === "childbirth" ? "28-year-old woman" : "62-year-old man";
  const accepted = list.find((c) => c.status === "accepted");
  const acceptedName = accepted?.hospital ?? twin?.hospital;   // a twin only exists once a hospital accepted
  const released = count("released");
  const ticket = twin?.ticket;
  // Delivery is a presentation-only mock until a receiving-system integration exists.
  const visitorCard = visitorCalls ? list.find((c) => c.live) : undefined;   // the first hospital, answered by the visitor
  const demoInfoSent = !!twin && (bridgeStatus === "ended" || (bridgeMode === "mock" && bridgeStatus === "simulated"));

  return (
    <div className="grid min-h-full grid-cols-[minmax(0,1fr)] grid-rows-[auto_minmax(340px,1fr)_auto] overflow-x-hidden">
      {/* Top bar */}
      <header className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-b border-ink-line px-5 py-3">
        <div className="flex min-w-0 items-baseline gap-3">
          <span className="whitespace-nowrap text-[18px] font-semibold tracking-[-0.025em]">Project Uzima</span>
          <span className="truncate text-sm text-ink-muted">{sending?.name ?? "…"}, Indianola, MS</span>
        </div>
        <div className="flex max-w-full flex-wrap items-center gap-2.5">
          <label className="relative">
            <span className="sr-only">Case</span>
            <select value={specialty} disabled={searching} onChange={(e) => { setSpecialty(e.target.value); setWindowMin(undefined); }}
              className="appearance-none rounded-full border border-ink-line bg-ink-panel py-1.5 pl-3.5 pr-9 text-sm font-medium text-ink-text shadow-xs outline-none focus-visible:ring-2 focus-visible:ring-gold disabled:cursor-not-allowed disabled:opacity-60">
              {CASES.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
            </select>
            <svg aria-hidden viewBox="0 0 12 12" className="pointer-events-none absolute right-3 top-1/2 h-3 w-3 -translate-y-1/2 text-ink-muted"><path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
          </label>
          <label className="flex items-center gap-2 whitespace-nowrap text-sm text-ink-muted">
            Care within
            <input type="range" min={10} max={120} step={5} disabled={searching}
              value={windowMin ?? windows[specialty]?.transport_budget_min ?? 60}
              onChange={(e) => setWindowMin(Number(e.target.value))} className="w-28 accent-[#F0C06A]" />
            <b className="tabular font-medium text-ink-text">{windowMin ?? windows[specialty]?.transport_budget_min ?? 60} min</b>
          </label>
          <button onClick={() => (visitorCalls ? setAskCall(true) : onStart())} disabled={!awake || searching || starting} className="btn-primary"
            title={awake ? undefined : "The demo server is starting; this takes up to 30 seconds after a quiet period."}>
            {!awake ? "Waking up…" : starting ? "Starting…" : searching ? "Searching…" : twin ? "New search" : "Find a bed"}
          </button>
        </div>
      </header>

      {askCall && <CallMePopup callerId={callerId} phone={phone} setPhone={setPhone}
        onCall={() => onStart(phone)} onSkip={() => onStart()} onCancel={() => setAskCall(false)} />}

      {/* Map */}
      <section className="relative min-h-[380px]">
        <MapView sending={sending} cards={list} names={names} focusKey={tid} searching={searching} />
        <div className="pointer-events-none absolute inset-x-3 top-3 flex flex-col items-start gap-2 lg:flex-row lg:justify-between">
        <div data-map-overlay className="min-w-0 max-w-full rounded-xl border border-ink-line bg-ink-panel px-3.5 py-2.5 shadow-xs lg:max-w-[440px]">
          <div className="flex min-w-0 items-center gap-2 text-sm">
            <span className="h-2 w-2 shrink-0 rounded-full bg-fill-no" />
            <span className="shrink-0 font-semibold">{caseInfo.label}</span>
            <span className="truncate text-ink-muted">· {caseInfo.detail}</span>
          </div>
          <div className="mt-1 text-xs text-ink-muted">
            {w && <>Care within <b className="font-medium text-ink-text">{w.transport_budget_min} min</b>{w.hard_max_min !== w.transport_budget_min && ` (max ${w.hard_max_min})`} · </>}
            {patientLabel}{tid && <> · <span className="font-mono text-[11px]">{tid}</span></>}
          </div>
        </div>
        <div data-map-overlay className="shrink-0 rounded-xl border border-ink-line bg-ink-panel px-4 py-3 shadow-xs">
          <div className="flex items-end gap-7">
            <div title={`Estimate at about ${perCall} seconds per call`}>
              <div className="eyebrow">Calling one by one</div>
              <div className="mt-1.5 text-[30px] font-light leading-none tracking-tight tabular text-ink-muted">{n ? fmt(n * perCall) : "—"}</div>
            </div>
            <div>
              <div className="eyebrow">Project Uzima</div>
              <div className={`mt-1.5 text-[30px] font-normal leading-none tracking-tight tabular ${twin ? "text-st-yes" : "text-gold-text"}`}>
                {fmt(elapsed)}{twin && <span className="ml-1.5 font-serif text-[17px] italic">placed</span>}
              </div>
            </div>
          </div>
          <div className="mt-3 border-t border-ink-line pt-2">
            <div className="eyebrow">Responses{n ? ` · ${n - calling} of ${n}` : ""}</div>
            <div className="mt-1 grid grid-cols-2 gap-x-5 gap-y-0.5 text-sm font-medium tabular">
              <Count dot="bg-fill-yes" className="text-st-yes">{yes} available</Count>
              <Count dot="bg-fill-no" className="text-st-no">{no} declined</Count>
              <Count dot="bg-fill-none" className="text-st-none">{none} no answer</Count>
              <Count dot="bg-fill-calling" className="text-st-calling">{calling} pending</Count>
              {callback > 0 && <Count dot="bg-fill-calling" className="text-st-calling">{callback} call back</Count>}
            </div>
          </div>
        </div>
        </div>
        {/* Popups: the visitor's own call, then the two doctor calls after Connect. */}
        <div className="pointer-events-none absolute bottom-[5.5rem] right-3 flex w-[min(21rem,calc(100%-1.5rem))] flex-col items-stretch gap-2 md:bottom-10 md:right-14">
          {callNote && <Popup title="Simulated search" onClose={() => setCallNote(undefined)}><p>{callNote}</p></Popup>}
          {visitorCard && !twin && !ended && <VisitorCall card={visitorCard} canConnect={!!rec} />}
          {twin && doctorPopup && bridgeStatus && <DoctorCall status={bridgeStatus} simulated={bridgeMode !== "live"} ticket={twin.ticket}
            desk={list.find((c) => c.status === "accepted")} onClose={() => setDoctorPopup(false)} />}
        </div>
      </section>

      {/* Decision bar. With a ticket, the ticket gets the wider column. */}
      <footer className={`grid grid-cols-1 gap-px border-t border-ink-line bg-ink-line ${ticket
        ? "lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)] xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]" : "lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]"}`}>
        <div className="bg-ink-bg px-5 py-3">
          {error ? <div className="text-sm text-st-no">{error}</div>
            : acceptedName ? (
              <div>
                <div className="eyebrow flex items-center gap-1.5 text-st-yes"><span className="h-1.5 w-1.5 rounded-full bg-fill-yes" />Transfer accepted</div>
                <div className="mt-0.5 text-base font-semibold">{acceptedName}</div>
                <div className="text-sm text-ink-muted">
                  {bridgeMode === "live" ? (bridgeLabel[bridgeStatus ?? ""] ?? "Doctor connection requested; waiting for the phones to join") : "Doctor calls are simulated in this demo"}{ticket ? ", transfer ticket created" : ""}
                  {released ? `, ${released} other ${released === 1 ? "hospital" : "hospitals"} released` : ""}.
                </div>
                {twin && (
                  <section aria-label="Patient information delivery" aria-live="polite"
                    className={`mt-3 rounded-xl border px-3.5 py-3 ${demoInfoSent ? "border-st-yes/25 bg-st-yes/5" : "border-ink-line bg-ink-panel"}`}>
                    <div className="flex items-start gap-2.5">
                      <svg aria-hidden="true" viewBox="0 0 20 20" fill="none"
                        className={`mt-0.5 h-5 w-5 shrink-0 ${demoInfoSent ? "text-st-yes" : "text-ink-muted"}`}>
                        {demoInfoSent ? <><circle cx="10" cy="10" r="8" stroke="currentColor" strokeWidth="1.5" /><path d="m6 10 2.5 2.5L14 7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></>
                          : <><path d="M5 2.5h6L15 7v10.5H5zM11 2.5V7h4M7.5 10h5M7.5 13h5" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" /></>}
                      </svg>
                      <div className="min-w-0">
                        <h2 className="text-sm font-semibold">{demoInfoSent ? "Patient information sent" : "Patient information ready"}</h2>
                        <div className="mt-1 inline-flex rounded-full border border-ink-line bg-ink-bg px-2 py-0.5 text-[10px] font-medium text-ink-muted">Demo · simulated delivery</div>
                        <p className="mt-2 text-xs text-ink-muted">To: <span className="font-medium text-ink-text">{twin.hospital}</span></p>
                        <p className="mt-1 text-xs leading-relaxed text-ink-muted">Patient summary, vitals, medications, allergies and transfer details.</p>
                        <p className="mt-1.5 text-xs leading-relaxed text-ink-muted">
                          {demoInfoSent ? "Delivery is simulated for this demo. Open the transfer ticket to access the full record."
                            : bridgeStatus === "failed" ? "Delivery is paused because the doctor connection failed. The record is available in the transfer ticket."
                            : "Simulated delivery will be shown after the doctor call ends. The record is available in the transfer ticket."}
                        </p>
                      </div>
                    </div>
                  </section>
                )}
              </div>
            ) : ended ? (
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="text-sm text-ink-muted"><b className="font-semibold text-ink-text">This search has ended.</b> The demo server was restarted, so its results are gone. Please start a new search.</div>
                <button onClick={() => (visitorCalls ? setAskCall(true) : onStart())} disabled={starting} className="btn-primary">Start a new search</button>
              </div>
            ) : rec ? (
              <div className="win flex flex-wrap items-center justify-between gap-x-6 gap-y-3 rounded-xl px-4 py-3">
                <div className="min-w-0">
                  <div className="eyebrow text-gold-text">Recommended · {rec.source === "live" ? "confirmed by phone" : "simulated answer"}</div>
                  <div className="mt-0.5 text-base font-semibold">{rec.hospital}</div>
                  <div className="mt-0.5 flex flex-wrap gap-x-5 text-sm tabular text-ink-muted">
                    <span>Treatment in <b className="font-semibold text-ink-text">~{rec.treatment_start_min} min</b></span>
                    <span>{rec.transport.recommended_mode === "air" ? "Air" : "Ground"} <b className="font-semibold text-ink-text">{rec.transport.recommended_mode === "air" ? rec.transport.est_air_min : rec.transport.est_ground_min} min</b></span>
                    <span>Ready in <b className="font-semibold text-ink-text">{rec.ready_in_min} min</b></span>
                  </div>
                </div>
                <div className="flex flex-col items-start sm:items-end">
                  <button onClick={onAccept} disabled={busy} className="btn-primary">
                    {busy ? "Connecting…" : "Connect doctors"}
                  </button>
                  <span className="mt-1 text-xs text-ink-muted">The agent reads the summary to them, then you are connected</span>
                </div>
              </div>
            ) : (
              <div className="text-sm text-ink-muted">{!n && !awake ? "Waking up the demo server. This takes up to 30 seconds after a quiet period."
                : !n ? "Choose the condition and press Find a bed. Every hospital that can treat it within the time window is called at once."
                : finished ? "No hospital confirmed a bed this time. Press Find a bed to search again, or widen the time window."
                : "Waiting for the first hospital to say yes…"}</div>
            )}
        </div>
        <div className="bg-ink-bg px-5 py-3">
          {ticket ? <TicketCard t={ticket} qr={qr} />
            : twin ? (
              <div className="flex items-center gap-4">
                {qr && <img src={qr} alt="QR code for the handoff record" className="h-[76px] w-[76px] rounded-sm" />}
                <div className="min-w-0 text-sm">
                  <div className="text-xs text-ink-muted">Handoff record for {twin.hospital}</div>
                  <div className="text-ink-faint">Scan to open · expires in 24 h</div>
                  <div className="truncate text-xs text-ink-faint">Insurance check: {twin.insurance?.payer}</div>
                </div>
              </div>
            ) : (
              <div className="text-sm text-ink-muted">After Connect, the agent reads the summary on the call and a transfer ticket is created for the patient. An encrypted record (case, every call, insurance check) is kept for the receiving team.</div>
            )}
        </div>
      </footer>
    </div>
  );
}

/** "+16623002188" -> "+1 (662) 300-2188" */
function prettyPhone(e164?: string) {
  const m = e164?.match(/^\+1(\d{3})(\d{3})(\d{4})$/);
  return m ? `+1 (${m[1]}) ${m[2]}-${m[3]}` : e164 ?? "our demo number";
}

/** Before a search in the public demo: the visitor can play the first hospital's transfer desk on a real call. */
function CallMePopup({ callerId, phone, setPhone, onCall, onSkip, onCancel }: {
  callerId?: string; phone: string; setPhone: (v: string) => void; onCall: () => void; onSkip: () => void; onCancel: () => void }) {
  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onCancel(); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onCancel]);
  const ready = phone.replace(/\D/g, "").length >= 10;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-text/30 px-4" onClick={onCancel}>
      <section role="dialog" aria-modal="true" aria-labelledby="callme-title" onClick={(e) => e.stopPropagation()}
        className="w-full max-w-[30rem] rounded-2xl border border-ink-line bg-ink-panel p-5 shadow-lg">
        <div className="flex items-start gap-3">
          <h2 id="callme-title" className="text-lg font-semibold tracking-[-0.01em]">Take the first call yourself</h2>
          <button onClick={onCancel} aria-label="Close" className="-mr-1 ml-auto rounded px-1.5 text-xl leading-none text-ink-muted hover:text-ink-text">×</button>
        </div>
        <p className="mt-2 text-sm leading-relaxed text-ink-muted">
          Uzima is about to call every capable hospital at once. In this demo the first hospital's call comes to <b className="font-medium text-ink-text">your phone</b>: you play its transfer desk, the way a real hospital gets the call. No app, no login, just the phone. The other hospitals are simulated.
        </p>
        <ol className="mt-3 space-y-1.5 text-sm text-ink-text">
          <li><span className="text-ink-muted">1.</span> Your phone rings from <b className="font-medium">{prettyPhone(callerId)}</b>.</li>
          <li><span className="text-ink-muted">2.</span> The AI agent says it's an AI, describes the patient and asks if you have a bed. Say <b>yes</b> or <b>no</b>.</li>
          <li><span className="text-ink-muted">3.</span> If yes, say how many minutes until you're ready, for example <b>"ten"</b>.</li>
          <li><span className="text-ink-muted">4.</span> It reads your answer back. Say <b>yes</b> to confirm, and it thanks you and hangs up.</li>
        </ol>
        <label className="mt-4 block text-sm font-medium" htmlFor="callme-phone">Your phone number (US)</label>
        <input id="callme-phone" type="tel" inputMode="tel" autoComplete="tel" autoFocus value={phone} maxLength={20}
          onChange={(e) => setPhone(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && ready) onCall(); }}
          placeholder="(555) 123-4567"
          className="mt-1.5 w-full rounded-lg border border-ink-line bg-ink-bg px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-gold" />
        <div className="mt-2.5 flex gap-2 rounded-lg border border-ink-line bg-ink-bg px-3 py-2 text-xs leading-relaxed text-ink-muted">
          <svg aria-hidden viewBox="0 0 16 16" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ink-text"><path d="M4.5 7V5a3.5 3.5 0 0 1 7 0v2M3.5 7h9v6.5h-9z" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" /></svg>
          <p><b className="font-semibold text-ink-text">We don't save your number.</b> It's used only to place this one demo call, kept in memory while the call runs, and never stored or shown anywhere. Our phone carrier keeps its usual call record.</p>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button onClick={onCall} disabled={!ready} className="btn-primary">Call me and start</button>
          <button onClick={onSkip} className="rounded-full border border-ink-line px-3.5 py-1.5 text-sm font-medium text-ink-text hover:bg-ink-bg">Start without a call</button>
          <button onClick={onCancel} className="ml-auto text-sm text-ink-muted hover:text-ink-text">Cancel</button>
        </div>
      </section>
    </div>
  );
}

/** A floating card over the map. */
function Popup({ title, tone, tag, onClose, children }: { title: string; tone?: "yes" | "no"; tag?: string; onClose?: () => void; children: React.ReactNode }) {
  // Drag anywhere on the map by any spot that isn't a button or link; it stays inside the map.
  const ref = useRef<HTMLElement>(null);
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const [side, setSide] = useState<"left" | "right">("left");   // which side a row's note opens on (md and up)
  const drag = useRef<{ x: number; y: number; px: number; py: number; id: number }>();
  const onDown = (e: React.PointerEvent<HTMLElement>) => {
    if (e.button !== 0 || (e.target as HTMLElement).closest("button, a, input, [role=note]")) return;
    drag.current = { x: e.clientX, y: e.clientY, px: pos.x, py: pos.y, id: e.pointerId };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onMove = (e: React.PointerEvent<HTMLElement>) => {
    const d = drag.current, el = ref.current, area = el?.parentElement?.parentElement;
    if (!d || d.id !== e.pointerId || !el || !area) return;
    const r = el.getBoundingClientRect(), m = area.getBoundingClientRect(), pad = 8;
    const baseLeft = r.left - pos.x, baseTop = r.top - pos.y;   // where it sits without the drag offset
    const x = Math.min(Math.max(d.px + e.clientX - d.x, m.left + pad - baseLeft), m.right - pad - r.width - baseLeft);
    const y = Math.min(Math.max(d.py + e.clientY - d.y, m.top + pad - baseTop), m.bottom - pad - r.height - baseTop);
    setPos({ x, y });
    setSide(baseLeft + x - m.left < 320 ? "right" : "left");
  };
  const onUp = (e: React.PointerEvent<HTMLElement>) => { if (drag.current?.id === e.pointerId) drag.current = undefined; };
  return (
    <section ref={ref} data-map-overlay data-side={side} aria-label={title} aria-live="polite"
      onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}
      style={{ transform: `translate(${pos.x}px, ${pos.y}px)`, touchAction: "none" }}
      className="group pointer-events-auto relative cursor-grab select-none rounded-xl border border-ink-line bg-ink-panel px-3.5 py-3 text-xs text-ink-muted shadow-md active:cursor-grabbing">
      <div className="flex items-start gap-2">
        <span aria-hidden title="Drag to move" className="-ml-1 mt-0.5 select-none text-[11px] leading-none tracking-[-2px] text-ink-muted/70">⋮⋮</span>
        <h2 className={`text-sm font-semibold ${tone === "yes" ? "text-st-yes" : tone === "no" ? "text-st-no" : "text-ink-text"}`}>{title}</h2>
        {onClose && <button onClick={onClose} aria-label="Close" className="-mr-1 -mt-0.5 ml-auto rounded px-1 text-base leading-none text-ink-muted hover:text-ink-text">×</button>}
      </div>
      {tag && <span className="mt-1 inline-flex rounded-full border border-ink-line bg-ink-bg px-2 py-0.5 text-[10px] font-medium text-ink-muted">{tag}</span>}
      <div className="mt-1.5 leading-relaxed">{children}</div>
    </section>
  );
}

/** The first hospital call, answered on the visitor's own phone. */
function VisitorCall({ card, canConnect }: { card: Card; canConnect: boolean }) {
  const s = card.status;
  if (card.error || s === "no_answer")
    return <Popup title="Your phone wasn't reached" tone="no"><p>No answer was recorded for {card.hospital}, so the search continues with the other hospitals.</p></Popup>;
  if (s === "calling")
    return <Popup title="Your phone is ringing" tag="Live call"><p>You're the transfer desk at <b className="font-medium text-ink-text">{card.hospital}</b>. Answer, say yes or no, and confirm when the agent reads your answer back.</p></Popup>;
  if (s === "declined")
    return <Popup title="You said no" tag="Confirmed by phone"><p>{card.hospital}: {card.decline_reason ?? "no bed"}. {canConnect
      ? "Another hospital confirmed a bed: press Connect doctors below to see the doctor calls."
      : "The other hospitals are still answering."}</p></Popup>;
  if (s === "callback_requested")
    return <Popup title="You asked for a call back" tag="Live call"><p>{card.hospital} is counted as pending.</p></Popup>;
  return <Popup title="You said yes" tone="yes" tag="Confirmed by phone"><p>{card.hospital} can take the patient, ready in {card.ready_in_min ?? "?"} min. The agent thanked you and ended the call.{canConnect
      ? " Press Connect doctors below to see the doctor calls." : " The recommendation appears below in a moment."}</p></Popup>;
}

/** The calls behind a transfer, after Connect: the hospital's transfer desk (already done), then the accepting doctor
 *  hears the summary and the referring doctor joins. Each row opens a short note on what that call is and says. */
function DoctorCall({ status, simulated, ticket, desk, onClose }: {
  status?: string; simulated: boolean; ticket?: Ticket; desk?: Card; onClose: () => void }) {
  const [open, setOpen] = useState<string>();
  const steps = ["calling_accepting_doctor", "calling_sending_doctor", "connected", "ended"];
  const step = status === "initiated" ? 0 : steps.indexOf(status ?? "");
  if (step < 0 && status !== "failed") return null;
  const failed = status === "failed";
  const title = failed ? "Doctor connection failed" : step === 3 ? "Doctor call ended" : step === 2 ? "Doctors connected · one call" : "Connecting doctors";
  const receiving = ticket?.to.name ?? desk?.hospital ?? "the receiving hospital";
  const sending = ticket?.from.name ?? "the sending hospital";
  const ready = ticket?.ready_in_min ?? desk?.ready_in_min;
  const byVisitor = desk?.source === "live";
  const travel = ticket ? ` Arriving by ${ticket.mode} in about ${ticket.travel_min} minutes.` : "";
  const rows: { who: string; what: string; state: "wait" | "ring" | "done"; about: React.ReactNode }[] = [
    { who: "Transfer desk", state: "done",
      what: `${byVisitor ? "You said yes" : "Said yes"}${ready != null ? ` · ready in ${ready} min` : ""}`,
      about: <>The first call. The AI agent phones the transfer desk at <b className="font-medium text-ink-text">{receiving}</b>, says it is an AI, and asks: <i>“{desk?.capability_question ?? "Do you have a bed and a team available right now?"}”</i> If yes, it asks how many minutes until they're ready, reads the answer back, and counts it only after the desk says yes. {byVisitor ? "You answered this call." : "In this run the desk's answer is simulated."}</> },
    { who: "Accepting doctor", state: step === 0 ? "ring" : "done",
      what: step === 0 ? "Ringing · hears the referral summary first" : step === 3 ? "Call ended" : "Heard the summary",
      about: <>The doctor at <b className="font-medium text-ink-text">{receiving}</b> who takes over the patient's care. The agent calls them first and reads the referral summary: <i>“This is the Uzima assistant with the referral summary. {ticket ? `${ticket.patient}, ${ticket.condition}.` : "The patient's age and condition."}{travel} The transfer ticket with the full record travels with the patient.”</i> Then it connects them to the referring doctor.</> },
    { who: "Referring doctor", state: step < 1 ? "wait" : step === 1 ? "ring" : "done",
      what: step < 1 ? "Joins after the summary" : step === 1 ? "Ringing" : step === 3 ? "Call ended" : "Joined the call",
      about: <>The doctor at <b className="font-medium text-ink-text">{sending}</b> who is sending the patient. Their phone rings after the summary, and both doctors talk on one call to hand the patient over directly. Nobody at either hospital has to open an app or a link.</> },
  ];
  const dot = { wait: "bg-fill-none", ring: "bg-fill-calling animate-pulse", done: "bg-fill-yes" };
  return (
    <Popup title={title} tone={failed ? "no" : step >= 2 ? "yes" : undefined} tag={simulated ? "Demo · simulated call" : "Live call"} onClose={onClose}>
      {!failed && (
        <>
          <ul className="space-y-0.5">
            {rows.map(({ who, what, state, about }) => (
              <li key={who}>
                <button onClick={() => setOpen(open === who ? undefined : who)} aria-expanded={open === who}
                  className="-mx-1.5 flex w-[calc(100%+0.75rem)] items-center gap-2 rounded-md px-1.5 py-1 text-left hover:bg-ink-bg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold">
                  <span aria-hidden className={`h-1.5 w-1.5 shrink-0 rounded-full ${dot[state]}`} />
                  <span className="font-medium text-ink-text underline decoration-ink-line decoration-dotted underline-offset-2">{who}</span>
                  <span className="truncate">{what}</span>
                  <span aria-hidden className={`ml-auto shrink-0 text-[10px] transition-transform ${open === who ? "rotate-90" : ""}`}>›</span>
                </button>
                {open === who && (
                  <div role="note" className="mb-1 ml-3.5 mt-0.5 rounded-lg border border-ink-line bg-ink-bg px-2.5 py-2 text-[11px] leading-relaxed text-ink-muted
                    md:absolute md:bottom-0 md:right-full md:z-10 md:mb-0 md:ml-0 md:mr-3 md:mt-0 md:w-72
                    md:group-data-[side=right]:left-full md:group-data-[side=right]:right-auto md:group-data-[side=right]:ml-3 md:group-data-[side=right]:mr-0 select-text cursor-auto md:bg-ink-panel md:px-3 md:py-2.5 md:text-xs md:shadow-md">
                    <div className="mb-1 font-semibold text-ink-text md:text-sm">{who}</div>{about}
                  </div>
                )}
              </li>
            ))}
          </ul>
          <p className="mt-1.5 text-[10px] text-ink-muted">Tap a call to see what it is and what it says.</p>
        </>
      )}
    </Popup>
  );
}

function Count({ dot, className, children }: { dot: string; className: string; children: React.ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap ${className}`}>
      <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${dot}`} />{children}
    </span>
  );
}

function Field({ k, v, sub }: { k: string; v: string; sub?: string }) {
  return (
    <div className="min-w-0">
      <dt className="eyebrow">{k}</dt>
      <dd className="truncate text-[13px] font-medium leading-5 text-ink-text" title={v}>{v}</dd>
      {sub && <dd className="truncate text-xs leading-4 text-ink-muted" title={sub}>{sub}</dd>}
    </div>
  );
}

/** The transfer ticket, laid out like a boarding pass: route and details on the left, a perforated stub with the QR on the right.
 *  Its QR code opens the encrypted record; there is no passcode. */
function TicketCard({ t, qr }: { t: Ticket; qr?: string }) {
  const mode = t.mode === "air" ? "Air" : "Ground";
  const insurance = t.insurance || "—";
  const cut = insurance.search(/ \(| · /);   // "Mississippi Medicaid (offline mock) · active" -> payer, then the rest underneath
  const city = "truncate text-base font-semibold leading-6 tracking-[-0.01em] sm:text-lg sm:leading-7 xl:text-[22px]";
  return (
    <article aria-label={`Transfer ticket ${t.code}`} className="flex flex-col overflow-hidden rounded-xl border border-ink-line bg-ink-panel shadow-xs sm:flex-row">
      <div className="min-w-0 flex-1 px-4 pb-3 pt-2.5">
        <div className="flex items-center justify-between gap-3">
          <span className="eyebrow flex items-center gap-1.5 text-gold-text"><span aria-hidden className="h-1.5 w-1.5 rounded-full bg-gold" />Ticket created</span>
          <span className="font-mono text-[13px] font-medium tracking-[.06em] text-ink-text">{t.code}</span>
        </div>

        <div className="mt-1.5 grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-x-3">
          <div className={city} title={t.from?.city}>{t.from?.city}</div>
          <div aria-hidden className="flex h-[9px] w-10 items-center text-ink-faint sm:w-16 xl:w-24">
            <span className="h-[5px] w-[5px] shrink-0 rounded-full border border-current" />
            <span className="h-px flex-1 bg-current" />
            <svg viewBox="0 0 6 9" className="h-[9px] w-[6px] shrink-0"><path d="M0 4.5h5.4M2.2 1.5l3.2 3-3.2 3" fill="none" stroke="currentColor" strokeWidth="1" /></svg>
          </div>
          <div className={`${city} text-right`} title={t.to?.city}>{t.to?.city}</div>
          <div className="truncate text-xs text-ink-muted" title={t.from?.name}>{t.from?.name}</div>
          <div />
          <div className="truncate text-right text-xs text-ink-muted" title={t.to?.name}>{t.to?.name}</div>
        </div>

        <dl className="mt-2.5 grid grid-cols-2 gap-x-3 gap-y-2 border-t border-ink-line pt-2 sm:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.3fr)]">
          <Field k="Patient" v={t.patient} sub={t.condition} />
          <Field k="Arrives" v={clock(t.eta)} sub={`${mode} · ${t.travel_min} min`} />
          <Field k="Team ready" v={t.ready_in_min != null ? `in ${t.ready_in_min} min` : "—"}
            sub={t.treatment_in_min != null ? `treatment ~${t.treatment_in_min} min` : undefined} />
          <Field k="Insurance" v={cut > 0 ? insurance.slice(0, cut) : insurance} sub={cut > 0 ? insurance.slice(cut + 1) : undefined} />
        </dl>

        <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-2">
          <a href={t.url} target="_blank" rel="noreferrer" className="btn-primary px-3.5 py-1 text-[13px]">Open ticket</a>
          {t.wallet_url && <a href={t.wallet_url} target="_blank" rel="noreferrer" className="btn-secondary px-3.5 py-1 text-[13px]">Add to Apple Wallet</a>}
        </div>
      </div>

      <div className="flex items-center gap-3 border-t border-dashed border-ink-line px-4 py-3 sm:w-[136px] sm:shrink-0 sm:flex-col sm:justify-center sm:gap-2 sm:border-l sm:border-t-0">
        {qr ? <img src={qr} alt={`QR code that opens ticket ${t.code}`} className="h-[104px] w-[104px] shrink-0" />
          : <div className="h-[104px] w-[104px] shrink-0 rounded bg-ink-raised" />}
        <div className="text-[11px] leading-4 text-ink-muted sm:text-center">Scan to open the ticket on a phone</div>
      </div>
    </article>
  );
}
