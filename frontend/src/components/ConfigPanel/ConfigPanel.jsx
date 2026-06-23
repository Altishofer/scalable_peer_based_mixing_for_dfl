import React from 'react';
import { CONFIG_SCHEMA } from '../../models/configModels';
import { TopologyGraph } from '../TopologyGraph/TopologyGraph';
import styles from './ConfigPanel.module.css';

const SECTION_META = {
  learning: { title: 'Learning' },
  network: { title: 'Network' },
  mixnet: { title: 'Mixnet' },
};

const FIELDS_BY_SECTION = {};
for (const [key, schema] of Object.entries(CONFIG_SCHEMA)) {
  const sectionName = schema.section;
  if (!FIELDS_BY_SECTION[sectionName]) FIELDS_BY_SECTION[sectionName] = [];
  FIELDS_BY_SECTION[sectionName].push([key, schema]);
}

function SelectField({ id, schema, value, error, disabled, onChange }) {
  const hasError = Boolean(error);
  return (
    <div className={styles.field}>
      <label htmlFor={id} className={styles.label}>
        <span className={styles.labelText}>{schema.label}</span>
        <div className={styles.inputWrapper}>
          <select
            id={id}
            value={value}
            onChange={onChange}
            disabled={disabled}
            className={`${styles.input} ${hasError ? styles.inputError : ''}`}
          >
            {schema.options.map((opt) => (
              <option key={opt} value={opt}>
                {schema.optionLabels?.[opt] || String(opt).replace(/_/g, ' ')}
              </option>
            ))}
          </select>
        </div>
      </label>
      {hasError && <span className={styles.error}>{error}</span>}
    </div>
  );
}

function NumericField({ id, schema, value, error, disabled, onChange }) {
  const hasError = Boolean(error);
  return (
    <div className={styles.field}>
      <label htmlFor={id} className={styles.label}>
        <span className={styles.labelText}>{schema.label}</span>
        <div className={styles.inputWrapper}>
          <input
            id={id}
            type="number"
            value={value}
            onChange={onChange}
            min={schema.min}
            max={schema.max}
            step={schema.type === 'float' ? 0.001 : 1}
            disabled={disabled}
            className={`${styles.input} ${hasError ? styles.inputError : ''}`}
          />
        </div>
      </label>
      {hasError && <span className={styles.error}>{error}</span>}
    </div>
  );
}

function ToggleField({ id, schema, checked, disabled, onChange }) {
  return (
    <div className={styles.toggleField}>
      <label htmlFor={id} className={styles.toggleSwitch}>
        <input
          id={id}
          type="checkbox"
          checked={checked}
          onChange={onChange}
          disabled={disabled}
          className={styles.toggleInput}
        />
        <span className={styles.toggleSlider}></span>
      </label>
      <div className={styles.toggleContent}>
        <div className={styles.toggleLabel}>{schema.label}</div>
      </div>
    </div>
  );
}

export function ConfigPanel({ config, errors, onUpdate, disabled, isRunning, adjacency }) {
  const hasErrors = Object.keys(errors).length > 0;

  const handleInputChange = (key, e) => {
    const schema = CONFIG_SCHEMA[key];
    if (schema.type === 'bool') {
      onUpdate(key, e.target.checked);
    } else {
      onUpdate(key, e.target.value);
    }
  };

  const renderField = (key, schema) => {
    if (schema.visibleWhen && !schema.visibleWhen(config)) return null;

    // mixnet sub-fields locked until mix_enabled is on
    const fieldDisabled =
      disabled || (schema.section === 'mixnet' && key !== 'mix_enabled' && !config.mix_enabled);
    const fieldId = `config-${key}`;

    if (schema.type === 'bool') {
      return (
        <ToggleField
          key={key}
          id={fieldId}
          schema={schema}
          checked={config[key]}
          disabled={fieldDisabled}
          onChange={(e) => handleInputChange(key, e)}
        />
      );
    }
    if (schema.type === 'select') {
      return (
        <SelectField
          key={key}
          id={fieldId}
          schema={schema}
          value={config[key]}
          error={errors[key]}
          disabled={fieldDisabled}
          onChange={(e) => handleInputChange(key, e)}
        />
      );
    }
    return (
      <NumericField
        key={key}
        id={fieldId}
        schema={schema}
        value={config[key]}
        error={errors[key]}
        disabled={fieldDisabled}
        onChange={(e) => handleInputChange(key, e)}
      />
    );
  };

  const getBadgeClass = () => {
    if (isRunning) return styles.badgeRunning;
    if (hasErrors) return styles.badgeError;
    return styles.badgeReady;
  };

  const getBadgeText = () => {
    if (isRunning) return 'Running';
    if (hasErrors) return 'Invalid';
    return 'Ready';
  };

  const renderSectionFooter = (sectionKey) => {
    if (sectionKey === 'network' && adjacency) {
      return (
        <div style={{ marginTop: '0.75rem' }}>
          <TopologyGraph adjacency={adjacency} />
        </div>
      );
    }
    return null;
  };

  return (
    <div className={`${styles.panel} ${disabled ? styles.disabled : ''}`}>
      <div className={styles.header}>
        <h2 className={styles.title}>Configuration</h2>
        <span className={`${styles.badge} ${getBadgeClass()}`}>{getBadgeText()}</span>
      </div>

      <div className={styles.sectionsGrid}>
        {Object.entries(SECTION_META).map(([sectionKey, meta]) => (
          <section key={sectionKey} className={styles.section}>
            <h3 className={styles.sectionTitle}>{meta.title}</h3>
            <div className={styles.fieldsGrid}>
              {(FIELDS_BY_SECTION[sectionKey] || []).map(([key, schema]) =>
                renderField(key, schema)
              )}
            </div>
            {renderSectionFooter(sectionKey)}
          </section>
        ))}
      </div>
    </div>
  );
}
