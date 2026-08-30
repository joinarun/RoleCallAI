import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  CalendarDays,
  Clock3,
  ExternalLink,
  FileText,
  History,
  KeyRound,
  LoaderCircle,
  LogOut,
  MoonStar,
  Plus,
  Power,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Trash2,
  Upload,
  Users,
} from "lucide-react";
import { CopyButton } from "../components/CopyButton";
import { StatusBadge } from "../components/StatusBadge";
import { ApiError, api, jsonBody } from "../lib/api";
import { adminApi, clearCsrfToken, setCsrfToken } from "../lib/adminSession";
import type {
  AdminSession,
  DashboardRoomItem,
  DashboardRoomsResponse,
  DocumentView,
  GameType,
  HistoryItem,
  RoleType,
  RuntimeState,
  SeatLink,
} from "../types";
import { ROLE_PRESETS } from "../rolePresets";
import { CreateRoomPage } from "./CreateRoomPage";

declare global {
  interface Window {
    grecaptcha?: {
      enterprise: {
        ready(callback: () => void): void;
        render(element: HTMLElement, options: Record<string, unknown>): number;
        reset(widgetId: number): void;
      };
    };
  }
}

function readableRole(role: string) {
  return role.replaceAll("_", " ").toLowerCase().replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDuration(seconds?: number | null) {
  if (seconds == null) return "Not started";
  if (seconds < 60) return `${seconds} sec`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return `${hours} hr${minutes % 60 ? ` ${minutes % 60} min` : ""}`;
}

function meetingDate(item: HistoryItem) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(item.startedAt ?? item.createdAt),
  );
}

