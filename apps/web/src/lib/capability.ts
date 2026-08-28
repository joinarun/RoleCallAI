import { useEffect, useState } from "react";
import { api, jsonBody } from "./api";

const fragmentTokens = new Map<string, string>();

type CapabilityState =
  | { status: "exchanging" }
  | { status: "ready"; scope: "ADMIN" | "SEAT"; slotId?: string }
  | { status: "error"; message: string };

export function useCapability(roomId: string, expectedScope: "ADMIN" | "SEAT"): CapabilityState {
  const [state, setState] = useState<CapabilityState>({ status: "exchanging" });

  useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams(window.location.hash.slice(1));
    const fragmentToken = params.get("cap");
    if (fragmentToken) {
      fragmentTokens.set(roomId, fragmentToken);
      history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
    }
    const token = fragmentToken ?? fragmentTokens.get(roomId) ?? null;

    async function exchange() {
      try {
        if (token) {
          const session = await api<{ scope: "ADMIN" | "SEAT"; slotId?: string }>(
            "/v1/capability-sessions",
            { method: "POST", ...jsonBody({ roomId, token }) },
          );
          if (!cancelled) {
            fragmentTokens.delete(roomId);
            setState({ status: "ready", ...session });
          }
          return;
        }
        const session = await api<{ scope: "ADMIN" | "SEAT"; slotId?: string }>(
          "/v1/capability-sessions/current",
        );
        if (!cancelled) setState({ status: "ready", ...session });
      } catch (error) {
        const message = error instanceof Error ? error.message : "This capability link is invalid or expired.";
        if (!cancelled) setState({ status: "error", message });
      }
    }
    void exchange();
    return () => {
      cancelled = true;
    };
  }, [roomId, expectedScope]);

  return state;
}
