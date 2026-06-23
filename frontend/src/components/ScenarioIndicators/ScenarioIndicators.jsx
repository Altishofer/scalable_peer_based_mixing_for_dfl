import React from 'react';
import styles from './ScenarioIndicators.module.css';

function formatBytes(bytes) {
  if (bytes >= 1e9) return (bytes / 1e9).toFixed(1) + ' GB';
  if (bytes >= 1e6) return (bytes / 1e6).toFixed(1) + ' MB';
  if (bytes >= 1e3) return (bytes / 1e3).toFixed(1) + ' KB';
  return bytes + ' B';
}

function formatRate(rate) {
  if (rate >= 1e3) return (rate / 1e3).toFixed(1) + 'K pkt/s';
  return rate + ' pkt/s';
}

function formatTime(seconds) {
  if (seconds >= 60) return (seconds / 60).toFixed(1) + ' min';
  if (seconds >= 1) return seconds.toFixed(1) + ' s';
  return Math.round(seconds * 1000) + ' ms';
}

function formatParams(params) {
  if (params >= 1e6) return (params / 1e6).toFixed(1) + 'M';
  if (params >= 1e3) return Math.round(params / 1e3) + 'K';
  return String(params);
}

const ENTROPY_BANDS = [
  { max: 5, label: 'Very Weak', color: '#dc2626' },
  { max: 10, label: 'Weak', color: '#ea580c' },
  { max: 15, label: 'Moderate', color: '#eab308' },
  { max: 20, label: 'Strong', color: '#16a34a' },
  { max: 25, label: 'Very Strong', color: '#15803d' },
];

const BAR_MAX = 25; // top of the bits scale the bar spans

function EntropyBar({ bits, enabled }) {
  const markerPercent = enabled ? Math.min((bits / BAR_MAX) * 100, 100) : 0;

  return (
    <div className={`${styles.barContainer} ${!enabled ? styles.barDisabled : ''}`}>
      <div className={styles.barTrack}>
        {ENTROPY_BANDS.map((band, i) => {
          const bandStart = i > 0 ? ENTROPY_BANDS[i - 1].max : 0;
          const widthPercent = ((band.max - bandStart) / BAR_MAX) * 100;

          return (
            <div
              key={i}
              className={styles.barSegment}
              style={{
                width: `${widthPercent}%`,
                backgroundColor: enabled ? band.color : '#d1d5db',
              }}
            />
          );
        })}
        {enabled && (
          <div className={styles.barMarker} style={{ left: `${markerPercent}%` }}>
            <div className={styles.markerLine} />
          </div>
        )}
      </div>
      {!enabled && <div className={styles.barLabel}>Mixnet disabled</div>}
    </div>
  );
}

function Stat({ label, value, muted }) {
  return (
    <div className={styles.stat}>
      <span className={styles.statLabel}>{label}</span>
      <span className={`${styles.statValue} ${muted ? styles.muted : ''}`}>{value}</span>
    </div>
  );
}

function KrumBadge({ aggregation, krumSafe, hasAttack }) {
  if (!hasAttack) return null;
  if (aggregation !== 'krum') {
    return <span className={`${styles.badge} ${styles.badgeDanger}`}>No Defense</span>;
  }
  if (krumSafe) {
    return <span className={`${styles.badge} ${styles.badgeSuccess}`}>Protected</span>;
  }
  return <span className={`${styles.badge} ${styles.badgeWarning}`}>At Risk</span>;
}

function LoadingSkeleton() {
  return (
    <div className={styles.skeletonGrid}>
      {[0, 1, 2].map((i) => (
        <div key={i} className={styles.skeletonGroup}>
          <div className={styles.skeletonBar} style={{ width: '40%' }} />
          <div className={styles.skeletonBar} />
          <div className={styles.skeletonBar} style={{ width: '70%' }} />
          <div className={styles.skeletonBar} style={{ width: '85%' }} />
        </div>
      ))}
    </div>
  );
}

