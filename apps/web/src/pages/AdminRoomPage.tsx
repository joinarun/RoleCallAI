import { FormEvent, useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  CalendarDays,
  ChevronRight,
  Download,
  Link2,
  LoaderCircle,
  Octagon,
  RefreshCw,
  RotateCw,
  Save,
  Settings2,
  ShieldCheck,
  Trash2,
  Users,
} from "lucide-react";
import { CapabilityBoundary } from "../components/CapabilityBoundary";
import { CopyButton } from "../components/CopyButton";
import { StatusBadge } from "../components/StatusBadge";
import { api, jsonBody } from "../lib/api";
import { ROLE_PRESET_BY_ID, ROLE_PRESETS } from "../rolePresets";
import type {
  GameType,
  Occurrence,
  Recap,
  RoleType,
  Room,
  RoomCreated,
} from "../types";

type Tab = "overview" | "settings" | "history";
type HistoryItem = {
  occurrenceId: string;
  number: number;
  status: Occurrence["status"];
  createdAt: string;
  startedAt?: string;
  endedAt?: string;
  recap?: Recap;
};
type RoomUpdated = {
  room: Room;
  newSeatUrls: Array<{ slotId: string; url: string }>;
};
type SettingsDraft = {
  name: string;
  expectedParticipants: number;
  durationMinutes: number;
  role: RoleType;
  agentName: string;
  instructions: string;
  game: GameType;
};

function settingsFromRoom(room: Room): SettingsDraft {
  return {
    name: room.name,
    expectedParticipants: room.expectedParticipants,
    durationMinutes: room.durationMinutes,
    role: room.role,
    agentName: room.agentName,
    instructions: room.instructions,
    game: room.game ?? "AUTO",
  };
}

function loadStoredLinks(roomId: string): RoomCreated | null {
  try {
    const saved = sessionStorage.getItem(`rolecall-links:${roomId}`);
    return saved ? (JSON.parse(saved) as RoomCreated) : null;
  } catch {
    return null;
  }
}

