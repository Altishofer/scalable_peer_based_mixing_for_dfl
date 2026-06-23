import React from 'react';
import styles from './MetricsSidebar.module.css';

export function MetricsSidebar({ metricsByGroup, selectedMetrics, onToggle }) {
  return (
    <aside className={styles.sidebar}>
      <h3 className={styles.sidebarTitle}>Metrics</h3>
      {Object.keys(metricsByGroup).length === 0 ? (
        <p className={styles.emptyState}>No metrics yet</p>
      ) : (
        Object.entries(metricsByGroup)
          .sort()
          .map(([group, items]) => (
            <div key={group} className={styles.metricGroup}>
              <div className={styles.metricGroupTitle}>{group}</div>
              {items.map(({ field, name }) => (
                <label key={field} className={styles.metricItem}>
                  <input
                    type="checkbox"
                    checked={selectedMetrics.includes(field)}
                    onChange={() => onToggle(field)}
                  />
                  {name}
                </label>
              ))}
            </div>
          ))
      )}
    </aside>
  );
}
