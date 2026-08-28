import type { ReactNode } from "react";
import { ArrowLeft, KeyRound, LoaderCircle } from "lucide-react";
import { Link } from "react-router-dom";
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
    return <div className="center-card error-card" role="alert"><KeyRound /><h1>This private link is unavailable</h1><p>{state.status === "error" ? state.message : "Open the matching room link from your home workspace."}</p><Link className="button primary" to="/"><ArrowLeft /> Return home</Link></div>;
  }
  return <>{children(state.slotId)}</>;
}
