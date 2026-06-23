import React from 'react';
import styles from './NodeStatusTable.module.css';

export function NodeStatusTable({ nodes, nodeColors, currentRounds }) {
  return (
    <div className={styles.card}>
      <h2 className={styles.cardTitle}>Nodes ({nodes.length})</h2>
      {nodes.length === 0 ? (
        <p className={styles.emptyState}>No nodes running</p>
      ) : (
        <table className={styles.table}>
          <caption className={styles.srOnly}>Node status and current round</caption>
          <thead>
            <tr>
              <th>Node</th>
              <th>Status</th>
              <th>Round</th>
            </tr>
          </thead>
          <tbody>
            {nodes.map((node) => (
              <tr key={node.name}>
                <td>
                  <span className={styles.colorDot} style={{ background: nodeColors[node.name] }} />
                  {node.name}
                </td>
                <td>
                  <span className={styles.status}>
                    <span
                      className={`${styles.statusDot} ${node.status === 'running' ? styles.running : styles.stopped}`}
                    />
                    {node.status}
                  </span>
                </td>
                <td>{currentRounds[node.name] ?? '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
