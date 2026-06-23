import React, { useMemo, useRef, useCallback } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { getColor } from '../../utils/colors';
import styles from './TopologyGraph.module.css';

const LAYOUT_MIN_RADIUS = 70;
const LAYOUT_RADIUS_PER_NODE = 2.5;

// nodes pinned in a ring so the layout is stable
function buildGraphData(adjacency) {
  const nodeIds = Object.keys(adjacency)
    .map(Number)
    .sort((a, b) => a - b);
  const nodeCount = nodeIds.length;

  const centerX = 0;
  const centerY = 0;
  const radius = Math.max(LAYOUT_MIN_RADIUS, nodeCount * LAYOUT_RADIUS_PER_NODE);

  const nodes = nodeIds.map((id, i) => {
    const angle = (2 * Math.PI * i) / nodeCount - Math.PI / 2;
    return { id, fx: centerX + radius * Math.cos(angle), fy: centerY + radius * Math.sin(angle) };
  });

  // adjacency lists each edge twice; dedupe on normalized low-high key
  const seenEdges = new Set();
  const links = [];
  for (const [src, neighbors] of Object.entries(adjacency)) {
    for (const tgt of neighbors) {
      const source = +src;
      const target = +tgt;
      const edgeKey = [Math.min(source, target), Math.max(source, target)].join('-');

      if (!seenEdges.has(edgeKey)) {
        seenEdges.add(edgeKey);

        // shorter arc distance; >1 means it's a chord
        const ringDistance = Math.min(
          Math.abs(source - target),
          nodeCount - Math.abs(source - target)
        );
        links.push({ source, target, isChord: ringDistance > 1 });
      }
    }
  }

  return { nodes, links };
}

function getCssVar(name, fallback) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

export function TopologyGraph({ adjacency }) {
  const graphRef = useRef();
  const total = Object.keys(adjacency).length;
  const data = useMemo(() => buildGraphData(adjacency), [adjacency]);

  const chordColor = getCssVar('--color-graph-chord', 'rgba(0, 180, 255, 0.1)');
  const linkColor = getCssVar('--color-graph-link', 'rgba(150, 150, 150, 0.15)');
  const labelColor = getCssVar('--color-graph-label', '#fff');

  const nodeR = total > 40 ? 3 : total > 20 ? 4 : 5;
  const fontSize = total > 40 ? 0 : total > 20 ? 4 : 5;

  const nodeCanvasObject = useCallback(
    (node, ctx) => {
      ctx.beginPath();
      ctx.arc(node.x, node.y, nodeR, 0, 2 * Math.PI);
      ctx.fillStyle = getColor(node.id, total);
      ctx.fill();

      if (fontSize > 0) {
        ctx.font = `${fontSize}px sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillStyle = labelColor;
        ctx.fillText(node.id, node.x, node.y);
      }
    },
    [total, nodeR, fontSize, labelColor]
  );

  const linkCanvasObject = useCallback(
    (link, ctx) => {
      const sourceNode = link.source;
      const targetNode = link.target;
      ctx.beginPath();
      ctx.moveTo(sourceNode.x, sourceNode.y);
      ctx.lineTo(targetNode.x, targetNode.y);
      ctx.strokeStyle = link.isChord ? chordColor : linkColor;
      ctx.lineWidth = 1.5;
      ctx.stroke();
    },
    [chordColor, linkColor]
  );

  return (
    <div
      className={styles.container}
      role="img"
      aria-label={`Network topology graph with ${total} nodes`}
    >
      <ForceGraph2D
        ref={graphRef}
        graphData={data}
        width={280}
        height={280}
        nodeCanvasObject={nodeCanvasObject}
        nodePointerAreaPaint={(node, color, ctx) => {
          ctx.beginPath();
          ctx.arc(node.x, node.y, nodeR, 0, 2 * Math.PI);
          ctx.fillStyle = color;
          ctx.fill();
        }}
        linkCanvasObject={linkCanvasObject}
        devicePixelRatio={Math.max(window.devicePixelRatio || 2, 4)}
        cooldownTicks={1}
        onEngineStop={() => graphRef.current?.zoomToFit(0, 20)}
        enableZoomInteraction={false}
        enablePanInteraction={false}
      />
    </div>
  );
}
