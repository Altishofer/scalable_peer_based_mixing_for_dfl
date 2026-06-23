import { useState, useCallback, useMemo } from 'react';
import { getDefaultConfig, validateConfig, CONFIG_SCHEMA } from '../models/configModels';

export function useExperimentConfig() {
  const [config, setConfig] = useState(getDefaultConfig);
  const [errors, setErrors] = useState({});

  const updateConfig = useCallback((key, value) => {
    if (!CONFIG_SCHEMA[key]) return;

    setConfig((prev) => {
      const next = { ...prev, [key]: value };

      Object.entries(CONFIG_SCHEMA).forEach(([otherKey, otherSchema]) => {
        if (otherSchema.visibleWhen && !otherSchema.visibleWhen(next)) {
          next[otherKey] = otherSchema.default;
        }
      });

      setErrors(validateConfig(next).errors);
      return next;
    });
  }, []);

  const isValid = useMemo(() => Object.keys(errors).length === 0, [errors]);

  // coerce form strings to the types the backend expects
  const getConfigForSubmit = useCallback(() => {
    const merged = { ...getDefaultConfig(), ...config };
    const result = {};
    Object.entries(merged).forEach(([key, value]) => {
      const schema = CONFIG_SCHEMA[key];
      if (!schema) return;
      if (schema.type === 'int') {
        result[key] = parseInt(value, 10);
      } else if (schema.type === 'float') {
        result[key] = parseFloat(value);
      } else {
        result[key] = value;
      }
    });
    return result;
  }, [config]);

  return { config, errors, isValid, updateConfig, getConfigForSubmit };
}