export function ScenarioIndicators({ indicators, isLoading }) {
  if (isLoading && !indicators) {
    return (
      <div className={styles.card}>
        <h2 className={styles.title}>Scenario Indicators</h2>
        <LoadingSkeleton />
      </div>
    );
  }

  if (indicators?.error) {
    return (
      <div className={`${styles.card} ${styles.cardError}`}>
        <h2 className={styles.title}>Scenario Indicators</h2>
        <p className={styles.errorMessage}>{indicators.error}</p>
      </div>
    );
  }

  if (!indicators) return null;

  const { topology, anonymity, communication, mixnet_traffic, robustness } = indicators;

  return (
    <div className={`${styles.card} ${isLoading ? styles.loading : ''}`}>
      <h2 className={styles.title}>Scenario Indicators</h2>

      <div className={styles.grid}>
        <div className={styles.group}>
          <h3 className={styles.groupTitle}>Topology</h3>
          <Stat label="Transport connections" value={topology.degree} />
          <Stat label="Transport diameter" value={topology.diameter} />
          <Stat label="Overlay degree" value={topology.exchange_peers} />
        </div>

        <div className={styles.group}>
          <h3 className={styles.groupTitle}>Anonymity</h3>
          <EntropyBar bits={anonymity.path_entropy_bits} enabled={anonymity.mix_enabled} />
          <Stat
            label="Path entropy"
            value={anonymity.mix_enabled ? `${anonymity.path_entropy_bits} bits` : '\u2014'}
            muted={!anonymity.mix_enabled}
          />
          <Stat
            label="Relay entropy"
            value={anonymity.mix_enabled ? `${anonymity.relay_entropy_bits} bits` : '\u2014'}
            muted={!anonymity.mix_enabled}
          />
          <Stat
            label="Anonymity set"
            value={anonymity.mix_enabled ? anonymity.anonymity_set_size : '\u2014'}
            muted={!anonymity.mix_enabled}
          />
        </div>

        <div className={styles.group}>
          <h3 className={styles.groupTitle}>Communication</h3>
          <Stat label="Model params" value={formatParams(communication.model_params)} />
          <Stat label="Sphinx payload" value={formatBytes(communication.sphinx_payload_size)} />
          <Stat label="Sphinx packet" value={formatBytes(communication.sphinx_packet_size)} />
          <Stat label="Fragments" value={communication.fragments_per_model} />
          <Stat
            label="Msgs / node / round"
            value={communication.messages_per_node.toLocaleString()}
          />
          <Stat label="Bytes / round" value={formatBytes(communication.bytes_per_round)} />
          <Stat
            label="Partial update ratio"
            value={`${(communication.partial_update_ratio * 100).toFixed(0)}%`}
          />
        </div>

        {mixnet_traffic && (
          <div className={styles.group}>
            <h3 className={styles.groupTitle}>Mixnet Traffic</h3>
            <Stat
              label="Send rate / node"
              value={mixnet_traffic.mix_enabled ? formatRate(mixnet_traffic.send_rate) : '\u2014'}
              muted={!mixnet_traffic.mix_enabled}
            />
            <Stat
              label="Bandwidth / node"
              value={
                mixnet_traffic.mix_enabled
                  ? formatBytes(mixnet_traffic.bandwidth_per_node) + '/s'
                  : '\u2014'
              }
              muted={!mixnet_traffic.mix_enabled}
            />
            <Stat
              label="Mix cycle time"
              value={
                mixnet_traffic.mix_enabled ? formatTime(mixnet_traffic.mix_cycle_time) : '\u2014'
              }
              muted={!mixnet_traffic.mix_enabled}
            />
            <Stat
              label="RTT lower bound"
              value={
                mixnet_traffic.mix_enabled
                  ? formatTime(mixnet_traffic.theoretical_rtt_lower_bound)
                  : '\u2014'
              }
              muted={!mixnet_traffic.mix_enabled}
            />
            <Stat
              label="Packets / node / round"
              value={
                mixnet_traffic.mix_enabled
                  ? mixnet_traffic.total_packets_per_node.toLocaleString()
                  : '\u2014'
              }
              muted={!mixnet_traffic.mix_enabled}
            />
            <Stat
              label="Total bytes / round"
              value={
                mixnet_traffic.mix_enabled
                  ? formatBytes(mixnet_traffic.total_bytes_network)
                  : '\u2014'
              }
              muted={!mixnet_traffic.mix_enabled}
            />
          </div>
        )}

        {robustness.has_attack && (
          <div className={styles.group}>
            <h3 className={styles.groupTitle}>Robustness</h3>
            <Stat
              label="Byzantine fraction"
              value={`${(robustness.byzantine_fraction * 100).toFixed(0)}%`}
            />
            <div className={styles.stat}>
              <span className={styles.statLabel}>Defense</span>
              <KrumBadge
                aggregation={robustness.aggregation}
                krumSafe={robustness.krum_safe}
                hasAttack={robustness.has_attack}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
