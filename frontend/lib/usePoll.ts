"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { get } from "./api";

/** Poll an API path every `ms` milliseconds. Returns data, error and a manual refresh. */
export function usePoll<T>(path: string | null, ms = 2500) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);

  const refresh = useCallback(async () => {
    if (!path) return;
    try {
      const d = await get<T>(path);
      if (alive.current) {
        setData(d);
        setError(null);
      }
    } catch (e) {
      if (alive.current) setError((e as Error).message);
    }
  }, [path]);

  useEffect(() => {
    alive.current = true;
    refresh();
    const t = setInterval(refresh, ms);
    return () => {
      alive.current = false;
      clearInterval(t);
    };
  }, [refresh, ms]);

  return { data, error, refresh };
}