function LoginPage({ onLogin }: { onLogin: (session: AdminSession) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [captchaToken, setCaptchaToken] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [config, setConfig] = useState<{ recaptchaSiteKey: string; action: string } | null>(null);
  const captchaRef = useRef<HTMLDivElement>(null);
  const widgetId = useRef<number | null>(null);

  useEffect(() => {
    void api<{ recaptchaSiteKey: string; action: string }>("/v1/auth/config").then(setConfig);
  }, []);

  useEffect(() => {
    if (!config || !captchaRef.current) return;
    if (config.recaptchaSiteKey.startsWith("local-")) {
      setCaptchaToken("local-browser-verification");
      return;
    }
    const render = () => window.grecaptcha?.enterprise.ready(() => {
      if (!captchaRef.current || widgetId.current != null) return;
      widgetId.current = window.grecaptcha!.enterprise.render(captchaRef.current, {
        sitekey: config.recaptchaSiteKey,
        action: config.action,
        callback: (token: string) => setCaptchaToken(token),
        "expired-callback": () => setCaptchaToken(""),
        "error-callback": () => setCaptchaToken(""),
      });
    });
    if (window.grecaptcha?.enterprise) render();
    else {
      const existing = document.querySelector<HTMLScriptElement>("script[data-rolecall-recaptcha]");
      const script = existing ?? document.createElement("script");
      if (!existing) {
        script.src = "https://www.google.com/recaptcha/enterprise.js?render=explicit";
        script.async = true;
        script.defer = true;
        script.dataset.rolecallRecaptcha = "true";
        document.head.appendChild(script);
      }
      script.addEventListener("load", render, { once: true });
    }
  }, [config]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const session = await api<AdminSession>("/v1/auth/login", {
        method: "POST",
        ...jsonBody({ username, password, recaptchaToken: captchaToken }),
      });
      setCsrfToken(session.csrfToken);
      onLogin(session);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Login failed");
      if (widgetId.current != null) window.grecaptcha?.enterprise.reset(widgetId.current);
      if (!config?.recaptchaSiteKey.startsWith("local-")) setCaptchaToken("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="login-layout">
      <div className="login-hero">
        <p className="eyebrow"><span /> Secure meeting operations</p>
        <h1>Let AI Lead the<br /><em>Conversation Forward.</em></h1>
        <p>Run voice meetings, protect participant links, ground facilitators in your documents, and return to every decision from one workspace.</p>
        <div className="sleep-note"><MoonStar /><div><strong>Cost-aware by design</strong><span>Voice services sleep after 30 minutes without real activity. Sign in and allow 10–20 minutes to wake them before a meeting.</span></div></div>
      </div>
      <form className="login-card" onSubmit={(event) => void submit(event)}>
        <span className="login-icon"><ShieldCheck /></span>
        <p className="eyebrow mint">Administrator access</p>
        <h2>Open your workspace</h2>
        <p>Protected by an eight-hour secure session and reCAPTCHA Enterprise.</p>
        <label>Username<input autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required /></label>
        <label>Password<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
        <div ref={captchaRef} className="captcha-slot" aria-label="Bot verification">{config?.recaptchaSiteKey.startsWith("local-") ? "Local verification enabled" : null}</div>
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="button primary wide" disabled={busy || !captchaToken}>{busy ? <><LoaderCircle className="spin" /> Verifying…</> : <><KeyRound /> Sign in securely</>}</button>
      </form>
    </section>
  );
}

function RuntimeCard({ runtime, refresh }: { runtime: RuntimeState; refresh: () => void }) {
  const transitioning = runtime.status === "WAKING" || runtime.status === "SUSPENDING";
  async function wake() {
    await adminApi<RuntimeState>("/v1/runtime:wake", { method: "POST" });
    refresh();
  }
  return (
    <section className={`runtime-card ${runtime.status.toLowerCase()}`} aria-live="polite">
      <div className="runtime-symbol">{transitioning ? <LoaderCircle className="spin" /> : runtime.status === "READY" ? <Power /> : <MoonStar />}</div>
      <div><small>VOICE RUNTIME · {runtime.status}</small><strong>{runtime.message}</strong><span>{runtime.status === "READY" ? "Participants may join now." : `Progress ${runtime.progress}% · participants cannot wake this runtime.`}</span></div>
      {runtime.status !== "READY" && runtime.status !== "WAKING" && <button className="button primary" onClick={() => void wake()}><Power /> Wake voice services</button>}
    </section>
  );
}

function RoomCard({ item, reload }: { item: DashboardRoomItem; reload: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const [links, setLinks] = useState<SeatLink[]>([]);
  const [documents, setDocuments] = useState<DocumentView[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [roomDraft, setRoomDraft] = useState({
    name: item.room.name,
    durationMinutes: item.room.durationMinutes,
    expectedParticipants: item.room.expectedParticipants,
    role: item.room.role,
    game: item.room.game ?? "AUTO" as GameType,
    agentName: item.room.agentName,
    instructions: item.room.instructions,
  });
  const latest = item.history[0];

  const loadDetails = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const [seatLinks, docs] = await Promise.all([
        adminApi<SeatLink[]>(`/v1/admin/rooms/${item.room.id}/seat-links`),
        adminApi<DocumentView[]>(`/v1/admin/rooms/${item.room.id}/documents`),
      ]);
      setLinks(seatLinks);
      setDocuments(docs);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load room details");
    } finally {
      setBusy(false);
    }
  }, [item.room.id]);

  async function toggleDetails() {
    const next = !expanded;
    setExpanded(next);
    if (next) await loadDetails();
  }

  async function upload(file: File) {
    const body = new FormData();
    body.append("file", file);
    setBusy(true);
    try {
      await adminApi<DocumentView>(`/v1/admin/rooms/${item.room.id}/documents`, { method: "POST", body });
      await loadDetails();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  async function setEndPermission(slotId: string, allowed: boolean) {
    await adminApi(`/v1/admin/rooms/${item.room.id}/slots/${slotId}:end-meeting-permission`, {
      method: "PUT",
      ...jsonBody({ allowed }),
    });
    await loadDetails();
    reload();
  }

  async function regenerateSeat(slotId: string) {
    setBusy(true);
    try {
      const result = await adminApi<{ url: string }>(`/v1/admin/rooms/${item.room.id}/slots/${slotId}:regenerate`, { method: "POST" });
      setLinks((current) => current.map((seat) => seat.slotId === slotId ? { ...seat, url: result.url } : seat));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not regenerate the link");
    } finally {
      setBusy(false);
    }
  }

  async function saveRoom() {
    setBusy(true);
    try {
      await adminApi(`/v1/admin/rooms/${item.room.id}`, { method: "PATCH", ...jsonBody({ ...roomDraft, game: roomDraft.role === "FUN_FRIDAY" ? roomDraft.game : null }) });
      reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update the room");
    } finally {
      setBusy(false);
    }
  }

  async function deleteRoom() {
    if (!window.confirm(`Delete ${item.room.name} and its retained data?`)) return;
    setBusy(true);
    try {
      await adminApi(`/v1/admin/rooms/${item.room.id}`, { method: "DELETE" });
      reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not delete the room");
      setBusy(false);
    }
  }

  async function endMeeting() {
    if (!item.currentOccurrence || !window.confirm("End this meeting for everyone?")) return;
    await adminApi(`/v1/admin/occurrences/${item.currentOccurrence.id}:end`, {
      method: "POST",
      ...jsonBody({ reason: "ended_by_admin" }),
    });
    reload();
  }

  async function deleteDocument(documentId: string) {
    await adminApi(`/v1/admin/rooms/${item.room.id}/documents/${documentId}`, { method: "DELETE" });
    await loadDetails();
  }

  async function replaceDocument(documentId: string, file: File) {
    const body = new FormData();
    body.append("file", file);
    setBusy(true);
    try {
      await adminApi<DocumentView>(`/v1/admin/rooms/${item.room.id}/documents/${documentId}:replace`, { method: "POST", body });
      await loadDetails();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Replacement failed");
    } finally {
      setBusy(false);
    }
  }

  async function retryDocument(documentId: string) {
    setBusy(true);
    try {
      await adminApi<DocumentView>(`/v1/admin/rooms/${item.room.id}/documents/${documentId}:retry`, { method: "POST" });
      await loadDetails();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Retry failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="dashboard-room-card">
      <div className="dashboard-room-top"><span className="room-card-icon"><Sparkles /></span><StatusBadge status={item.currentOccurrence?.status ?? "IDLE"} /></div>
      <div className="dashboard-room-title"><h3>{item.room.name}</h3><p>{item.room.agentName} · {readableRole(item.room.role)}</p></div>
      <div className="room-card-meta"><span><Users /> {item.room.expectedParticipants} seats</span><span><Clock3 /> {item.room.durationMinutes} min</span><span><History /> {item.history.length} meetings</span></div>
      <div className="dashboard-room-actions"><button className="button primary" onClick={() => void toggleDetails()}>{expanded ? "Close controls" : "Manage room"}</button>{item.currentOccurrence && <button className="button danger" onClick={() => void endMeeting()}>End for everyone</button>}</div>
      <div className="latest-room-recap"><div className="dashboard-card-label"><span>Latest meeting</span>{latest && <small>{meetingDate(latest)}</small>}</div>{latest ? <><p>{latest.recap?.summary ?? "Recap is processing."}</p><span>{formatDuration(latest.durationSeconds)} · {latest.participants.join(", ") || "No attendees"}</span></> : <p>No meeting history yet.</p>}</div>
      {expanded && <div className="room-control-drawer">
        {busy && <p className="drawer-loading"><LoaderCircle className="spin" /> Updating secure room data…</p>}
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="room-settings-grid">
          <label>Room name<input value={roomDraft.name} disabled={Boolean(item.currentOccurrence)} onChange={(event) => setRoomDraft({ ...roomDraft, name: event.target.value })} /></label>
          <label>Duration<input type="number" min="5" max="60" value={roomDraft.durationMinutes} disabled={Boolean(item.currentOccurrence)} onChange={(event) => setRoomDraft({ ...roomDraft, durationMinutes: Number(event.target.value) })} /></label>
          <label>Seats<input type="number" min="2" max="10" value={roomDraft.expectedParticipants} disabled={Boolean(item.currentOccurrence)} onChange={(event) => setRoomDraft({ ...roomDraft, expectedParticipants: Number(event.target.value) })} /></label>
          <label>Role<select value={roomDraft.role} disabled={Boolean(item.currentOccurrence)} onChange={(event) => setRoomDraft({ ...roomDraft, role: event.target.value as RoleType })}>{ROLE_PRESETS.map((role) => <option key={role.id} value={role.id}>{role.title}</option>)}</select></label>
          <label>Agent name<input value={roomDraft.agentName} disabled={Boolean(item.currentOccurrence)} onChange={(event) => setRoomDraft({ ...roomDraft, agentName: event.target.value })} /></label>
          {roomDraft.role === "FUN_FRIDAY" && <label>Game<select value={roomDraft.game} disabled={Boolean(item.currentOccurrence)} onChange={(event) => setRoomDraft({ ...roomDraft, game: event.target.value as GameType })}><option value="AUTO">Auto</option><option value="RAPID_FIRE_TRIVIA">Rapid-fire trivia</option><option value="WOULD_YOU_RATHER">Would You Rather</option><option value="CATEGORIES">Categories</option></select></label>}
          <label className="wide">Facilitator instructions<textarea rows={3} value={roomDraft.instructions} disabled={Boolean(item.currentOccurrence)} onChange={(event) => setRoomDraft({ ...roomDraft, instructions: event.target.value })} /></label>
          <div className="room-settings-actions wide"><button className="button primary" disabled={busy || Boolean(item.currentOccurrence)} onClick={() => void saveRoom()}>Save settings</button><button className="button danger" disabled={busy || Boolean(item.currentOccurrence)} onClick={() => void deleteRoom()}>Delete room</button></div>
        </div>
        <div className="dashboard-card-label"><span>Participants and links</span><small>Decrypted only on request</small></div>
        {links.map((seat) => <div className="dashboard-seat" key={seat.slotId}><span className="avatar small">{(seat.lastDisplayName || `S${seat.ordinal}`).slice(0, 2).toUpperCase()}</span><div><strong>{seat.lastDisplayName || `Seat ${seat.ordinal}`}</strong><small>Persistent participant seat</small></div><label className="permission-toggle"><input type="checkbox" checked={seat.canEndMeeting} onChange={(event) => void setEndPermission(seat.slotId, event.target.checked)} /> Can end</label><button className="icon-button" disabled={busy || Boolean(item.currentOccurrence)} onClick={() => void regenerateSeat(seat.slotId)} aria-label={`Regenerate seat ${seat.ordinal} link`}><RefreshCw /></button><CopyButton value={seat.url} label="Copy" /><a className="seat-open-link" href={seat.url} target="_blank" rel="noreferrer" aria-label={`Open seat ${seat.ordinal}`}><ExternalLink /></a></div>)}
        <div className="document-library">
          <div className="dashboard-card-label"><span>Meeting documents</span><small>{documents.length}/20</small></div>
          <label className="document-upload"><Upload /><span><strong>Add context document</strong><small>PDF, DOCX, PPTX, TXT or Markdown · 25 MB</small></span><input type="file" accept=".pdf,.docx,.pptx,.txt,.md,.markdown" disabled={Boolean(item.currentOccurrence) || busy} onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file); event.currentTarget.value = ""; }} /></label>
          {item.currentOccurrence && <small className="document-lock-note">Document changes unlock when the active meeting ends.</small>}
          {documents.map((entry) => { const version = entry.pendingVersion ?? entry.activeVersion; const locked = Boolean(item.currentOccurrence) || busy; return <div className="document-row" key={entry.document.id}><FileText /><div><strong>{entry.document.title}</strong><small>{version ? `Version ${version.version} · ${Math.round(version.sizeBytes / 1024)} KB${version.errorMessage ? ` · ${version.errorMessage}` : ""}` : "No active version"}</small></div><StatusBadge status={version?.status ?? "FAILED"} />{entry.pendingVersion?.status === "FAILED" && <button className="icon-button" disabled={locked} aria-label={`Retry ${entry.document.title}`} onClick={() => void retryDocument(entry.document.id)}><RefreshCw /></button>}<label className={`icon-button ${locked ? "disabled" : ""}`} aria-label={`Replace ${entry.document.title}`}><Upload /><input type="file" accept=".pdf,.docx,.pptx,.txt,.md,.markdown" disabled={locked} onChange={(event) => { const file = event.target.files?.[0]; if (file) void replaceDocument(entry.document.id, file); event.currentTarget.value = ""; }} /></label><button className="icon-button danger" disabled={locked} aria-label={`Delete ${entry.document.title}`} onClick={() => void deleteDocument(entry.document.id)}><Trash2 /></button></div>; })}
        </div>
      </div>}
    </article>
  );
}

type RecentMeeting = HistoryItem & { roomName: string; roomId: string };
type TranscriptLine = { id: string; speakerName: string; text: string };

function RecentMeetingRow({ item }: { item: RecentMeeting }) {
  const [transcript, setTranscript] = useState<TranscriptLine[] | null>(null);
  async function toggleTranscript() {
    if (transcript) setTranscript(null);
    else setTranscript(await adminApi<TranscriptLine[]>(`/v1/admin/occurrences/${item.occurrenceId}/transcript`));
  }
  return <article className="workspace-history-row"><div className="history-date-tile"><strong>{new Date(item.startedAt ?? item.createdAt).toLocaleDateString(undefined, { day: "2-digit" })}</strong><small>{new Date(item.startedAt ?? item.createdAt).toLocaleDateString(undefined, { month: "short" })}</small></div><div className="history-main"><div><strong>{item.roomName} · Meeting {item.number}</strong><small>{meetingDate(item)} · {formatDuration(item.durationSeconds)}</small></div><p>{item.recap?.summary ?? "Meeting recap is processing."}</p><div className="history-people"><Users /> {item.participants.join(", ") || "No participants recorded"}</div><button className="history-link" onClick={() => void toggleTranscript()}>{transcript ? "Hide transcript" : "View transcript"}</button>{transcript && <div className="transcript-preview">{transcript.map((line) => <p key={line.id}><strong>{line.speakerName}</strong> {line.text}</p>)}</div>}</div><StatusBadge status={item.status} /></article>;
}

function Metric({ icon, label, value, tone = "indigo" }: { icon: ReactNode; label: string; value: string; tone?: "indigo" | "mint" }) {
  return <div className={`workspace-metric ${tone}`}><span>{icon}</span><div><small>{label}</small><strong>{value}</strong></div></div>;
}

function Dashboard({ session, onLogout }: { session: AdminSession; onLogout: () => void }) {
  const [rooms, setRooms] = useState<DashboardRoomItem[]>([]);
  const [runtime, setRuntime] = useState<RuntimeState | null>(null);
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setError("");
    try {
      const [dashboard, runtimeState] = await Promise.all([
        adminApi<DashboardRoomsResponse>("/v1/admin/rooms"),
        api<RuntimeState>("/v1/runtime"),
      ]);
      setRooms(dashboard.rooms);
      setRuntime(runtimeState);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load the workspace");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    const interval = window.setInterval(() => void refresh(), runtime?.status === "WAKING" || runtime?.status === "SUSPENDING" ? 5000 : 30000);
    return () => window.clearInterval(interval);
  }, [refresh, runtime?.status]);
  useEffect(() => {
    let lastSent = 0;
    const activity = () => {
      if (Date.now() - lastSent < 60_000) return;
      lastSent = Date.now();
      void adminApi("/v1/runtime/activity", { method: "POST" }).catch(() => undefined);
    };
    window.addEventListener("pointerdown", activity);
    window.addEventListener("keydown", activity);
    window.addEventListener("input", activity);
    return () => { window.removeEventListener("pointerdown", activity); window.removeEventListener("keydown", activity); window.removeEventListener("input", activity); };
  }, []);

  const recentMeetings = useMemo(() => rooms.flatMap((item) => item.history.map((meeting) => ({ ...meeting, roomId: item.room.id, roomName: item.room.name }))).sort((left, right) => new Date(right.startedAt ?? right.createdAt).getTime() - new Date(left.startedAt ?? left.createdAt).getTime()), [rooms]);
  const activeRooms = rooms.filter((item) => item.currentOccurrence).length;

  if (creating) return <CreateRoomPage onRoomCreated={() => undefined} onShowWorkspace={() => { setCreating(false); void refresh(); }} />;
  return <section className="workspace-layout">
    <header className="workspace-hero"><div><p className="eyebrow"><span /> Authenticated workspace</p><h1>Rooms, people and outcomes.<br /><em>All in one view.</em></h1><p>Signed in as {session.username}. Manage every room without secret admin URLs.</p></div><div className="workspace-actions"><button className="button ghost" onClick={() => void refresh()}>{loading ? <LoaderCircle className="spin" /> : <RefreshCw />} Refresh</button><button className="button primary" onClick={() => setCreating(true)}><Plus /> Create room</button><button className="button ghost" onClick={onLogout}><LogOut /> Logout</button></div></header>
    {runtime && <RuntimeCard runtime={runtime} refresh={() => void refresh()} />}
    {error && <p className="form-error" role="alert">{error}</p>}
    <div className="workspace-metrics"><Metric icon={<Sparkles />} label="Rooms" value={String(rooms.length)} /><Metric icon={<Users />} label="Live now" value={String(activeRooms)} tone="mint" /><Metric icon={<History />} label="Meetings" value={String(recentMeetings.length)} /><Metric icon={<Clock3 />} label="Conversation time" value={formatDuration(recentMeetings.reduce((total, item) => total + (item.durationSeconds ?? 0), 0))} /></div>
    <div className="workspace-section-heading"><div><p className="eyebrow coral">Meeting rooms</p><h2>Reusable rooms</h2></div><span>{rooms.length} available</span></div>
    {loading && !rooms.length ? <div className="workspace-loading"><LoaderCircle className="spin" /> Loading your rooms…</div> : <div className="room-dashboard-grid">{rooms.map((item) => <RoomCard key={item.room.id} item={item} reload={() => void refresh()} />)}{!rooms.length && <div className="workspace-empty"><CalendarDays /><h3>No rooms yet</h3><p>Create your first secured voice meeting room.</p></div>}</div>}
    <div className="workspace-section-heading history-heading"><div><p className="eyebrow mint">Meeting history</p><h2>Recent conversations</h2></div><span>{recentMeetings.length} retained</span></div>
    <div className="workspace-history">{recentMeetings.length ? recentMeetings.map((item) => <RecentMeetingRow key={item.occurrenceId} item={item} />) : <div className="workspace-empty"><History /><h3>No completed meetings yet</h3><p>Recaps, dates, durations and transcripts will appear here.</p></div>}</div>
  </section>;
}

export function HomePage() {
  const [session, setSession] = useState<AdminSession | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    void api<AdminSession>("/v1/auth/session")
      .then((value) => { setCsrfToken(value.csrfToken); setSession(value); })
      .catch((reason) => { if (!(reason instanceof ApiError) || reason.status !== 401) console.error(reason); })
      .finally(() => setLoading(false));
  }, []);

  async function logout() {
    await adminApi("/v1/auth/logout", { method: "POST" }).catch(() => undefined);
    clearCsrfToken();
    setSession(null);
  }

  if (loading) return <div className="center-card"><LoaderCircle className="spin" /><h1>Opening RoleCallAI…</h1></div>;
  return session ? <Dashboard session={session} onLogout={() => void logout()} /> : <LoginPage onLogin={setSession} />;
}
