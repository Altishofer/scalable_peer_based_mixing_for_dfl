import { useState, useEffect, useRef } from 'react';
import { API_BASE } from '../utils/api';

export function useScenarioIndicators(config) {
  const [indicators, setIndicators] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const abortRef = useRef(null);

  useEffect(() => {
    // debounce config changes; cancel any in-flight request from the previous value
    const timer = setTimeout(() => {
      if (abortRef.current) abortRef.current.abort();

      const controller = new AbortController();
      abortRef.current = controller;
      setIsLoading(true);

      fetch(`${API_BASE}/nodes/config/indicators`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
        signal: controller.signal,
      })
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => {
          if (data) setIndicators(data);
        })
        .catch((err) => {
          if (err.name !== 'AbortError') setIndicators(null);
        })
        .finally(() => setIsLoading(false));
    }, 300);

    return () => {
      clearTimeout(timer);
      if (abortRef.current) abortRef.current.abort();
    };
  }, [config]);

  return { indicators, isLoading };
}