function AdminContent({ roomId }: { roomId: string }) {
  const navigate = useNavigate();
  const [room, setRoom] = useState<Room | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [current, setCurrent] = useState<Occurrence | null>(null);
  const [draft, setDraft] = useState<SettingsDraft | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [ending, setEnding] = useState(false);
  const [permissionBusy, setPermissionBusy] = useState<string | null>(null);
  const [links, setLinks] = useState<RoomCreated | null>(() => loadStoredLinks(roomId));

  const refresh = useCallback(async () => {
    try {
      const [nextRoom, nextHistory, active] = await Promise.all([
        api<Room>(`/v1/rooms/${roomId}`),
        api<HistoryItem[]>(`/v1/rooms/${roomId}/history`),
        api<Occurrence | null>(`/v1/rooms/${roomId}/current-occurrence`),
      ]);
      setRoom(nextRoom);
      setDraft((value) => value ?? settingsFromRoom(nextRoom));
      setHistory(nextHistory);
      setCurrent(active);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load the admin room.");
    }
  }, [roomId]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 4000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  function rememberLinks(updatedRoom: Room, newSeatUrls: RoomUpdated["newSeatUrls"]) {
    setLinks((currentLinks) => {
      if (!currentLinks && newSeatUrls.length === 0) return null;
      const validSlots = new Set(updatedRoom.slots.map((slot) => slot.id));
      const merged = new Map(
        (currentLinks?.seatUrls ?? [])
          .filter((item) => validSlots.has(item.slotId))
          .map((item) => [item.slotId, item]),
      );
      for (const item of newSeatUrls) merged.set(item.slotId, item);
      const next: RoomCreated = {
        room: updatedRoom,
        adminUrl: currentLinks?.adminUrl ?? "",
        seatUrls: [...merged.values()],
      };
      sessionStorage.setItem(`rolecall-links:${roomId}`, JSON.stringify(next));
      return next;
    });
  }

  async function regenerate(slotId: string) {
    if (!confirm("Regenerate this seat link? Its old link and active sessions will stop working.")) {
      return;
    }
    setError("");
    try {
      const result = await api<{ url: string }>(
        `/v1/rooms/${roomId}/slots/${slotId}:regenerate`,
        { method: "POST" },
      );
      if (room) rememberLinks(room, [{ slotId, url: result.url }]);
      setNotice("The replacement seat link is ready; the previous link is revoked.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not regenerate this seat link.");
    }
  }

  async function saveSettings(event: FormEvent) {
    event.preventDefault();
    if (!draft || current) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const result = await api<RoomUpdated>(`/v1/rooms/${roomId}`, {
        method: "PATCH",
        ...jsonBody({
          ...draft,
          game: draft.role === "FUN_FRIDAY" ? draft.game : null,
        }),
      });
      setRoom(result.room);
      setDraft(settingsFromRoom(result.room));
      rememberLinks(result.room, result.newSeatUrls);
      setNotice(
        result.newSeatUrls.length
          ? "Room settings saved. Copy the newly created seat links before leaving this browser."
          : "Room settings saved.",
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save room settings.");
    } finally {
      setSaving(false);
    }
  }

  async function setEndPermission(slotId: string, allowed: boolean) {
    setPermissionBusy(slotId);
    setError("");
    setNotice("");
    try {
      const updated = await api<Room>(`/v1/rooms/${roomId}/slots/${slotId}:end-meeting-permission`, {
        method: "PUT",
        ...jsonBody({ allowed }),
      });
      setRoom(updated);
      setNotice(allowed ? "This participant can now end a meeting for everyone." : "End-meeting delegation revoked.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update meeting control access.");
    } finally {
      setPermissionBusy(null);
    }
  }

  async function endMeeting() {
    if (!current || !confirm("End this meeting for everyone and process a recap from the conversation so far?")) return;
    setEnding(true);
    setError("");
    setNotice("");
    try {
      const ended = await api<Occurrence>(`/v1/occurrences/${current.id}:end`, { method: "POST" });
      setCurrent(ended);
      setNotice("The meeting ended for everyone. Its recap is now processing.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not end the meeting.");
    } finally {
      setEnding(false);
    }
  }

  async function deleteRoom() {
    if (current || !confirm(`Delete “${room?.name ?? "this room"}” and its retained meeting data?`)) {
      return;
    }
    setDeleting(true);
    setError("");
    try {
      await api<void>(`/v1/rooms/${roomId}`, { method: "DELETE" });
      sessionStorage.removeItem(`rolecall-links:${roomId}`);
      await api<void>("/v1/capability-sessions", { method: "DELETE" }).catch(() => undefined);
      navigate("/", { replace: true });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not delete this room.");
      setDeleting(false);
    }
  }

  if (!room || !draft) {
    return (
      <div className="center-card" aria-live="polite">
        <LoaderCircle className="spin" />
        <h1>Loading admin room…</h1>
        {error && <p className="form-error">{error}</p>}
      </div>
    );
  }

  return (
    <section className="admin-layout">
      <header className="room-heading">
        <div>
          <p className="eyebrow">Admin room</p>
          <div className="heading-line">
            <h1>{room.name}</h1>
            <StatusBadge status={current?.status ?? "IDLE"} />
          </div>
          <p>{room.agentName} · {room.role.replaceAll("_", " ").toLowerCase()} · {room.durationMinutes} min</p>
        </div>
        <button className="button ghost" onClick={() => void refresh()}>
          <RefreshCw size={17} /> Refresh
        </button>
      </header>

      <nav className="tabs" aria-label="Room management">
        <button className={tab === "overview" ? "active" : ""} onClick={() => setTab("overview")}>Overview</button>
        <button className={tab === "settings" ? "active" : ""} onClick={() => setTab("settings")}><Settings2 size={14} /> Settings</button>
        <button className={tab === "history" ? "active" : ""} onClick={() => setTab("history")}>History <span>{history.length}</span></button>
      </nav>

      {error && <p className="form-error" role="alert">{error}</p>}
      {notice && <p className="form-notice" role="status">{notice}</p>}

      {tab === "overview" && (
        <div className="admin-grid">
          <div className="panel meeting-now">
            <div className="panel-title"><div><span className="panel-icon coral-bg"><CalendarDays /></span><div><small>CURRENT OCCURRENCE</small><h2>{current ? `Meeting ${current.number}` : "Room is idle"}</h2></div></div><StatusBadge status={current?.status ?? "IDLE"} /></div>
            {current ? <><div className="big-status"><span>{Object.values(current.attendance).filter((person) => person.connected).length}</span><small>of {room.expectedParticipants} present</small></div><div className="presence-bar">{room.slots.map((slot) => <span key={slot.id} className={current.attendance[slot.id]?.connected ? "present" : ""} />)}</div><p>{current.status === "LOBBY" ? "The agent starts automatically when every seat arrives." : current.status === "PROCESSING" ? "The conversation is being turned into a recap." : "The deterministic controller is running the floor."}</p>{["LOBBY", "STARTING", "RUNNING", "ENDING"].includes(current.status) && <button className="button danger end-meeting-admin" disabled={ending} onClick={() => void endMeeting()}>{ending ? <LoaderCircle className="spin" /> : <Octagon size={17} />} End meeting for everyone</button>}</> : <div className="idle-illustration"><span className="mini-orb" /><p>The next participant arrival creates Meeting {history.length + 1}.</p></div>}
          </div>

          <div className="panel">
            <div className="panel-title"><div><span className="panel-icon mint-bg"><Users /></span><div><small>PERSISTENT SEATS</small><h2>{room.expectedParticipants} invitations</h2></div></div></div>
            {links?.adminUrl && <div className="admin-link-callout"><div><small>ADMIN LINK</small><strong>Keep your management credential safe</strong></div><CopyButton value={links.adminUrl} /></div>}
            <div className="seat-admin-list">{room.slots.map((seat) => { const link = links?.seatUrls.find((item) => item.slotId === seat.id)?.url; const seatName = seat.lastDisplayName || `Seat ${seat.ordinal}`; return <div key={seat.id}><span className="avatar small">{seat.ordinal}</span><div><strong>{seatName}</strong><small>{link ? "Link available this browser session" : "Secret link hidden"}</small></div><button className={`permission-toggle ${seat.canEndMeeting ? "active" : ""}`} aria-label={seat.canEndMeeting ? `${seatName} can end meeting; revoke permission` : `Delegate end meeting to ${seatName}`} aria-pressed={seat.canEndMeeting} disabled={permissionBusy === seat.id} onClick={() => void setEndPermission(seat.id, !seat.canEndMeeting)} title={seat.canEndMeeting ? "Revoke permission to end the meeting for everyone" : "Allow this participant to end the meeting for everyone"}>{permissionBusy === seat.id ? <LoaderCircle className="spin" /> : <ShieldCheck />}<span>{seat.canEndMeeting ? "Can end" : "Delegate end"}</span></button>{link && <CopyButton value={link} />}<button className="bare-button" disabled={Boolean(current)} onClick={() => void regenerate(seat.id)} title={current ? "Seat links are locked during an active occurrence" : "Regenerate seat link"}><RotateCw size={16} /></button></div>; })}</div>
            <p className="privacy-callout"><Link2 size={15} aria-hidden="true" /> Lost links cannot be recovered. Regeneration revokes the previous link.</p>
          </div>

          <div className="panel span-two brief-panel"><div><small>FACILITATOR BRIEF</small><h2>{room.agentName}’s operating note</h2></div><blockquote>{room.instructions || "No additional instructions."}</blockquote></div>
        </div>
      )}

      {tab === "settings" && (
        <div className="settings-stack">
          <form className="panel settings-form" onSubmit={(event) => void saveSettings(event)}>
            <div className="panel-title"><div><span className="panel-icon indigo-bg"><Settings2 /></span><div><small>ROOM CONFIGURATION</small><h2>Facilitator and timing</h2></div></div></div>
            {current && <p className="panel-note">Settings are locked while Meeting {current.number} is {current.status.toLowerCase()}.</p>}
            <div className="field-grid"><label>Room name<input required maxLength={100} disabled={Boolean(current)} value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label><label>Agent name<input required maxLength={60} disabled={Boolean(current)} value={draft.agentName} onChange={(event) => setDraft({ ...draft, agentName: event.target.value })} /></label></div>
            <div className="field-grid"><label>Participants<select disabled={Boolean(current)} value={draft.expectedParticipants} onChange={(event) => setDraft({ ...draft, expectedParticipants: Number(event.target.value) })}>{Array.from({ length: 9 }, (_, index) => index + 2).map((count) => <option key={count} value={count}>{count} people</option>)}</select></label><label>Duration<select disabled={Boolean(current)} value={draft.durationMinutes} onChange={(event) => setDraft({ ...draft, durationMinutes: Number(event.target.value) })}>{[5, 10, 15, 20, 30, 45, 60].map((minutes) => <option key={minutes} value={minutes}>{minutes} minutes</option>)}</select></label></div>
            <div className="field-grid"><label>Role<select disabled={Boolean(current)} value={draft.role} onChange={(event) => { const role = event.target.value as RoleType; setDraft({ ...draft, role, instructions: ROLE_PRESET_BY_ID[role].prompt }); }}>{ROLE_PRESETS.map((preset) => <option key={preset.id} value={preset.id}>{preset.title}</option>)}</select></label>{draft.role === "FUN_FRIDAY" ? <label>Game<select aria-label="Game" disabled={Boolean(current)} value={draft.game} onChange={(event) => setDraft({ ...draft, game: event.target.value as GameType })}><option value="AUTO">Auto</option><option value="RAPID_FIRE_TRIVIA">Rapid-fire trivia</option><option value="WOULD_YOU_RATHER">Would You Rather</option><option value="CATEGORIES">Categories</option></select></label> : <div />}</div>
            <label>How should the agent run it?<textarea aria-label="How should the agent run it?" maxLength={8000} rows={6} disabled={Boolean(current)} value={draft.instructions} onChange={(event) => setDraft({ ...draft, instructions: event.target.value })} /></label>
            <div className="settings-actions"><button type="button" className="button ghost" disabled={Boolean(current) || saving} onClick={() => setDraft(settingsFromRoom(room))}>Discard changes</button><button className="button primary" disabled={Boolean(current) || saving}>{saving ? <LoaderCircle className="spin" /> : <Save size={17} />} Save settings</button></div>
          </form>

          <div className="panel danger-zone"><div><small>DANGER ZONE</small><h2>Delete this reusable room</h2><p>Deletion revokes its links immediately and queues retained meeting data and memory for removal.</p></div><button className="button danger" disabled={Boolean(current) || deleting} onClick={() => void deleteRoom()}>{deleting ? <LoaderCircle className="spin" /> : <Trash2 size={17} />} Delete room</button></div>
        </div>
      )}

      {tab === "history" && (
        <div className="panel history-panel">
          <div className="panel-title"><div><span className="panel-icon indigo-bg"><CalendarDays /></span><div><small>90-DAY HISTORY</small><h2>Meetings and outcomes</h2></div></div></div>
          {history.length === 0 ? <div className="empty-inline"><CalendarDays /><p>Completed meetings will appear here.</p></div> : history.map((item) => <details className="history-item" key={item.occurrenceId}><summary><span className="history-number">{String(item.number).padStart(2, "0")}</span><div><strong>Meeting {item.number}</strong><small>{new Date(item.createdAt).toLocaleString()}</small></div><StatusBadge status={item.status} /><ChevronRight /></summary>{item.recap ? <div className="recap-body"><p>{item.recap.summary}</p><div className="recap-columns"><div><small>DECISIONS</small>{item.recap.decisions.length ? <ul>{item.recap.decisions.map((text) => <li key={text}>{text}</li>)}</ul> : <p>None recorded.</p>}</div><div><small>ACTIONS</small>{item.recap.actions.length ? <ul>{item.recap.actions.map((action) => <li key={action.text}>{action.text}</li>)}</ul> : <p>None recorded.</p>}</div></div><a className="text-link" href={`${import.meta.env.VITE_API_BASE_URL ?? ""}/v1/occurrences/${item.occurrenceId}/transcript`}><Download size={15} /> Open transcript JSON</a></div> : <div className="recap-body"><p>Recap is still processing.</p></div>}</details>)}
        </div>
      )}
    </section>
  );
}

export function AdminRoomPage() {
  const { roomId = "" } = useParams();
  return <CapabilityBoundary roomId={roomId} expected="ADMIN">{() => <AdminContent roomId={roomId} />}</CapabilityBoundary>;
}
