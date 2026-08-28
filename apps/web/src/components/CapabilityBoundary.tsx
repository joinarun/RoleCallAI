import type { ReactNode } from "react";
import { KeyRound, LoaderCircle } from "lucide-react";
import { useCapability } from "../lib/capability";

export function CapabilityBoundary({
  roomId,
  expected,
  children,
}: {
  roomId: string;
  expected: "ADMIN" | "SEAT";
  children: (slotId?: string) => ReactNode;
}) {
  const state = useCapability(roomId, expected);
  if (state.status === "exchanging") {
    return <div className="center-card" aria-live="polite"><LoaderCircle className="spin" /><h1>Opening your private room…</h1><p>Exchanging the link without putting its secret in browser history.</p></div>;
  }
  if (state.status === "error" || state.scope !== expected) {
    return <div className="center-card error-card" role="alert"><KeyRound /><h1>This link can’t be used</h1><p>{state.status === "error" ? state.message : "This capability has the wrong room scope."}</p><small>Links cannot be recovered in Phase 1. Ask the room admin to regenerate a participant link.</small></div>;
  }
  return <>{children(state.slotId)}</>;
}
