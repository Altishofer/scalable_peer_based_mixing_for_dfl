import React, { useState } from 'react';
import { useNodeStatus } from './hooks/useNodeStatus';
import { useMetricsStream } from './hooks/useMetricsStream';
import { useMetricsIndex } from './hooks/useMetricsIndex';
import { useNodeControls } from './hooks/useNodeControls';
import { useExperimentConfig } from './hooks/useExperimentConfig';
import { useScenarioIndicators } from './hooks/useScenarioIndicators';
import { ConfigPanel } from './components/ConfigPanel/ConfigPanel';
import { ScenarioIndicators } from './components/ScenarioIndicators/ScenarioIndicators';
import { NodeStatusTable } from './components/NodeStatusTable/NodeStatusTable';
import { MetricsSidebar } from './components/MetricsSidebar/MetricsSidebar';
import { ChartsGrid } from './components/ChartsGrid/ChartsGrid';
import { createColorMap } from './utils/colors';
import styles from './Dashboard.module.css';

export default function Dashboard() {
  const [selectedMetrics, setSelectedMetrics] = useState([]);
  const { nodes, isRunning } = useNodeStatus();
  const { metrics, clearMetrics } = useMetricsStream();
  const {
    config,
    errors: configErrors,
    isValid: isConfigValid,
    updateConfig,
    getConfigForSubmit,
  } = useExperimentConfig();
  const { indicators, isLoading: indicatorsLoading } = useScenarioIndicators(config);
  const {
    nodeNames: indexedNodeNames,
    metricInfo,
    currentRounds,
    chartIndex,
  } = useMetricsIndex(metrics);

  function handleReset() {
    clearMetrics();
    setSelectedMetrics([]);
  }

  const {
    handleStart: startNodes,
    handleStop,
    isStarting,
    isStopping,
    error: controlsError,
    clearError,
  } = useNodeControls({
    onStart: handleReset,
    onStop: handleReset,
  });

  function handleStart() {
    if (isConfigValid) startNodes(getConfigForSubmit());
  }

  function toggleMetric(field) {
    setSelectedMetrics((prev) =>
      prev.includes(field) ? prev.filter((m) => m !== field) : [...prev, field]
    );
  }

  const nodeNameSet = new Set(indexedNodeNames);
  nodes.forEach((node) => {
    if (node.name) nodeNameSet.add(node.name);
  });
  const nodeNames = [...nodeNameSet].sort();
  const nodeColors = createColorMap(nodeNames);

  const metricsByGroup = {};
  Object.entries(metricInfo).forEach(([field, info]) => {
    if (!metricsByGroup[info.group]) metricsByGroup[info.group] = [];
    metricsByGroup[info.group].push({ field, ...info });
  });

  const chartData = {};
  selectedMetrics.forEach((field) => {
    chartData[field] = chartIndex[field] || [];
  });

  const disabled = isRunning || isStarting;

  return (
    <div className={styles.container}>
      {controlsError && (
        <div className={styles.banner} onClick={clearError}>
          {controlsError}
        </div>
      )}

      <header className={styles.header}>
        <h1 className={styles.title}>MixDfl</h1>
        <div className={styles.controls}>
          <button
            className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={handleStart}
            disabled={isRunning || isStopping || !isConfigValid}
          >
            {isStarting ? 'Starting...' : 'Start'}
          </button>
          <button
            className={`${styles.btn} ${styles.btnDanger}`}
            onClick={handleStop}
            disabled={(!isRunning && !isStopping) || isStarting}
          >
            {isStopping ? 'Stopping...' : 'Stop'}
          </button>
        </div>
      </header>

      <ConfigPanel
        config={config}
        errors={configErrors}
        onUpdate={updateConfig}
        disabled={disabled}
        isRunning={isRunning}
        adjacency={indicators?.topology?.adjacency}
      />
      <ScenarioIndicators indicators={indicators} isLoading={indicatorsLoading} />
      <NodeStatusTable nodes={nodes} nodeColors={nodeColors} currentRounds={currentRounds} />

      <div className={styles.metricsLayout}>
        <MetricsSidebar
          metricsByGroup={metricsByGroup}
          selectedMetrics={selectedMetrics}
          onToggle={toggleMetric}
        />
        <ChartsGrid
          selectedMetrics={selectedMetrics}
          metricInfo={metricInfo}
          chartData={chartData}
          nodeNames={nodeNames}
          nodeColors={nodeColors}
        />
      </div>
    </div>
  );
}
