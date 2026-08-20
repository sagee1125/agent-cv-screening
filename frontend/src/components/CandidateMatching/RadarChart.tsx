// Dependency-free SVG radar chart for 0-100 dimension scores.
import type { RadarDimensionDatum } from "../../types";

interface RadarChartProps {
  // Radar axes to draw; null values are rendered as not-applicable axes.
  dimensions: RadarDimensionDatum[];
  size?: number;
  maxValue?: number;
  showLabels?: boolean;
  showValues?: boolean;
  className?: string;
}

interface RadarPoint {
  x: number;
  y: number;
}

// Converts a radar axis index into its angle measured clockwise from 12 o'clock.
function angleForIndex(index: number, total: number): number {
  return -90 + (360 / total) * index;
}

// Converts a polar coordinate into an SVG viewBox point.
function polarPoint(center: number, radius: number, angleDeg: number): RadarPoint {
  const radians = (Math.PI / 180) * angleDeg;
  return {
    x: center + radius * Math.cos(radians),
    y: center + radius * Math.sin(radians),
  };
}

// Builds the SVG polygon points attribute from a list of points.
function pointsToPolygon(points: RadarPoint[]): string {
  return points
    .map((point) => point.x.toFixed(2) + "," + point.y.toFixed(2))
    .join(" ");
}

// Chooses a text anchor so labels extend toward the chart instead of clipping.
function textAnchorForX(center: number, x: number): "start" | "middle" | "end" {
  if (Math.abs(x - center) < 1) return "middle";
  return x < center ? "start" : "end";
}

// Renders radar grid rings, axes, data polygon, points, and optional labels.
export function RadarChart({
  dimensions,
  size = 220,
  maxValue = 100,
  showLabels = false,
  showValues = false,
  className,
}: RadarChartProps) {
  const total = dimensions.length;
  if (total === 0) {
    return <p className="text-xs text-slate-500">No radar dimensions available.</p>;
  }

  const center = size / 2;
  const labelPadding = showLabels ? 36 : 12;
  const valuePadding = showValues ? 8 : 0;
  const radius = Math.max(20, center - labelPadding - valuePadding);
  const rings = [0.2, 0.4, 0.6, 0.8, 1];

  const axisPoints = dimensions.map((_, index) =>
    polarPoint(center, radius, angleForIndex(index, total))
  );
  const dataPoints = dimensions.map((dimension, index) => {
    if (dimension.value === null) return null;
    const clamped = Math.max(0, Math.min(maxValue, dimension.value));
    return polarPoint(
      center,
      radius * (clamped / maxValue),
      angleForIndex(index, total)
    );
  });
  const polygonPoints = dataPoints.filter(
    (point): point is RadarPoint => point !== null
  );

  return (
    <div className={className}>
      <svg
        viewBox={"0 0 " + size + " " + size}
        role="img"
        aria-label="Candidate match radar chart"
        className="h-auto w-full"
      >
        {rings.map((ratio, ringIndex) => (
          <polygon
            key={"ring-" + ringIndex}
            points={pointsToPolygon(
              dimensions.map((_, index) =>
                polarPoint(center, radius * ratio, angleForIndex(index, total))
              )
            )}
            fill="none"
            stroke="#e2e8f0"
            strokeWidth={1}
          />
        ))}

        {axisPoints.map((point, index) => (
          <line
            key={"axis-" + index}
            x1={center}
            y1={center}
            x2={point.x}
            y2={point.y}
            stroke="#e2e8f0"
            strokeWidth={1}
          />
        ))}

        {polygonPoints.length >= 3 ? (
          <polygon
            points={pointsToPolygon(polygonPoints)}
            fill="rgba(14,165,233,0.25)"
            stroke="#0284c7"
            strokeWidth={2}
          />
        ) : null}

        {dataPoints.map((point, index) => {
          if (point === null) {
            return (
              <circle
                key={"point-" + index}
                cx={axisPoints[index].x}
                cy={axisPoints[index].y}
                r={3}
                fill="none"
                stroke="#cbd5e1"
                strokeDasharray="2 2"
              />
            );
          }
          return (
            <circle
              key={"point-" + index}
              cx={point.x}
              cy={point.y}
              r={4}
              fill="#0284c7"
            />
          );
        })}

        {showValues
          ? dimensions.map((dimension, index) => {
              const point = dataPoints[index];
              if (!point) {
                return (
                  <text
                    key={"value-" + index}
                    x={axisPoints[index].x}
                    y={axisPoints[index].y - 8}
                    textAnchor="middle"
                    fontSize={10}
                    className="fill-slate-500"
                  >
                    N/A
                  </text>
                );
              }
              return (
                <text
                  key={"value-" + index}
                  x={point.x}
                  y={point.y - 8}
                  textAnchor="middle"
                  fontSize={10}
                  className="fill-slate-700"
                >
                  {dimension.value?.toFixed(0)}
                </text>
              );
            })
          : null}

        {showLabels
          ? dimensions.map((dimension, index) => {
              const point = polarPoint(
                center,
                radius + 12,
                angleForIndex(index, total)
              );
              return (
                <text
                  key={"label-" + index}
                  x={point.x}
                  y={point.y}
                  textAnchor={textAnchorForX(center, point.x)}
                  fontSize={10}
                  className="fill-slate-700"
                >
                  {dimension.label + (dimension.value === null ? " (N/A)" : "")}
                </text>
              );
            })
          : null}
      </svg>

      <div className="sr-only">
        <ul>
          {dimensions.map((dimension) => (
            <li key={dimension.id}>
              {dimension.label}: {dimension.value ?? "Not applicable"}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
