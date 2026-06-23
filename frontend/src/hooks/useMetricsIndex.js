import { useMemo } from 'react';

export function useMetricsIndex(metrics) {
  return useMemo(() => {
    const nodes = new Set();
    const metricInfo = {};
    const currentRounds = {};
    const byField = {};

    for (const metric of metrics) {
      if (metric.node) nodes.add(metric.node);

      if (metric.field && !metricInfo[metric.field]) {
        metricInfo[metric.field] = {
          name: metric.name || metric.field,
          group: metric.group || 'Other',
          unit: metric.unit || '',
        };
      }

      if (metric.field === 'current_round') {
        currentRounds[metric.node] = metric.value;
      }

      if (metric.field) {
        if (!byField[metric.field]) byField[metric.field] = {};
        const timestampMs = metric.timestamp ? new Date(metric.timestamp).getTime() : 0;
        if (!byField[metric.field][timestampMs]) {
          byField[metric.field][timestampMs] = {
            time: metric.timestamp ? new Date(metric.timestamp).toLocaleTimeString() : '',
            _ts: timestampMs,
          };
        }
        byField[metric.field][timestampMs][metric.node] = metric.value;
      }
    }

    const chartIndex = {};
    for (const [field, byTimestamp] of Object.entries(byField)) {
      chartIndex[field] = Object.values(byTimestamp).sort((a, b) => a._ts - b._ts);
    }

    return {
      nodeNames: [...nodes].sort(),
      metricInfo,
      currentRounds,
      chartIndex,
    };
  }, [metrics]);
}
