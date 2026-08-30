import type { DocumentStatus, OccurrenceStatus, RuntimeStatus } from "../types";

export function StatusBadge({ status }: { status: OccurrenceStatus | DocumentStatus | RuntimeStatus | "IDLE" }) {
  const tone = status === "COMPLETED" || status === "READY" ? "good" : status === "FAILED" || status === "ERROR" ? "bad" : status === "RUNNING" || status === "ENDING" ? "live" : "pending";
  return <span className={`badge ${tone}`}><span className="badge-dot" />{status.replaceAll("_", " ")}</span>;
}
