import type { OccurrenceStatus } from "../types";

export function StatusBadge({ status }: { status: OccurrenceStatus | "IDLE" }) {
  const tone = status === "COMPLETED" ? "good" : status === "FAILED" ? "bad" : status === "RUNNING" || status === "ENDING" ? "live" : "pending";
  return <span className={`badge ${tone}`}><span className="badge-dot" />{status.replaceAll("_", " ")}</span>;
}
