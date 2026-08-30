import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { CalendarDays, CheckCircle2, Clock3, Gauge, Hand, Home, LoaderCircle, LogOut, Mic, MicOff, Octagon, Radio, Sparkles, Timer, Users } from "lucide-react";
import { api, jsonBody } from "../lib/api";
import { useLiveMeeting } from "../hooks/useLiveMeeting";
import type { JoinResponse, Recap } from "../types";
import { StatusBadge } from "./StatusBadge";

function formatClock(seconds: number) {
  const value = Math.max(0, seconds);
  return `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`;
}

function formatMeetingDuration(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return minutes ? `${minutes}m ${String(remainder).padStart(2, "0")}s` : `${remainder}s`;
}

function audioQualitySummary(quality: string, mediaError: string) {
  if (mediaError || quality === "lost") return { value: "Needs attention", detail: "A connection or device issue was detected", tone: "poor" };
  if (quality === "poor") return { value: "Fair", detail: "Some network instability was detected", tone: "fair" };
  if (quality === "excellent") return { value: "Excellent", detail: "LiveKit reported a strong media connection", tone: "excellent" };
  if (quality === "good") return { value: "Good", detail: "LiveKit reported a stable media connection", tone: "good" };
  return { value: "Not measured", detail: "No quality warning was reported", tone: "unknown" };
}

