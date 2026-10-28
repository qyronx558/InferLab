import { useMemo } from 'react';
import type { Data, Layout } from 'plotly.js';
import { PlotlyChart } from '@/components/PlotlyChart';
import type { ComparisonModel, DataLabel } from '@/data/demo';
import { formatMeasurement, measurementFor, type ComparisonMetric } from '@/data/comparison';

const chartConfig = {
  responsive: true,
  displayModeBar: false,
  displaylogo: false,
  scrollZoom: false,
};

function sideLabel(side: ComparisonModel, index: number) {
  return `${index === 0 ? 'A' : 'B'} · ${side.name}`;
}

export function ComparisonChart({
  metric,
  left,
  right,
  dataLabel,
}: {
  metric: ComparisonMetric;
  left: ComparisonModel;
  right: ComparisonModel;
  dataLabel: DataLabel;
}) {
  const { data, layout, ariaLabel } = useMemo(() => {
    const sides = [left, right];
    const labels = sides.map(sideLabel);
    const measurements = sides.map((side) => measurementFor(side, metric.key));
    const traces: Data[] = sides.flatMap((side, index) => {
      const measurement = measurements[index];
      const label = labels[index] ?? '';
      if (!measurement || measurement.value === null) return [];
      return [
        {
          type: 'bar' as const,
          x: [label],
          y: [measurement.value],
          name: side.name,
          marker: { color: side.color },
          text: [formatMeasurement(metric, measurement)],
          textposition: 'outside' as const,
          cliponaxis: false,
          hovertemplate: `${side.name}<br>${metric.label}: %{y:,.2f} ${metric.unit}<extra></extra>`,
        },
      ];
    });
    const annotations = measurements.flatMap((measurement, index) => {
      if (measurement.value !== null) return [];
      return [
        {
          x: labels[index] ?? '',
          y: 0,
          text: 'Unavailable',
          showarrow: false,
          yshift: 12,
          font: { color: '#8a5a12', size: 11 },
        },
      ];
    });
    const yaxis =
      metric.key === 'quality'
        ? {
            range: [0, 1],
            title: { text: `${metric.label} (${metric.unit})` },
            gridcolor: '#edf1f6',
            zeroline: false,
          }
        : {
            rangemode: 'tozero' as const,
            title: { text: `${metric.label} (${metric.unit})` },
            gridcolor: '#edf1f6',
            zeroline: false,
          };
    const chartLayout: Partial<Layout> = {
      height: 250,
      autosize: true,
      margin: { l: 54, r: 16, t: 16, b: 44 },
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      font: {
        family: "'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif",
        size: 11,
        color: '#59677c',
      },
      xaxis: {
        type: 'category',
        categoryorder: 'array',
        categoryarray: labels,
        showgrid: false,
        tickfont: { size: 11, color: '#344965' },
      },
      yaxis,
      showlegend: false,
      bargap: 0.5,
      annotations,
      hoverlabel: { bgcolor: '#17243b', font: { color: '#ffffff', size: 11 } },
    };
    const accessibleValues = sides
      .map((side, index) => {
        const measurement = measurements[index];
        return `${index === 0 ? 'A' : 'B'} ${side.name}: ${
          measurement ? formatMeasurement(metric, measurement) : 'Unavailable'
        }`;
      })
      .join('; ');
    return {
      data: traces,
      layout: chartLayout,
      ariaLabel: `${metric.label}. ${accessibleValues}. ${dataLabel}.`,
    };
  }, [dataLabel, left, metric, right]);

  return (
    <article className="comparison-chart-card">
      <div className="comparison-chart-heading">
        <div>
          <h2>{metric.label}</h2>
          <p>
            {metric.higherIsBetter ? 'Higher is shown above' : 'Lower is shown above'} ·{' '}
            {metric.unit}
          </p>
        </div>
        <span className="subtle-tag">{dataLabel}</span>
      </div>
      <PlotlyChart data={data} layout={layout} config={chartConfig} ariaLabel={ariaLabel} />
      <p className="comparison-metric-note">{metric.description}</p>
      <div className="comparison-chart-context">
        {[left, right].map((side, index) => (
          <p key={`${index}-${side.id}`}>
            <strong>{index === 0 ? 'A' : 'B'}</strong> {side.revision} · {side.quantization} ·{' '}
            {side.promptDistribution} · n={side.sampleCount} · {side.hardwareLabel}
          </p>
        ))}
      </div>
      <details className="comparison-data-details">
        <summary>View accessible values</summary>
        <table>
          <caption>{metric.label} values and comparison context</caption>
          <thead>
            <tr>
              <th scope="col">Side</th>
              <th scope="col">Value</th>
              <th scope="col">Revision / quantization</th>
              <th scope="col">Prompt distribution</th>
              <th scope="col">Samples</th>
              <th scope="col">Hardware</th>
            </tr>
          </thead>
          <tbody>
            {[left, right].map((side, index) => {
              const measurement = measurementFor(side, metric.key);
              return (
                <tr key={`${index}-${side.id}`}>
                  <th scope="row">
                    {index === 0 ? 'A' : 'B'} · {side.name}
                  </th>
                  <td>{formatMeasurement(metric, measurement)}</td>
                  <td>
                    {side.revision} · {side.quantization}
                  </td>
                  <td>{side.promptDistribution}</td>
                  <td>{side.sampleCount}</td>
                  <td>{side.hardwareLabel}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </details>
    </article>
  );
}
