export type RoleType =
  | "SCRUM_MASTER"
  | "FUN_FRIDAY"
  | "BRAINSTORM"
  | "SPRINT_RETROSPECTIVE"
  | "PROJECT_STATUS"
  | "INCIDENT_RESPONSE"
  | "COURSE_INSTRUCTOR"
  | "WORKSHOP_FACILITATOR"
  | "TECHNICAL_INTERVIEWER"
  | "PRODUCT_DISCOVERY"
  | "DECISION_MAKING"
  | "TOWN_HALL"
  | "CUSTOM";
export type GameType = "AUTO" | "RAPID_FIRE_TRIVIA" | "WOULD_YOU_RATHER" | "CATEGORIES";
export type OccurrenceStatus =
  | "LOBBY"
  | "STARTING"
  | "RUNNING"
  | "ENDING"
  | "PROCESSING"
  | "COMPLETED"
  | "FAILED";
export type RuntimeStatus = "SLEEPING" | "WAKING" | "READY" | "SUSPENDING" | "ERROR";
export type DocumentStatus = "PENDING" | "INDEXING" | "READY" | "FAILED" | "DELETING" | "DELETED";

export interface Seat {
  id: string;
  ordinal: number;
  lastDisplayName?: string | null;
  canEndMeeting: boolean;
}

export interface Room {
  id: string;
  name: string;
  expectedParticipants: number;
  durationMinutes: number;
  role: RoleType;
  agentName: string;
  instructions: string;
  game?: GameType | null;
  slots: Seat[];
  createdAt: string;
  updatedAt: string;
}

export interface Recap {
  summary: string;
  decisions: string[];
  actions: Array<{ text: string; ownerSlotId?: string | null }>;
  blockers: string[];
  ideas: string[];
  gameResults: Array<{ label: string; score?: number | null; slotId?: string | null }>;
  citations?: RetrievalCitation[];
  generatedAt: string;
}

export interface Attendance {
  slotId: string;
  displayName: string;
  consentVersion: string;
  joinedAt: string;
  connected: boolean;
  connectionId: string;
  disconnectedAt?: string | null;
  leftAt?: string | null;
  absent: boolean;
}

export interface Occurrence {
  id: string;
  roomId: string;
  number: number;
  status: OccurrenceStatus;
  createdAt: string;
  lobbyDeadlineAt: string;
  startedAt?: string | null;
  endedAt?: string | null;
  attendance: Record<string, Attendance>;
  absentSlotIds: string[];
  turnOrder: string[];
  currentFloorType: "AGENT" | "SEAT" | "NONE";
  currentFloorSlotId?: string | null;
  nextFloorSlotId?: string | null;
  floorEpoch: number;
  handRaiseQueue: string[];
  endMeetingSlotIds: string[];
  readyDocumentVersionIds?: string[];
  omittedDocumentCount?: number;
  retrievalCitations?: RetrievalCitation[];
  recap?: Recap | null;
  sequence: number;
}

export interface RoomCreated {
  room: Room;
  seatUrls: Array<{ slotId: string; url: string }>;
}

export interface AdminSession {
  authenticated: boolean;
  username: string;
  ownerId: string;
  expiresAt: string;
  csrfToken: string;
}

export interface RuntimeState {
  status: RuntimeStatus;
  progress: number;
  message: string;
  generation: number;
  operationId?: string | null;
  lastActivityAt: string;
  updatedAt: string;
  errorCode?: string | null;
}

export interface SeatLink {
  slotId: string;
  ordinal: number;
  url: string;
  lastDisplayName?: string | null;
  canEndMeeting: boolean;
}

export interface RetrievalCitation {
  documentId: string;
  versionId: string;
  title: string;
  version: number;
  excerpt: string;
  pageStart?: number | null;
  pageEnd?: number | null;
  slideStart?: number | null;
  slideEnd?: number | null;
  distance?: number | null;
}

export interface DocumentVersion {
  id: string;
  documentId: string;
  version: number;
  originalFilename: string;
  title: string;
  sizeBytes: number;
  status: DocumentStatus;
  errorCode?: string | null;
  errorMessage?: string | null;
  createdAt: string;
  readyAt?: string | null;
  chunkCount?: number | null;
}

export interface RoomDocument {
  id: string;
  title: string;
  activeVersionId?: string | null;
  pendingVersionId?: string | null;
}

export interface DocumentView {
  document: RoomDocument;
  activeVersion?: DocumentVersion | null;
  pendingVersion?: DocumentVersion | null;
}

export interface HistoryItem {
  occurrenceId: string;
  number: number;
  status: OccurrenceStatus;
  createdAt: string;
  startedAt?: string | null;
  endedAt?: string | null;
  recap?: Recap | null;
  participants: string[];
  durationSeconds?: number | null;
}

export interface DashboardRoomItem {
  room: Room;
  currentOccurrence?: Occurrence | null;
  history: HistoryItem[];
}

export interface DashboardRoomsResponse {
  rooms: DashboardRoomItem[];
  unavailableRoomIds: string[];
}

export interface JoinResponse {
  occurrence: Occurrence;
  livekitUrl: string;
  livekitToken: string;
  slotId: string;
  roomName: string;
  agentName: string;
  expectedParticipants: number;
  connectionId: string;
  canEndMeeting: boolean;
}

export interface Caption {
  id: string;
  sequence: number;
  speakerId: string;
  speakerName: string;
  text: string;
}

export interface LiveMessage {
  v: 1;
  type: "meeting.state" | "hand.raise" | "caption.final" | "citation" | "recap.ready";
  occurrenceId: string;
  sequence: number;
  payload: Record<string, unknown>;
}
