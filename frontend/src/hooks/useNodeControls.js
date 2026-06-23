import { useCallback, useState } from 'react';
import { API_BASE } from '../utils/api';

export function useNodeControls({ onStart, onStop } = {}) {
  const [isStarting, setIsStarting] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [error, setError] = useState(null);

  const clearError = () => setError(null);

  const handleStart = useCallback(
    async (config = null) => {
      setIsStarting(true);
      setError(null);

      try {
        const requestOptions = {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        };
        if (config) {
          requestOptions.body = JSON.stringify(config);
        }

        const response = await fetch(`${API_BASE}/nodes/start`, requestOptions);
        if (!response.ok) {
          const errorBody = await response.json();
          throw new Error(errorBody.detail || 'Failed to start nodes');
        }

        onStart?.();
      } catch (e) {
        console.error('Failed to start nodes:', e);
        setError(e.message || 'Failed to start nodes');
      } finally {
        setIsStarting(false);
      }
    },
    [onStart]
  );

  const handleStop = useCallback(async () => {
    setIsStopping(true);
    setError(null);

    try {
      const stopResponse = await fetch(`${API_BASE}/nodes/stop`, { method: 'POST' });
      if (!stopResponse.ok) throw new Error('Failed to stop nodes');

      const clearResponse = await fetch(`${API_BASE}/metrics/clear`);
      if (!clearResponse.ok) throw new Error('Failed to clear metrics');

      onStop?.();
    } catch (e) {
      console.error('Failed to stop nodes:', e);
      setError('Failed to stop nodes');
    } finally {
      setIsStopping(false);
    }
  }, [onStop]);

  return { handleStart, handleStop, isStarting, isStopping, error, clearError };
}
