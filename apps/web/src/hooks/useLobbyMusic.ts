import { useCallback, useEffect, useRef, useState } from "react";
import lobbyMusicUrl from "../assets/audio/rolecall-lobby-lyria.mp3";

const LOBBY_VOLUME = 0.14;
const FADE_DURATION_MS = 600;
const MUTE_STORAGE_KEY = "rolecall-lobby-music-muted:v1";

export type LobbyMusicStatus = "idle" | "starting" | "playing" | "blocked" | "muted" | "unavailable";

function storedMutePreference() {
  try {
    return window.localStorage.getItem(MUTE_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

function storeMutePreference(muted: boolean) {
  try {
    window.localStorage.setItem(MUTE_STORAGE_KEY, String(muted));
  } catch {
    // Storage can be unavailable in private or restricted browser contexts.
  }
}

export function useLobbyMusic(active: boolean) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const fadeTimerRef = useRef<number | null>(null);
  const activeRef = useRef(active);
  const mutedRef = useRef(storedMutePreference());
  const [muted, setMuted] = useState(mutedRef.current);
  const [status, setStatus] = useState<LobbyMusicStatus>(mutedRef.current ? "muted" : "idle");

  const clearFade = useCallback(() => {
    if (fadeTimerRef.current !== null) {
      window.clearInterval(fadeTimerRef.current);
      fadeTimerRef.current = null;
    }
  }, []);

  const ensureAudio = useCallback(() => {
    if (!audioRef.current) {
      const audio = new Audio(lobbyMusicUrl);
      audio.loop = true;
      audio.preload = "auto";
      audio.volume = LOBBY_VOLUME;
      audio.muted = mutedRef.current;
      audioRef.current = audio;
    }
    return audioRef.current;
  }, []);

  const stop = useCallback((immediate = false) => {
    const audio = audioRef.current;
    clearFade();
    if (!audio) return;

    const reduceMotion = typeof window.matchMedia === "function"
      && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (immediate || audio.paused || reduceMotion) {
      audio.pause();
      audio.currentTime = 0;
      audio.volume = LOBBY_VOLUME;
      return;
    }

    const steps = 10;
    const initialVolume = audio.volume;
    let step = 0;
    fadeTimerRef.current = window.setInterval(() => {
      step += 1;
      audio.volume = Math.max(0, initialVolume * (1 - step / steps));
      if (step >= steps) {
        clearFade();
        audio.pause();
        audio.currentTime = 0;
        audio.volume = LOBBY_VOLUME;
      }
    }, FADE_DURATION_MS / steps);
  }, [clearFade]);

  const play = useCallback(async () => {
    if (!activeRef.current) return;
    const audio = ensureAudio();
    clearFade();
    audio.volume = LOBBY_VOLUME;
    audio.muted = mutedRef.current;
    if (mutedRef.current) {
      setStatus("muted");
      return;
    }

    setStatus("starting");
    try {
      await audio.play();
      if (activeRef.current) setStatus("playing");
    } catch (reason) {
      if (!activeRef.current) return;
      const blocked = reason instanceof DOMException && reason.name === "NotAllowedError";
      setStatus(blocked ? "blocked" : "unavailable");
    }
  }, [clearFade, ensureAudio]);

  useEffect(() => {
    activeRef.current = active;
    if (active) {
      void play();
    } else {
      setStatus(mutedRef.current ? "muted" : "idle");
      stop();
    }
  }, [active, play, stop]);

  useEffect(() => () => {
    activeRef.current = false;
    stop(true);
    audioRef.current = null;
  }, [stop]);

  const toggle = useCallback(() => {
    if (!activeRef.current || status === "unavailable") return;
    if (status === "blocked") {
      mutedRef.current = false;
      setMuted(false);
      storeMutePreference(false);
      void play();
      return;
    }

    const nextMuted = !mutedRef.current;
    mutedRef.current = nextMuted;
    setMuted(nextMuted);
    storeMutePreference(nextMuted);
    const audio = ensureAudio();
    audio.muted = nextMuted;
    if (nextMuted) {
      setStatus("muted");
    } else {
      void play();
    }
  }, [ensureAudio, play, status]);

  return { status, muted, toggle };
}
