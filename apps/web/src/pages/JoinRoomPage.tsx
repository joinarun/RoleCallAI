import { FormEvent, lazy, Suspense, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { Check, Headphones, LoaderCircle, LockKeyhole, Mic2, ShieldCheck, Volume2 } from "lucide-react";
import { CapabilityBoundary } from "../components/CapabilityBoundary";
import { api, jsonBody } from "../lib/api";
import type { JoinResponse, Room } from "../types";

const CONSENT_VERSION = "2026-08-phase1";
const MeetingSurface = lazy(() =>
  import("../components/MeetingSurface").then((module) => ({ default: module.MeetingSurface })),
);

function JoinContent({ roomId, slotId }: { roomId: string; slotId: string }) {
  const [room, setRoom] = useState<Room | null>(null);
  const [name, setName] = useState("");
  const [consent, setConsent] = useState(false);
  const [deviceReady, setDeviceReady] = useState(false);
  const [deviceLabel, setDeviceLabel] = useState("Microphone not checked");
  const [checking, setChecking] = useState(false);
  const [joining, setJoining] = useState(false);
  const [join, setJoin] = useState<JoinResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    void api<Room>(`/v1/rooms/${roomId}`).then((value) => {
      setRoom(value);
      const seat = value.slots.find((item) => item.id === slotId);
      setName(seat?.lastDisplayName ?? "");
      sessionStorage.setItem(`rolecall-duration:${roomId}`, String(value.durationMinutes));
    }).catch((reason) => setError(reason instanceof Error ? reason.message : "Could not open the room."));
  }, [roomId, slotId]);

  const seatNumber = useMemo(() => room?.slots.find((seat) => seat.id === slotId)?.ordinal, [room, slotId]);

  async function checkDevice() {
    setChecking(true);
    setError("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true }, video: false });
      const track = stream.getAudioTracks()[0];
      setDeviceLabel(track.label || "Default microphone");
      stream.getTracks().forEach((item) => item.stop());
      setDeviceReady(true);
    } catch {
      setError("Microphone access is required for a voice-only meeting.");
      setDeviceReady(false);
    } finally {
      setChecking(false);
    }
  }

  async function enter(event: FormEvent) {
    event.preventDefault();
    if (!deviceReady || !consent) return;
    setJoining(true);
    setError("");
    try {
      const connectionId = crypto.randomUUID();
      const result = await api<JoinResponse>(`/v1/rooms/${roomId}:join`, {
        method: "POST",
        ...jsonBody({ name, consentVersion: CONSENT_VERSION, connectionId }),
      });
      sessionStorage.setItem(`rolecall-occurrence:${roomId}`, result.occurrence.id);
      setJoin(result);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not join the meeting.");
    } finally {
      setJoining(false);
    }
  }

  if (join) return <Suspense fallback={<div className="center-card"><LoaderCircle className="spin" /><h1>Connecting voice…</h1></div>}><MeetingSurface join={join} /></Suspense>;
  if (!room) return <div className="center-card"><LoaderCircle className="spin" /><h1>Preparing your seat…</h1>{error && <p className="form-error">{error}</p>}</div>;

  return (
    <section className="lobby-layout">
      <div className="lobby-identity"><div className="lobby-orb"><span><Mic2 /></span></div><p className="eyebrow mint">Private voice room</p><h1>{room.name}</h1><p><strong>{room.agentName}</strong> will facilitate this {room.durationMinutes}-minute meeting.</p><div className="lobby-meta"><span>Seat {seatNumber}</span><span>{room.expectedParticipants} participants</span><span>{room.role.replaceAll("_", " ").toLowerCase()}</span></div></div>
      <form className="lobby-card" onSubmit={(event) => void enter(event)}><div><p className="eyebrow coral">Before you join</p><h2>Sound good?</h2></div><label>Your name<input required maxLength={60} autoComplete="name" value={name} onChange={(event) => setName(event.target.value)} placeholder="How the agent should address you" /></label><div className={`device-check ${deviceReady ? "ready" : ""}`}><span>{deviceReady ? <Check /> : <Headphones />}</span><div><strong>{deviceReady ? "Microphone ready" : "Check your microphone"}</strong><small>{deviceLabel}</small></div><button type="button" onClick={() => void checkDevice()} disabled={checking}>{checking ? "Checking…" : deviceReady ? "Check again" : "Run check"}</button></div><div className="audio-tip"><Volume2 /><p>Use headphones when possible to reduce echo while the agent is speaking.</p></div><label className="consent-row"><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} /><span className="custom-check"><Check /></span><span>I consent to live Gemini voice processing and storage of finalized transcripts, recaps and meeting memory for up to 90 days. Raw audio is not stored.</span></label>{error && <p className="form-error" role="alert">{error}</p>}<button className="button primary wide" disabled={!name.trim() || !consent || !deviceReady || joining}>{joining ? <><LoaderCircle className="spin" /> Joining…</> : <><Mic2 /> Enter voice room</>}</button><p className="secure-note"><ShieldCheck /> Your seat link is the only credential for this room.</p></form>
    </section>
  );
}

export function JoinRoomPage() {
  const { roomId = "" } = useParams();
  return <CapabilityBoundary roomId={roomId} expected="SEAT">{(slotId) => slotId ? <JoinContent roomId={roomId} slotId={slotId} /> : <div className="center-card"><LockKeyhole /><h1>This seat is missing.</h1></div>}</CapabilityBoundary>;
}
