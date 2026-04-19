import { useCallback, useEffect, useRef, useState } from "react";
import { getPatients } from "../lib/api";
import type { PatientSummary } from "../types";

export function usePollingPatients(
  hospitalId: string,
  pin: string | null,
  intervalMs = 10_000,
  status: "waiting" | "all" = "waiting"
) {
  const [patients, setPatients] = useState<PatientSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const backoffRef = useRef(1_000);

  const fetchOnce = useCallback(async () => {
    if (!pin) return;
    try {
      const { patients } = await getPatients(hospitalId, pin, status);
      setPatients(patients);
      setError(null);
      backoffRef.current = 1_000;
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err?.message || "Failed to load patients";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [hospitalId, pin, status]);

  useEffect(() => {
    if (!pin) return;
    let cancelled = false;
    let timer: number | null = null;

    const loop = async () => {
      if (cancelled) return;
      if (document.hidden) {
        timer = window.setTimeout(loop, intervalMs);
        return;
      }
      await fetchOnce();
      timer = window.setTimeout(loop, error ? Math.min(backoffRef.current *= 2, 30_000) : intervalMs);
    };

    loop();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [pin, fetchOnce, intervalMs, error]);

  return { patients, loading, error, refetch: fetchOnce };
}
