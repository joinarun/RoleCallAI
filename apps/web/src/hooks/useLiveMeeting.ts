import { useCallback, useEffect, useRef, useState } from "react";
import {
  ConnectionQuality,
  Room as LiveKitRoom,
  RoomEvent,
  Track,
  type RemoteTrack,
} from "livekit-client";
import { api, jsonBody } from "../lib/api";
import type { Caption, JoinResponse, LiveMessage, Occurrence, Recap } from "../types";

const encoder = new TextEncoder();
const decoder = new TextDecoder();
const qualityRank: Record<ConnectionQuality, number> = {
  [ConnectionQuality.Unknown]: -1,
  [ConnectionQuality.Excellent]: 0,
  [ConnectionQuality.Good]: 1,
  [ConnectionQuality.Poor]: 2,
  [ConnectionQuality.Lost]: 3,
};

export function useLiveMeeting(join: JoinResponse) {
  const roomRef = useRef<LiveKitRoom | null>(null);
  const allowRecoveryRef = useRef(true);
  const wantsMicRef = useRef(true);
  const worstQualityRef = useRef<ConnectionQuality>(ConnectionQuality.Unknown);
  const [connection, setConnection] = useState<"connecting" | "connected" | "reconnecting" | "disconnected">("connecting");
  const [occurrence, setOccurrence] = useState(join.occurrence);
  const [captions, setCaptions] = useState<Caption[]>([]);
  const [recap, setRecap] = useState<Recap | null>(join.occurrence.recap ?? null);
  const [micEnabled, setMicEnabled] = useState(false);
  const [micAllowed, setMicAllowed] = useState(false);
  const [mediaError, setMediaError] = useState("");
  const [audioQuality, setAudioQuality] = useState<ConnectionQuality>(ConnectionQuality.Unknown);
  const [left, setLeft] = useState(false);

  const noteAudioQuality = useCallback((quality: ConnectionQuality) => {
    if (
      quality !== ConnectionQuality.Unknown &&
      qualityRank[quality] > qualityRank[worstQualityRef.current]
    ) {
      worstQualityRef.current = quality;
      setAudioQuality(quality);
    }
  }, []);

  useEffect(() => {
    const room = new LiveKitRoom({ adaptiveStream: true, dynacast: false });
    roomRef.current = room;
    const audioElements = new Set<HTMLMediaElement>();
    let disposed = false;
    let recovering = false;

    function syncPermission() {
      const allowed = Boolean(room.localParticipant.permissions?.canPublish);
      setMicAllowed(allowed);
      if (!allowed) {
        void room.localParticipant.setMicrophoneEnabled(false).finally(() => setMicEnabled(false));
      } else if (wantsMicRef.current) {
        void room.localParticipant.setMicrophoneEnabled(true).then(() => {
          setMicEnabled(true);
          setMediaError("");
        }).catch(() => {
          setMicEnabled(false);
          noteAudioQuality(ConnectionQuality.Poor);
          setMediaError("Your microphone is unavailable. Check browser permission, then unmute.");
        });
      }
    }
    function onTrackSubscribed(track: RemoteTrack) {
      if (track.kind !== Track.Kind.Audio) return;
      const element = track.attach();
      element.className = "remote-audio";
      document.body.appendChild(element);
      audioElements.add(element);
      void element.play().catch(() => undefined);
    }
    function onTrackUnsubscribed(track: RemoteTrack) {
      for (const element of track.detach()) {
        audioElements.delete(element);
        element.remove();
      }
    }
    function onData(data: Uint8Array) {
      try {
        const message = JSON.parse(decoder.decode(data)) as LiveMessage;
        if (message.occurrenceId !== join.occurrence.id || message.v !== 1) return;
        if (message.type === "meeting.state") setOccurrence(message.payload as unknown as Occurrence);
        if (message.type === "caption.final") setCaptions((items) => [...items.filter((item) => item.id !== (message.payload as unknown as Caption).id), message.payload as unknown as Caption].sort((a, b) => a.sequence - b.sequence));
        if (message.type === "recap.ready") setRecap(message.payload as unknown as Recap);
      } catch {
        // Ignore unversioned or malformed room data.
      }
    }

    async function recoverWithFreshToken() {
      if (disposed || recovering || !allowRecoveryRef.current) return;
      recovering = true;
      setConnection("reconnecting");
      try {
        for (let attempt = 0; attempt < 3 && !disposed; attempt += 1) {
          try {
            if (attempt > 0) {
              await new Promise((resolve) => window.setTimeout(resolve, 2 ** attempt * 500));
            }
            const refreshed = await api<JoinResponse>(`/v1/rooms/${join.occurrence.roomId}:refresh`, {
              method: "POST",
              ...jsonBody({ connectionId: join.connectionId }),
            });
            if (disposed) return;
            setOccurrence(refreshed.occurrence);
            await room.connect(refreshed.livekitUrl, refreshed.livekitToken, { autoSubscribe: true });
            if (!disposed) {
              setConnection("connected");
              syncPermission();
            }
            return;
          } catch {
            // Retry with bounded backoff; state polling still provides recap access.
          }
        }
        if (!disposed) {
          setConnection("disconnected");
          noteAudioQuality(ConnectionQuality.Lost);
        }
      } finally {
        recovering = false;
      }
    }

    room.on(RoomEvent.Connected, () => { setConnection("connected"); syncPermission(); });
    room.on(RoomEvent.Reconnecting, () => { setConnection("reconnecting"); noteAudioQuality(ConnectionQuality.Poor); });
    room.on(RoomEvent.Reconnected, () => { setConnection("connected"); syncPermission(); });
    room.on(RoomEvent.Disconnected, () => {
      if (disposed || !allowRecoveryRef.current) return;
      setConnection("disconnected");
      void recoverWithFreshToken();
    });
    room.on(RoomEvent.ParticipantPermissionsChanged, syncPermission);
    room.on(RoomEvent.ConnectionQualityChanged, (quality) => noteAudioQuality(quality));
    room.on(RoomEvent.TrackSubscribed, onTrackSubscribed);
    room.on(RoomEvent.TrackUnsubscribed, onTrackUnsubscribed);
    room.on(RoomEvent.DataReceived, onData);

    void room.connect(join.livekitUrl, join.livekitToken, { autoSubscribe: true }).catch(() => {
      if (!disposed) void recoverWithFreshToken();
    });
    return () => {
      disposed = true;
      room.removeAllListeners();
      void room.disconnect();
      for (const element of audioElements) element.remove();
      roomRef.current = null;
    };
  }, [join.connectionId, join.livekitToken, join.livekitUrl, join.occurrence.id, join.occurrence.roomId, noteAudioQuality]);

  useEffect(() => {
    const livePhase = ["LOBBY", "STARTING", "RUNNING", "ENDING"].includes(occurrence.status);
    allowRecoveryRef.current = livePhase;
    if (!livePhase) {
      setConnection("disconnected");
      void roomRef.current?.disconnect();
    }
  }, [occurrence.status]);

  const toggleMic = useCallback(async () => {
    const room = roomRef.current;
    if (!room || !micAllowed) return;
    const next = !micEnabled;
    wantsMicRef.current = next;
    try {
      await room.localParticipant.setMicrophoneEnabled(next);
      setMicEnabled(next);
      setMediaError("");
    } catch {
      setMicEnabled(false);
      noteAudioQuality(ConnectionQuality.Poor);
      setMediaError("Your microphone is unavailable. Check browser permission and try again.");
    }
  }, [micAllowed, micEnabled, noteAudioQuality]);

  const raiseHand = useCallback(async () => {
    const room = roomRef.current;
    if (!room) return;
    const message: LiveMessage = { v: 1, type: "hand.raise", occurrenceId: occurrence.id, sequence: occurrence.sequence, payload: {} };
    await room.localParticipant.publishData(encoder.encode(JSON.stringify(message)), { reliable: true, topic: "rolecall.v1" });
  }, [occurrence.id, occurrence.sequence]);

  const leaveMeeting = useCallback(async () => {
    allowRecoveryRef.current = false;
    wantsMicRef.current = false;
    setLeft(true);
    const room = roomRef.current;
    try {
      await room?.localParticipant.setMicrophoneEnabled(false);
    } catch {
      // Continue leaving even if the browser has already removed the track.
    }
    setMicEnabled(false);
    try {
      const updated = await api<Occurrence>(`/v1/occurrences/${occurrence.id}:leave`, {
        method: "POST",
        ...jsonBody({ connectionId: join.connectionId }),
      });
      setOccurrence(updated);
    } finally {
      await room?.disconnect();
      setConnection("disconnected");
    }
  }, [join.connectionId, occurrence.id]);

  return { connection, occurrence, setOccurrence, captions, recap, micEnabled, micAllowed, mediaError, audioQuality, left, toggleMic, raiseHand, leaveMeeting };
}
