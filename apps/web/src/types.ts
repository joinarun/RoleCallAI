export type RoleType = "SCRUM_MASTER" | "FUN_FRIDAY" | "BRAINSTORM" | "CUSTOM";
export type GameType = "AUTO" | "RAPID_FIRE_TRIVIA" | "WOULD_YOU_RATHER" | "CATEGORIES";
export type OccurrenceStatus =
  | "LOBBY"
  | "STARTING"
  | "RUNNING"
  | "ENDING"
  | "PROCESSING"
  | "COMPLETED"
  | "FAILED";

export interface Seat {
  id: string;
  ordinal: number;
  lastDisplayName?: string | null;
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
  generatedAt: string;
}

export interface Attendance {
  slotId: string;
  displayName: string;
  consentVersion: string;
  joinedAt: string;
  connected: boolean;
  connectionId: string;
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
  handRaiseQueue: string[];
  recap?: Recap | null;
  sequence: number;
}

export interface RoomCreated {
  room: Room;
  adminUrl: string;
  seatUrls: Array<{ slotId: string; url: string }>;
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
  type: "meeting.state" | "hand.raise" | "caption.final" | "recap.ready";
  occurrenceId: string;
  sequence: number;
  payload: Record<string, unknown>;
}