export function MeetingSurface({ join }: { join: JoinResponse }) {
  const live = useLiveMeeting(join);
  const [now, setNow] = useState(Date.now());
  const [recap, setRecap] = useState<Recap | null>(join.occurrence.recap ?? null);
  const [actionBusy, setActionBusy] = useState(false);
  const [error, setError] = useState("");
  const occurrenceId = live.occurrence.id;
  const occurrenceStatus = live.occurrence.status;
  const setLiveOccurrence = live.setOccurrence;

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (live.recap) setRecap(live.recap);
  }, [live.recap]);

  useEffect(() => {
    if (occurrenceStatus === "COMPLETED" || occurrenceStatus === "FAILED") return;
    async function synchronizeState() {
      try {
        const result = await api<JoinResponse["occurrence"]>(`/v1/occurrences/${occurrenceId}/state`);
        setLiveOccurrence(result);
        if (result.recap) setRecap(result.recap);
      } catch {
        // LiveKit data remains primary; polling is a reconnect and completion backstop.
      }
    }
    void synchronizeState();
    const timer = window.setInterval(() => void synchronizeState(), 3000);
    return () => window.clearInterval(timer);
  }, [occurrenceId, occurrenceStatus, setLiveOccurrence]);

  useEffect(() => {
    if (live.occurrence.status !== "PROCESSING" && live.occurrence.status !== "COMPLETED") return;
    async function loadRecap() {
      try {
        const result = await api<Recap>(`/v1/occurrences/${live.occurrence.id}/recap`);
        setRecap(result);
      } catch {
        // Processing is expected to return 404 until the recap is committed.
      }
    }
    void loadRecap();
    const timer = window.setInterval(() => void loadRecap(), 2500);
    return () => window.clearInterval(timer);
  }, [live.occurrence.id, live.occurrence.status]);

  const currentSpeaker = useMemo(() => {
    if (live.occurrence.currentFloorType === "AGENT") return { name: join.agentName, agent: true };
    const attendance = live.occurrence.currentFloorSlotId ? live.occurrence.attendance[live.occurrence.currentFloorSlotId] : null;
    return { name: attendance?.displayName ?? "No active speaker", agent: false };
  }, [join.agentName, live.occurrence]);
  const startedAt = live.occurrence.startedAt ? new Date(live.occurrence.startedAt).getTime() : 0;
  const roomDuration = Number(sessionStorage.getItem(`rolecall-duration:${join.occurrence.roomId}`) ?? 15);
  const remaining = startedAt ? Math.floor((startedAt + roomDuration * 60000 - now) / 1000) : Math.max(0, Math.floor((new Date(live.occurrence.lobbyDeadlineAt).getTime() - now) / 1000));
  const isLobby = live.occurrence.status === "LOBBY";
  const canStart = isLobby && now >= new Date(live.occurrence.lobbyDeadlineAt).getTime();
  const raised = live.occurrence.handRaiseQueue.includes(join.slotId);
  const myTurn = live.occurrence.currentFloorSlotId === join.slotId;
  const canEndMeeting = (live.occurrence.endMeetingSlotIds ?? []).includes(join.slotId);
  const meetingIsLive = ["LOBBY", "STARTING", "RUNNING", "ENDING"].includes(live.occurrence.status);

  async function start() {
    setActionBusy(true);
    setError("");
    try {
      const occurrence = await api<JoinResponse["occurrence"]>(`/v1/occurrences/${live.occurrence.id}:start`, { method: "POST", ...jsonBody({ reason: "participant_requested" }) });
      live.setOccurrence(occurrence);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not start the meeting.");
    } finally {
      setActionBusy(false);
    }
  }

  async function leave() {
    if (!confirm("Leave this meeting? Everyone else can continue.")) return;
    setActionBusy(true);
    setError("");
    try {
      await live.leaveMeeting();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "You left, but presence may take a moment to update.");
    } finally {
      setActionBusy(false);
    }
  }

  async function endForEveryone() {
    if (!confirm("End this meeting for everyone and create a recap from the conversation so far?")) return;
    setActionBusy(true);
    setError("");
    try {
      const occurrence = await api<JoinResponse["occurrence"]>(`/v1/occurrences/${live.occurrence.id}:end`, { method: "POST" });
      live.setOccurrence(occurrence);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not end the meeting.");
    } finally {
      setActionBusy(false);
    }
  }

  if (live.left) {
    return <section className="meeting-complete"><div className="complete-mark left-mark"><LogOut /></div><p className="eyebrow mint">You left the room</p><h1>The meeting can continue without you.</h1><p className="recap-summary">You can close this tab. Your persistent seat link can be used again for a future meeting.</p><a className="button primary" href="/">Return to RoleCallAI</a></section>;
  }

  if (recap) {
    const meetingStart = new Date(live.occurrence.startedAt ?? live.occurrence.createdAt);
    const meetingEnd = live.occurrence.endedAt ? new Date(live.occurrence.endedAt) : meetingStart;
    const actualDurationSeconds = Math.max(
      0,
      Math.round((meetingEnd.getTime() - meetingStart.getTime()) / 1000),
    );
    const quality = audioQualitySummary(live.audioQuality, live.mediaError);
    const recapCitations = recap.citations ?? [];
    return <section className="meeting-complete recap-complete"><div className="complete-mark"><CheckCircle2 /></div><p className="eyebrow mint">Meeting complete</p><h1>Meeting summary</h1><p className="completion-room-name">{join.roomName} · facilitated by {join.agentName}</p><div className="recap-meta-grid"><SummaryMetric icon={<CalendarDays />} label="Date" value={meetingStart.toLocaleDateString(undefined, { dateStyle: "medium" })} detail={meetingStart.toLocaleDateString(undefined, { weekday: "long" })} /><SummaryMetric icon={<Clock3 />} label="Time" value={meetingStart.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })} detail="Meeting start" /><SummaryMetric icon={<Timer />} label="Duration" value={formatMeetingDuration(actualDurationSeconds)} detail={`${roomDuration} min scheduled`} /><SummaryMetric icon={<Gauge />} label="Audio quality" value={quality.value} detail={quality.detail} tone={quality.tone} /></div><div className="recap-overview"><small>MEETING SUMMARY</small><p className="recap-summary">{recap.summary}</p></div><div className="recap-grid"><RecapGroup title="Decisions" values={recap.decisions} /><RecapGroup title="Actions" values={recap.actions.map((item) => item.text)} /><RecapGroup title="Blockers" values={recap.blockers} /><RecapGroup title="Ideas" values={recap.ideas} /></div>{recapCitations.length > 0 && <div className="recap-sources"><small>SOURCES USED</small>{recapCitations.map((citation) => <details key={`${citation.versionId}-${citation.excerpt}`}><summary>{citation.title} · v{citation.version}{citation.pageStart ? ` · page ${citation.pageStart}` : citation.slideStart ? ` · slide ${citation.slideStart}` : ""}</summary><p>{citation.excerpt}</p></details>)}</div>}<a className="button primary recap-home" href="/"><Home /> Return to home workspace</a></section>;
  }

  return (
    <section className="meeting-shell">
      <header className="meeting-header"><div><span className="live-word"><Radio /> {live.connection}</span><h1>{join.roomName}</h1></div><div className="meeting-clock"><Clock3 /><span>{formatClock(remaining)}</span><small>{isLobby ? "EARLY START" : "REMAINING"}</small></div><StatusBadge status={live.occurrence.status} /></header>
      <div className="meeting-grid">
        <aside className="roster-panel"><div className="section-label"><Users /> People <span>{Object.values(live.occurrence.attendance).filter((item) => item.connected).length}/{join.expectedParticipants}</span></div><div className="roster-list"><div className={`roster-person agent-person ${live.occurrence.currentFloorType === "AGENT" ? "speaking" : ""}`}><span className="avatar agent-avatar"><Sparkles /></span><div><strong>{join.agentName}</strong><small>AI facilitator</small></div>{live.occurrence.currentFloorType === "AGENT" && <AudioBars />}</div>{Object.values(live.occurrence.attendance).map((person) => <div className={`roster-person ${live.occurrence.currentFloorSlotId === person.slotId ? "speaking" : ""}`} key={person.slotId}><span className="avatar">{person.displayName.slice(0, 2).toUpperCase()}</span><div><strong>{person.displayName}{person.slotId === join.slotId ? " (you)" : ""}</strong><small>{person.connected ? live.occurrence.currentFloorSlotId === person.slotId ? "Speaking" : "Listening" : "Reconnecting"}</small></div>{live.occurrence.handRaiseQueue.includes(person.slotId) && <Hand className="raised-icon" />}{live.occurrence.currentFloorSlotId === person.slotId && <AudioBars />}</div>)}</div></aside>
        <section className="agent-stage" aria-label="Agent stage"><div className={`voice-orb ${currentSpeaker.agent ? "agent-active" : "listening"}`} aria-hidden="true"><span className="orb-core"><Sparkles /></span><span className="orbit orbit-one" /><span className="orbit orbit-two" /></div><p className="eyebrow">Current speaker</p><h2>{currentSpeaker.name}</h2><p>{isLobby ? "Waiting for the room to gather" : currentSpeaker.agent ? `${join.agentName} is facilitating` : myTurn ? "The floor is yours" : "Listening to the current turn"}</p>{isLobby && <div className="lobby-progress"><div>{Object.values(live.occurrence.attendance).filter((person) => person.connected).length} present</div><span>Automatic start when all expected seats arrive</span>{canStart && <button disabled={actionBusy} className="button primary" onClick={() => void start()}>{actionBusy ? <LoaderCircle className="spin" /> : <Radio />} Start with present participants</button>}</div>}{live.occurrence.status === "PROCESSING" && <div className="processing-note"><LoaderCircle className="spin" /> Turning the conversation into a recap…</div>}</section>
        <aside className="caption-panel"><div className="section-label"><Radio /> Live captions</div><div className="caption-stream" aria-live="polite" aria-relevant="additions">{live.captions.length === 0 ? <div className="caption-empty"><span className="caption-cursor" /><p>Finalized speech appears here.</p></div> : live.captions.slice(-8).map((caption) => <article key={caption.id}><strong>{caption.speakerName}</strong><p>{caption.text}</p></article>)}{live.citations.slice(-3).map((citation) => <details className="source-chip" key={`${citation.versionId}-${citation.excerpt}`}><summary>{citation.title} · v{citation.version}</summary><p>{citation.excerpt}</p></details>)}</div></aside>
      </div>
      {(error || live.mediaError) && <p className="form-error meeting-error" role="alert">{error || live.mediaError}</p>}
      <footer className="meeting-controls"><button className={`control-button ${live.micEnabled ? "on" : ""}`} disabled={!live.micAllowed} onClick={() => void live.toggleMic()}>{live.micEnabled ? <Mic /> : <MicOff />}<span>{!live.micAllowed ? "Mic unlocks on your turn" : live.micEnabled ? "Mute" : "Unmute"}</span></button><button className={`control-button hand-button ${raised ? "on" : ""}`} disabled={isLobby || raised} onClick={() => void live.raiseHand()}><Hand /><span>{raised ? "Hand raised" : "Raise hand"}</span></button>{canEndMeeting && meetingIsLive && <button className="control-button end-button" disabled={actionBusy} onClick={() => void endForEveryone()}><Octagon /><span>End for everyone</span></button>}<button className="control-button leave-button" disabled={actionBusy || !meetingIsLive} onClick={() => void leave()}><LogOut /><span>Leave meeting</span></button><div className="floor-note"><span className={myTurn ? "mint-dot" : ""} />{myTurn ? "You own the floor" : `Floor: ${currentSpeaker.name}`}</div></footer>
    </section>
  );
}

function AudioBars() {
  return <span className="audio-bars" role="img" aria-label="Speaking"><i /><i /><i /></span>;
}

function RecapGroup({ title, values }: { title: string; values: string[] }) {
  return <div><small>{title.toUpperCase()}</small>{values.length ? <ul>{values.map((value) => <li key={value}>{value}</li>)}</ul> : <p>None recorded.</p>}</div>;
}

function SummaryMetric({ icon, label, value, detail, tone = "" }: { icon: ReactNode; label: string; value: string; detail: string; tone?: string }) {
  return <div className={`recap-meta-card ${tone}`}><span>{icon}</span><div><small>{label}</small><strong>{value}</strong><p>{detail}</p></div></div>;
}
