import React from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import styles from './ChartsGrid.module.css';

function Chart({ title, unit, data, nodeNames, nodeColors }) {
  return (
    <div className={styles.card}>
      <h3 className={styles.cardTitle}>
        {title} {unit && <span className={styles.unit}>({unit})</span>}
      </h3>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
          <XAxis dataKey="time" fontSize={11} tick={{ fill: 'var(--color-text-secondary)' }} />
          <YAxis fontSize={11} tick={{ fill: 'var(--color-text-secondary)' }} />
          <Tooltip />
          <Legend />
          {nodeNames.map((node) => (
            <Line
              key={node}
              type="monotone"
              dataKey={node}
              stroke={nodeColors[node]}
              dot={false}
              strokeWidth={2}
              isAnimationActive={false}
              connectNulls
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function ChartsGrid({ selectedMetrics, metricInfo, chartData, nodeNames, nodeColors }) {
  if (selectedMetrics.length === 0) {
    return (
      <div className={styles.charts}>
        <div className={styles.card}>
          <p className={styles.emptyState}>Select metrics to display charts</p>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.charts}>
      <div className={styles.chartsGrid}>
        {selectedMetrics
          .filter((metricKey) => metricInfo[metricKey])
          .map((metric) => (
            <Chart
              key={metric}
              title={metricInfo[metric].name}
              unit={metricInfo[metric].unit}
              data={chartData[metric] || []}
              nodeNames={nodeNames}
              nodeColors={nodeColors}
            />
          ))}
      </div>
    </div>
  );
}
