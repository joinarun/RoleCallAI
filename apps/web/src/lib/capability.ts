import { useEffect, useState } from "react";
import { api, jsonBody } from "./api";

const fragmentTokens = new Map<string, string>();

type CapabilityState =
  | { status: "exchanging" }
  | { status: "ready"; scope: "SEAT"; slotId?: string }
  | { status: "error"; message: string };

type CapabilitySession = {
  roomId: string;
  scope: "SEAT";
  slotId?: string;
};

export function useCapability(roomId: string, expectedScope: "SEAT"): CapabilityState {
  const [state, setState] = useState<CapabilityState>({ status: "exchanging" });

  useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams(window.location.hash.slice(1));
    const fragmentToken = params.get("cap");
    if (fragmentToken) {
      fragmentTokens.set(roomId, fragmentToken);
      history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
    }
    const token = fragmentToken ?? fragmentTokens.get(roomId);

    function accept(session: CapabilitySession) {
      if (session.roomId !== roomId || session.scope !== expectedScope) {
        throw new Error("The current private link belongs to a different room.");
      }
      if (!cancelled) setState({ status: "ready", ...session });
    }

    async function exchangeToken(capabilityToken: string) {
      const session = await api<CapabilitySession>("/v1/capability-sessions", {
        method: "POST",
        ...jsonBody({ roomId, token: capabilityToken }),
      });
      fragmentTokens.delete(roomId);
      accept(session);
    }

    async function exchange() {
      try {
        if (token) {
          await exchangeToken(token);
          return;
        }
        accept(await api<CapabilitySession>("/v1/capability-sessions/current"));
      } catch {
        if (!cancelled) {
          setState({
            status: "error",
            message: "Open the original private link or choose the room from your home workspace.",
          });
        }
      }
    }
    void exchange();
    return () => {
      cancelled = true;
    };
  }, [roomId, expectedScope]);

  return state;
}
