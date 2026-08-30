import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ArrowLeft, ArrowRight, Brain, CalendarClock, Check, ClipboardList, Code2, Gamepad2, GraduationCap, Lightbulb, Link2, ListChecks, LockKeyhole, Megaphone, Scale, Search, Sparkles, Users, Wrench } from "lucide-react";
import { jsonBody } from "../lib/api";
import { adminApi } from "../lib/adminSession";
import type { GameType, RoleType, RoomCreated } from "../types";
import { CopyButton } from "../components/CopyButton";
import { ROLE_PRESET_BY_ID, ROLE_PRESETS } from "../rolePresets";

type Draft = {
  name: string;
  expectedParticipants: number;
  durationMinutes: number;
  role: RoleType;
  agentName: string;
  instructions: string;
  game: GameType;
};

const roleIcons = {
  SCRUM_MASTER: ListChecks,
  FUN_FRIDAY: Gamepad2,
  BRAINSTORM: Brain,
  SPRINT_RETROSPECTIVE: Lightbulb,
  PROJECT_STATUS: ClipboardList,
  INCIDENT_RESPONSE: AlertTriangle,
  COURSE_INSTRUCTOR: GraduationCap,
  WORKSHOP_FACILITATOR: Wrench,
  TECHNICAL_INTERVIEWER: Code2,
  PRODUCT_DISCOVERY: Search,
  DECISION_MAKING: Scale,
  TOWN_HALL: Megaphone,
  CUSTOM: Sparkles,
} satisfies Record<RoleType, typeof ListChecks>;

const roles = ROLE_PRESETS.map((preset) => ({ ...preset, icon: roleIcons[preset.id] }));

const defaultDraft: Draft = {
  name: "",
  expectedParticipants: 4,
  durationMinutes: 15,
  role: "SCRUM_MASTER",
  agentName: "Nova",
  instructions: ROLE_PRESET_BY_ID.SCRUM_MASTER.prompt,
  game: "AUTO",
};

