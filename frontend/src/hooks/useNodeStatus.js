import { useState, useEffect } from 'react';
import { API_BASE } from '../utils/api';

export function useNodeStatus(pollInterval = 3000) {
  const [nodes, setNodes] = useState([]);

  useEffect(() => {
    const poll = () =>
      fetch(`${API_BASE}/nodes/status`)
        .then((r) => r.json())
        .then((data) => setNodes(Array.isArray(data) ? data : []))
        .catch(() => {});

    poll();

    const intervalId = setInterval(poll, pollInterval);
    return () => clearInterval(intervalId);
  }, [pollInterval]);

  const isRunning = nodes.length > 0;

  return { nodes, isRunning };
}
