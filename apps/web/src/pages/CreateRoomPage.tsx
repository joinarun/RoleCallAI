import { FormEvent, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, ArrowRight, Brain, CalendarClock, Check, Gamepad2, Link2, ListChecks, LockKeyhole, Sparkles, Users } from "lucide-react";
import { api, jsonBody } from "../lib/api";
import type { GameType, RoleType, RoomCreated } from "../types";
import { CopyButton } from "../components/CopyButton";

type Draft = {
  name: string;
  expectedParticipants: number;
  durationMinutes: number;
  role: RoleType;
  agentName: string;
  instructions: string;
  game: GameType;
};

const roles = [
  { id: "SCRUM_MASTER" as const, icon: ListChecks, title: "Scrum Master", text: "Status round, blockers and owned next steps." },
  { id: "FUN_FRIDAY" as const, icon: Gamepad2, title: "Fun Friday", text: "A fair, fast virtual game with equal turns." },
  { id: "BRAINSTORM" as const, icon: Brain, title: "Brainstorm", text: "Diverge, cluster, prioritize and materialize ideas." },
  { id: "CUSTOM" as const, icon: Sparkles, title: "Custom", text: "Your instructions inside a safe timed framework." },
];

const defaultDraft: Draft = {
  name: "",
  expectedParticipants: 4,
  durationMinutes: 15,
  role: "SCRUM_MASTER",
  agentName: "Nova",
  instructions: "Keep updates concise. Ask one useful follow-up for blockers.",
  game: "AUTO",
};