export function CreateRoomPage({
  onRoomCreated,
  onShowWorkspace,
}: {
  onRoomCreated?: (room: RoomCreated) => void;
  onShowWorkspace?: () => void;
} = {}) {
  const [step, setStep] = useState(1);
  const [draft, setDraft] = useState(defaultDraft);
  const [created, setCreated] = useState<RoomCreated | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const wizardHeadingRef = useRef<HTMLHeadingElement>(null);
  const role = useMemo(() => roles.find((item) => item.id === draft.role)!, [draft.role]);

  function update<K extends keyof Draft>(key: K, value: Draft[K]) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  function selectRole(nextRole: RoleType) {
    setDraft((current) => ({
      ...current,
      role: nextRole,
      instructions: ROLE_PRESET_BY_ID[nextRole].prompt,
    }));
  }

  useEffect(() => {
    if (step > 1) wizardHeadingRef.current?.focus();
  }, [step]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (step < 3) {
      setStep((value) => value + 1);
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await adminApi<RoomCreated>("/v1/admin/rooms", {
        method: "POST",
        ...jsonBody({
          ...draft,
          game: draft.role === "FUN_FRIDAY" ? draft.game : null,
        }),
      });
      onRoomCreated?.(result);
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
        <div className="success-hero"><div className="success-check"><Check /></div><p className="eyebrow mint">Room ready</p><h1>{created.room.name}</h1><p>Share each participant link with one person. You can securely recover or rotate these links from the admin dashboard.</p></div>
        <div className="link-vault">
          <div className="vault-header"><div><LockKeyhole /><span>Participant links</span></div><span className="badge good">KMS protected</span></div>
          <div className="seat-link-grid">{created.seatUrls.map((seat, index) => <div className="seat-link" key={seat.slotId}><span className="seat-number">{String(index + 1).padStart(2, "0")}</span><div><small>PARTICIPANT SEAT</small><strong>Invite {index + 1}</strong></div><CopyButton value={seat.url} label="Copy" /></div>)}</div>
          <div className="success-actions">{onShowWorkspace && <button className="button primary wide" onClick={onShowWorkspace}>Return to dashboard <ArrowRight size={18} /></button>}</div>
        </div>
      </section>
    );
  }

  return (
    <><section className={`create-layout ${step > 1 ? "focused" : ""}`}>
      {onShowWorkspace && <button className="workspace-back" type="button" onClick={onShowWorkspace}><ArrowLeft size={16} /> Back to workspace</button>}
      {step === 1 && <div className="hero-copy">
        <p className="eyebrow"><span /> RoleCallAI</p>
        <h1>Let AI Lead the<br /><em>Conversation Forward.</em></h1>
        <p className="hero-lede">Create a private room. Invite your people. Your agent remembers the context, runs the floor and turns talk into outcomes.</p>
        <div className="trust-row"><span><LockKeyhole size={16} /> Secret links</span><span><Users size={16} /> 2–10 people</span><span><CalendarClock size={16} /> 5–60 minutes</span></div>
      </div>}
      <form className="wizard-card" onSubmit={(event) => void submit(event)}>
        <div className="wizard-top"><div><p className="eyebrow coral">Create a room</p><h2 ref={wizardHeadingRef} tabIndex={-1}>{step === 1 ? "Set the scene" : step === 2 ? "Choose the facilitator" : "Tune the brief"}</h2></div><span className="step-count">0{step} / 03</span></div>
        <div className="step-track" role="progressbar" aria-label="Room creation progress" aria-valuemin={1} aria-valuemax={3} aria-valuenow={step} aria-valuetext={`Step ${step} of 3`}>{[1, 2, 3].map((item) => <span key={item} className={item <= step ? "active" : ""} />)}</div>

        {step === 1 && <div className="form-step">
          <label>Room name<input aria-label="Room name" required maxLength={100} value={draft.name} onChange={(e) => update("name", e.target.value)} placeholder="Product sync — Thursday" /><small>Unique name for this reusable room</small></label>
          <div className="field-grid"><label>Participants<select value={draft.expectedParticipants} onChange={(e) => update("expectedParticipants", Number(e.target.value))}>{Array.from({ length: 9 }, (_, i) => i + 2).map((n) => <option key={n} value={n}>{n} people</option>)}</select></label><label>Duration<select value={draft.durationMinutes} onChange={(e) => update("durationMinutes", Number(e.target.value))}>{[5, 10, 15, 20, 30, 45, 60].map((n) => <option key={n} value={n}>{n} minutes</option>)}</select></label></div>
        </div>}

        {step === 2 && <div className="form-step role-grid" role="radiogroup" aria-label="Agent role">{roles.map((item) => <button key={item.id} type="button" role="radio" aria-checked={draft.role === item.id} className={`role-card ${draft.role === item.id ? "selected" : ""}`} onClick={() => selectRole(item.id)}><span className="role-icon"><item.icon size={21} /></span><span><strong>{item.title}</strong><small>{item.description}</small></span>{draft.role === item.id && <Check className="role-check" size={17} />}</button>)}</div>}

        {step === 3 && <div className="form-step">
          <div className="brief-summary"><role.icon /><div><small>SELECTED ROLE</small><strong>{role.title}</strong></div><button type="button" onClick={() => setStep(2)}>Change</button></div>
          <label>Agent name<input required maxLength={60} value={draft.agentName} onChange={(e) => update("agentName", e.target.value)} /></label>
          {draft.role === "FUN_FRIDAY" && <label>Game<select aria-label="Game" value={draft.game} onChange={(e) => update("game", e.target.value as GameType)}><option value="AUTO">Auto — choose for the room</option><option value="RAPID_FIRE_TRIVIA">Rapid-fire trivia</option><option value="WOULD_YOU_RATHER">Would You Rather</option><option value="CATEGORIES">Categories</option></select></label>}
          <label>How should the agent run it?<textarea aria-label="How should the agent run it?" maxLength={8000} rows={5} value={draft.instructions} onChange={(e) => update("instructions", e.target.value)} placeholder="Tone, agenda, topic, rules or desired outcome…" /><small>This brief guides the agent in every occurrence.</small></label>
        </div>}
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="wizard-actions">{step > 1 ? <button type="button" className="button ghost" onClick={() => setStep((value) => value - 1)}><ArrowLeft size={18} /> Back</button> : <span />}<button className="button primary" disabled={busy || (step === 1 && !draft.name.trim())}>{busy ? "Creating…" : step === 3 ? <><Link2 size={18} /> Create private room</> : <>Continue <ArrowRight size={18} /></>}</button></div>
        <p className="retention-note">By creating a room, you acknowledge live Gemini processing and 90-day meeting retention.</p>
      </form>
    </section></>
  );
}
