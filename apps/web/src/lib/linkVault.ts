import type { RoomCreated } from "../types";

const ROOM_PREFIX = "rolecall-links:";
const LAST_SEAT_PREFIX = "rolecall-last-seat:";

function validRoomLinks(value: unknown): value is RoomCreated {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<RoomCreated>;
  return Boolean(
    candidate.room?.id &&
      typeof candidate.adminUrl === "string" &&
      Array.isArray(candidate.seatUrls),
  );
}

export function loadRoomLinks(roomId: string): RoomCreated | null {
  try {
    const saved = sessionStorage.getItem(`${ROOM_PREFIX}${roomId}`);
    if (!saved) return null;
    const parsed: unknown = JSON.parse(saved);
    return validRoomLinks(parsed) && parsed.room.id === roomId ? parsed : null;
  } catch {
    return null;
  }
}

export function listRoomLinks(): RoomCreated[] {
  const rooms: RoomCreated[] = [];
  try {
    for (let index = 0; index < sessionStorage.length; index += 1) {
      const key = sessionStorage.key(index);
      if (!key?.startsWith(ROOM_PREFIX)) continue;
      const room = loadRoomLinks(key.slice(ROOM_PREFIX.length));
      if (room) rooms.push(room);
    }
  } catch {
    return [];
  }
  return rooms.sort((left, right) => right.room.createdAt.localeCompare(left.room.createdAt));
}

export function saveRoomLinks(value: RoomCreated): void {
  try {
    sessionStorage.setItem(`${ROOM_PREFIX}${value.room.id}`, JSON.stringify(value));
  } catch {
    // The one-time link vault remains visible even if browser storage is disabled.
  }
}

export function removeRoomLinks(roomId: string): void {
  try {
    sessionStorage.removeItem(`${ROOM_PREFIX}${roomId}`);
    sessionStorage.removeItem(`${LAST_SEAT_PREFIX}${roomId}`);
  } catch {
    // Nothing else is required when browser storage is unavailable.
  }
}

export function rememberSeat(roomId: string, slotId: string): void {
  try {
    sessionStorage.setItem(`${LAST_SEAT_PREFIX}${roomId}`, slotId);
  } catch {
    // The active HttpOnly capability cookie remains the primary credential.
  }
}

export function capabilityToken(url: string): string | null {
  try {
    return new URLSearchParams(new URL(url, window.location.origin).hash.slice(1)).get("cap");
  } catch {
    return null;
  }
}

export function storedCapabilityToken(
  roomId: string,
  expectedScope: "ADMIN" | "SEAT",
): string | null {
  const links = loadRoomLinks(roomId);
  if (!links) return null;
  if (expectedScope === "ADMIN") return capabilityToken(links.adminUrl);
  try {
    const slotId = sessionStorage.getItem(`${LAST_SEAT_PREFIX}${roomId}`);
    const seatUrl = links.seatUrls.find((item) => item.slotId === slotId)?.url;
    return seatUrl ? capabilityToken(seatUrl) : null;
  } catch {
    return null;
  }
}
