import { useState, useEffect, useRef, useCallback } from 'react';
import { API_BASE, MAX_METRICS, fetchMetricsHistory } from '../utils/api';

export function useMetricsStream() {
  const [metrics, setMetrics] = useState([]);
  const lastTimestampRef = useRef(null);

  useEffect(() => {
    let eventSource = null;

    const init = async () => {
      try {
        const allMetrics = [];
        let offset = 0;
        let hasMore = true;

        while (hasMore) {
          const result = await fetchMetricsHistory(offset, 50000);
          allMetrics.push(...result.metrics);
          hasMore = result.has_more;
          offset += result.metrics.length;
        }

        if (allMetrics.length > 0) {
          const maxTs = allMetrics.reduce(
            (max, m) => (m.timestamp > max ? m.timestamp : max),
            allMetrics[0].timestamp
          );
          lastTimestampRef.current = maxTs;
        }

        setMetrics(allMetrics.slice(-MAX_METRICS));
      } catch (err) {
        console.warn('Failed to load metrics history:', err);
        return;
      }

      eventSource = new EventSource(`${API_BASE}/metrics/sse`);

      eventSource.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          // payload may be array or wrapped in .data
          const incoming = Array.isArray(data) ? data : data?.data;
          if (!Array.isArray(incoming) || incoming.length === 0) return;

          const fresh = lastTimestampRef.current
            ? incoming.filter((m) => !m.timestamp || m.timestamp > lastTimestampRef.current)
            : incoming;
          if (fresh.length === 0) return;

          const maxTs = fresh.reduce(
            (max, m) => (m.timestamp > max ? m.timestamp : max),
            fresh[0].timestamp
          );
          if (!lastTimestampRef.current || maxTs > lastTimestampRef.current) {
            lastTimestampRef.current = maxTs;
          }

          setMetrics((prev) => [...prev, ...fresh].slice(-MAX_METRICS));
        } catch (err) {
          console.warn('SSE parse error:', err);
        }
      };
    };

    init();
    return () => eventSource?.close();
  }, []);

  const clearMetrics = useCallback(() => {
    setMetrics([]);
    lastTimestampRef.current = null;
  }, []);

  return { metrics, clearMetrics };
}
