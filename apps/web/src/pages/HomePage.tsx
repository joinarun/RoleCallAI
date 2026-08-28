import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  ArrowRight,
  CalendarDays,
  Clock3,
  ExternalLink,
  History,
  LayoutDashboard,
  Link2,
  LoaderCircle,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
  Users,
} from "lucide-react";
import { CopyButton } from "../components/CopyButton";
import { StatusBadge } from "../components/StatusBadge";
import { api, jsonBody } from "../lib/api";
import {
  capabilityToken,
  listRoomLinks,
  removeRoomLinks,
} from "../lib/linkVault";
import type {
  DashboardRoomItem,
  DashboardRoomsResponse,
  HistoryItem,
  RoomCreated,
} from "../types";
import { CreateRoomPage } from "./CreateRoomPage";

function readableRole(role: string) {
  return role.replaceAll("_", " ").toLowerCase().replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDuration(seconds?: number | null) {
  if (seconds == null) return "Not started";
  if (seconds < 60) return `${seconds} sec`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return remainder ? `${hours} hr ${remainder} min` : `${hours} hr`;
}

function meetingDate(item: HistoryItem) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(item.startedAt ?? item.createdAt));
}

type RecentMeeting = HistoryItem & { roomName: string; roomId: string };

function WorkspaceDashboard({
  storedRooms,
  onCreate,
  onForget,
}: {
  storedRooms: RoomCreated[];
  onCreate: () => void;
  onForget: (roomId: string) => void;
}) {
  const [rooms, setRooms] = useState<DashboardRoomItem[]>([]);
  const [unavailable, setUnavailable] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  const refresh = useCallback(() => setRefreshKey((value) => value + 1), []);

  useEffect(() => {
    let cancelled = false;
    async function loadDashboard() {
      setLoading(true);
      setError("");
      const credentials = storedRooms.flatMap((item) => {
        const token = capabilityToken(item.adminUrl);
        return token ? [{ roomId: item.room.id, token }] : [];
      });
      try {
        const result = await api<DashboardRoomsResponse>("/v1/dashboard/rooms", {
          method: "POST",
          ...jsonBody({ rooms: credentials }),
        });
        if (!cancelled) {
          setRooms(result.rooms);
          setUnavailable([
            ...new Set([
              ...result.unavailableRoomIds,
              ...storedRooms
                .filter((item) => !credentials.some((entry) => entry.roomId === item.room.id))
                .map((item) => item.room.id),
            ]),
          ]);
        }
      } catch (reason) {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : "Could not load the workspace.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void loadDashboard();
    return () => {
      cancelled = true;
    };
  }, [refreshKey, storedRooms]);

  const roomLinks = useMemo(
    () => new Map(storedRooms.map((item) => [item.room.id, item])),
    [storedRooms],
  );
  const recentMeetings = useMemo(
    () =>
      rooms
        .flatMap((item) =>
          item.history.map((meeting) => ({
            ...meeting,
            roomId: item.room.id,
            roomName: item.room.name,
          })),
        )
        .sort(
          (left, right) =>
            new Date(right.startedAt ?? right.createdAt).getTime() -
            new Date(left.startedAt ?? left.createdAt).getTime(),
        ),
    [rooms],
  );
  const activeRooms = rooms.filter((item) => item.currentOccurrence).length;
  const totalSeconds = recentMeetings.reduce(
    (total, item) => total + (item.durationSeconds ?? 0),
    0,
  );

  return (
    <section className="workspace-layout">
      <header className="workspace-hero">
        <div>
          <p className="eyebrow"><span /> Your meeting workspace</p>
          <h1>Rooms, people and outcomes.<br /><em>All in one view.</em></h1>
          <p>Run a meeting, share a saved seat link, or return to the decisions your team made.</p>
        </div>
        <div className="workspace-actions">
          <button className="button ghost" disabled={loading} onClick={refresh}>
            {loading ? <LoaderCircle className="spin" /> : <RefreshCw />} Refresh
          </button>
          <button className="button primary" onClick={onCreate}><Plus /> Create room</button>
        </div>
      </header>

      <div className="workspace-private-note">
        <LayoutDashboard />
        <span><strong>Private browser workspace</strong> — only rooms whose admin links were created in this browser session appear here.</span>
      </div>

      {error && <p className="form-error" role="alert">{error}</p>}

      <div className="workspace-metrics" aria-label="Meeting workspace totals">
        <Metric icon={<Sparkles />} label="Saved rooms" value={String(rooms.length)} />
        <Metric icon={<Users />} label="Live now" value={String(activeRooms)} tone="mint" />
        <Metric icon={<History />} label="Meetings" value={String(recentMeetings.length)} />
        <Metric icon={<Clock3 />} label="Conversation time" value={formatDuration(totalSeconds)} />
      </div>

      <div className="workspace-section-heading">
        <div><p className="eyebrow coral">Meeting rooms</p><h2>Your reusable rooms</h2></div>
        <span>{rooms.length} available</span>
      </div>

      {loading && rooms.length === 0 ? (
        <div className="workspace-loading" aria-live="polite"><LoaderCircle className="spin" /> Loading your rooms…</div>
      ) : (
        <div className="room-dashboard-grid">
          {rooms.map((item) => (
            <RoomDashboardCard key={item.room.id} item={item} links={roomLinks.get(item.room.id)} />
          ))}
          {unavailable.map((roomId) => {
            const stored = roomLinks.get(roomId);
            if (!stored) return null;
            return (
              <article className="dashboard-room-card unavailable" key={roomId}>
                <div className="dashboard-room-top"><span className="room-card-icon"><Link2 /></span><StatusBadge status="FAILED" /></div>
                <h3>{stored.room.name}</h3>
                <p>This saved link was revoked or the room was deleted.</p>
                <button className="button ghost" onClick={() => onForget(roomId)}><Trash2 /> Remove from this browser</button>
              </article>
            );
          })}
        </div>
      )}

      <div className="workspace-section-heading history-heading">
        <div><p className="eyebrow mint">Meeting history</p><h2>Recent conversations</h2></div>
        <span>{recentMeetings.length} retained</span>
      </div>
      <div className="workspace-history">
        {recentMeetings.length ? recentMeetings.map((item) => (
          <RecentMeetingRow key={item.occurrenceId} item={item} />
        )) : <div className="workspace-empty"><CalendarDays /><h3>No completed meetings yet</h3><p>Your first recap will appear here with participants, duration and outcomes.</p></div>}
      </div>
    </section>
  );
}

function Metric({
  icon,
  label,
  value,
  tone = "indigo",
}: {
  icon: ReactNode;
  label: string;
  value: string;
  tone?: "indigo" | "mint";
}) {
  return <div className={`workspace-metric ${tone}`}><span>{icon}</span><div><small>{label}</small><strong>{value}</strong></div></div>;
}

function RoomDashboardCard({
  item,
  links,
}: {
  item: DashboardRoomItem;
  links?: RoomCreated;
}) {
  const latest = item.history[0];
  return (
    <article className="dashboard-room-card">
      <div className="dashboard-room-top">
        <span className="room-card-icon"><Sparkles /></span>
        <StatusBadge status={item.currentOccurrence?.status ?? "IDLE"} />
      </div>
      <div className="dashboard-room-title"><h3>{item.room.name}</h3><p>{item.room.agentName} · {readableRole(item.room.role)}</p></div>
      <div className="room-card-meta"><span><Users /> {item.room.expectedParticipants} seats</span><span><Clock3 /> {item.room.durationMinutes} min</span><span><History /> {item.history.length} meetings</span></div>
      <div className="dashboard-room-actions">
        {links?.adminUrl && <a className="button primary" href={links.adminUrl}>Manage room <ArrowRight /></a>}
        {links?.adminUrl && <CopyButton value={links.adminUrl} label="Copy admin link" />}
      </div>
      <div className="dashboard-seats">
        <div className="dashboard-card-label"><span>Participants and links</span><small>{item.room.slots.length}</small></div>
        {item.room.slots.map((seat) => {
          const seatLink = links?.seatUrls.find((candidate) => candidate.slotId === seat.id)?.url;
          const name = seat.lastDisplayName || `Seat ${seat.ordinal}`;
          return <div className="dashboard-seat" key={seat.id}><span className="avatar small">{name.slice(0, 2).toUpperCase()}</span><div><strong>{name}</strong><small>{seat.lastDisplayName ? `Persistent seat ${seat.ordinal}` : "Waiting for first join"}</small></div>{seatLink && <><CopyButton value={seatLink} label="Copy" /><a className="seat-open-link" href={seatLink} aria-label={`Open meeting link for ${name}`}><ExternalLink /></a></>}</div>;
        })}
      </div>
      <div className="latest-room-recap">
        <div className="dashboard-card-label"><span>Latest meeting</span>{latest && <small>{meetingDate(latest)}</small>}</div>
        {latest ? <><p>{latest.recap?.summary ?? "Recap is still processing."}</p><span>{formatDuration(latest.durationSeconds)} · {latest.participants.length ? latest.participants.join(", ") : "No attendees recorded"}</span></> : <p>No meeting history yet. Share a participant link to begin.</p>}
      </div>
    </article>
  );
}

function RecentMeetingRow({ item }: { item: RecentMeeting }) {
  return (
    <article className="workspace-history-row">
      <div className="history-date-tile"><strong>{new Date(item.startedAt ?? item.createdAt).toLocaleDateString(undefined, { day: "2-digit" })}</strong><small>{new Date(item.startedAt ?? item.createdAt).toLocaleDateString(undefined, { month: "short" })}</small></div>
      <div className="history-main"><div><strong>{item.roomName} · Meeting {item.number}</strong><small>{meetingDate(item)} · {formatDuration(item.durationSeconds)}</small></div><p>{item.recap?.summary ?? "Meeting recap is processing."}</p><div className="history-people"><Users /> {item.participants.length ? item.participants.join(", ") : "No participants recorded"}</div></div>
      <StatusBadge status={item.status} />
    </article>
  );
}

export function HomePage() {
  const [storedRooms, setStoredRooms] = useState<RoomCreated[]>(() => listRoomLinks());
  const [creating, setCreating] = useState(storedRooms.length === 0);

  function refreshStoredRooms() {
    setStoredRooms(listRoomLinks());
  }

  function forgetRoom(roomId: string) {
    removeRoomLinks(roomId);
    refreshStoredRooms();
  }

  if (creating) {
    return (
      <CreateRoomPage
        onRoomCreated={refreshStoredRooms}
        onShowWorkspace={storedRooms.length ? () => setCreating(false) : undefined}
      />
    );
  }
  return (
    <WorkspaceDashboard
      storedRooms={storedRooms}
      onCreate={() => setCreating(true)}
      onForget={forgetRoom}
    />
  );
}