export function CreateRoomPage() {
  const [step, setStep] = useState(1);
  const [draft, setDraft] = useState(defaultDraft);
  const [created, setCreated] = useState<RoomCreated | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const role = useMemo(() => roles.find((item) => item.id === draft.role)!, [draft.role]);

  function update<K extends keyof Draft>(key: K, value: Draft[K]) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (step < 3) {
      setStep((value) => value + 1);
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await api<RoomCreated>("/v1/rooms", {
        method: "POST",
        ...jsonBody({
          ...draft,
          game: draft.role === "FUN_FRIDAY" ? draft.game : null,
        }),
      });
      sessionStorage.setItem(`rolecall-links:${result.room.id}`, JSON.stringify(result));
      setCreated(result);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not create this room.");
    } finally {
      setBusy(false);
    }
  }

  if (created) {
    return (
      <section className="success-layout">
        <div className="success-hero"><div className="success-check"><Check /></div><p className="eyebrow mint">Room ready</p><h1>{created.room.name}</h1><p>These are the only copies of the secret links. Store the admin link safely and share each seat link with one person.</p></div>
        <div className="link-vault">
          <div className="vault-header"><div><LockKeyhole /><span>One-time link vault</span></div><span className="badge pending">Not recoverable</span></div>
          <div className="link-row admin-link"><div><small>ADMIN MANAGEMENT LINK</small><strong>Controls room settings and history</strong></div><CopyButton value={created.adminUrl} /></div>
          <div className="seat-link-grid">{created.seatUrls.map((seat, index) => <div className="seat-link" key={seat.slotId}><span className="seat-number">{String(index + 1).padStart(2, "0")}</span><div><small>PARTICIPANT SEAT</small><strong>Invite {index + 1}</strong></div><CopyButton value={seat.url} label="Copy" /></div>)}</div>
          <button className="button primary wide" onClick={() => navigate(new URL(created.adminUrl).pathname + new URL(created.adminUrl).hash)}><span>Open admin room</span><ArrowRight size={18} /></button>
        </div>
      </section>
    );
  }

  return (
    <section className="create-layout">
      <div className="hero-copy">
        <p className="eyebrow"><span /> AI-facilitated meetings</p>
        <h1>Give every meeting<br /><em>a steady voice.</em></h1>
        <p className="hero-lede">Create a private room. Invite your people. Your agent remembers the context, runs the floor and turns talk into outcomes.</p>
        <div className="trust-row"><span><LockKeyhole size={16} /> Secret links</span><span><Users size={16} /> 2–10 people</span><span><CalendarClock size={16} /> 5–60 minutes</span></div>
      </div>
      <form className="wizard-card" onSubmit={(event) => void submit(event)}>
        <div className="wizard-top"><div><p className="eyebrow coral">Create a room</p><h2>{step === 1 ? "Set the scene" : step === 2 ? "Choose the facilitator" : "Tune the brief"}</h2></div><span className="step-count">0{step} / 03</span></div>
        <div className="step-track" role="progressbar" aria-label="Room creation progress" aria-valuemin={1} aria-valuemax={3} aria-valuenow={step} aria-valuetext={`Step ${step} of 3`}>{[1, 2, 3].map((item) => <span key={item} className={item <= step ? "active" : ""} />)}</div>

        {step === 1 && <div className="form-step">
          <label>Room name<input aria-label="Room name" required maxLength={100} value={draft.name} onChange={(e) => update("name", e.target.value)} placeholder="Product sync — Thursday" /><small>Unique name for this reusable room</small></label>
          <div className="field-grid"><label>Participants<select value={draft.expectedParticipants} onChange={(e) => update("expectedParticipants", Number(e.target.value))}>{Array.from({ length: 9 }, (_, i) => i + 2).map((n) => <option key={n} value={n}>{n} people</option>)}</select></label><label>Duration<select value={draft.durationMinutes} onChange={(e) => update("durationMinutes", Number(e.target.value))}>{[5, 10, 15, 20, 30, 45, 60].map((n) => <option key={n} value={n}>{n} minutes</option>)}</select></label></div>
        </div>}

        {step === 2 && <div className="form-step role-grid" role="radiogroup" aria-label="Agent role">{roles.map((item) => <button key={item.id} type="button" role="radio" aria-checked={draft.role === item.id} className={`role-card ${draft.role === item.id ? "selected" : ""}`} onClick={() => update("role", item.id)}><span className="role-icon"><item.icon size={21} /></span><span><strong>{item.title}</strong><small>{item.text}</small></span>{draft.role === item.id && <Check className="role-check" size={17} />}</button>)}</div>}

        {step === 3 && <div className="form-step">
          <div className="brief-summary"><role.icon /><div><small>SELECTED ROLE</small><strong>{role.title}</strong></div><button type="button" onClick={() => setStep(2)}>Change</button></div>
          <label>Agent name<input required maxLength={60} value={draft.agentName} onChange={(e) => update("agentName", e.target.value)} /></label>
          {draft.role === "FUN_FRIDAY" && <label>Game<select value={draft.game} onChange={(e) => update("game", e.target.value as GameType)}><option value="AUTO">Auto — choose for the room</option><option value="RAPID_FIRE_TRIVIA">Rapid-fire trivia</option><option value="WOULD_YOU_RATHER">Would You Rather</option><option value="CATEGORIES">Categories</option></select></label>}
          <label>How should the agent run it?<textarea maxLength={8000} rows={5} value={draft.instructions} onChange={(e) => update("instructions", e.target.value)} placeholder="Tone, agenda, topic, rules or desired outcome…" /><small>This brief guides the agent in every occurrence.</small></label>
        </div>}
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="wizard-actions">{step > 1 ? <button type="button" className="button ghost" onClick={() => setStep((value) => value - 1)}><ArrowLeft size={18} /> Back</button> : <span />}<button className="button primary" disabled={busy || (step === 1 && !draft.name.trim())}>{busy ? "Creating…" : step === 3 ? <><Link2 size={18} /> Create private room</> : <>Continue <ArrowRight size={18} /></>}</button></div>
        <p className="retention-note">By creating a room, you acknowledge live Gemini processing and 90-day meeting retention.</p>
      </form>
    </section>
  );
}
