import { useEffect, useRef, useState } from 'react';
import type { Config, Data, Layout } from 'plotly.js';

type PlotlyModule = typeof import('plotly.js-basic-dist-min');

let plotlyPromise: Promise<PlotlyModule> | null = null;
let loadedPlotly: PlotlyModule['default'] | null = null;

function loadPlotly() {
  plotlyPromise ??= import('plotly.js-basic-dist-min').then((module) => {
    loadedPlotly = module.default;
    return module;
  });
  return plotlyPromise;
}

export function PlotlyChart({
  data,
  layout,
  config,
  ariaLabel,
  height = 270,
}: {
  data: Data[];
  layout: Partial<Layout>;
  config?: Partial<Config>;
  ariaLabel: string;
  height?: number;
}) {
  const node = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');

  useEffect(() => {
    let active = true;
    const element = node.current;
    if (!element) return;
    setStatus('loading');
    void loadPlotly()
      .then((module) => {
        if (!active || !element) return;
        return module.default.react(element, data, layout, config);
      })
      .then(() => {
        if (active) setStatus('ready');
      })
      .catch(() => {
        if (active) setStatus('error');
      });
    return () => {
      active = false;
      if (loadedPlotly && element) loadedPlotly.purge(element);
    };
  }, [config, data, layout]);

  return (
    <figure className="plotly-figure">
      <div
        ref={node}
        className="plotly-chart"
        style={{ minHeight: height }}
        role="img"
        aria-label={ariaLabel}
        aria-busy={status === 'loading'}
      />
      {status === 'loading' && (
        <p className="plotly-chart-status" role="status">
          Loading chart…
        </p>
      )}
      {status === 'error' && (
        <p className="plotly-chart-status plotly-chart-error" role="status">
          Chart could not be rendered. The accessible values are available below.
        </p>
      )}
      <figcaption className="sr-only">{ariaLabel}</figcaption>
    </figure>
  );
}
