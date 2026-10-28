import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { downloadText } from '@/lib/download';
import { AppRoutes } from './App';

vi.mock('@/lib/download', () => ({ downloadText: vi.fn() }));

function preview(path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

describe('demo workspace', () => {
  it('keeps demo disclosure present across all navigation destinations', async () => {
    const user = userEvent.setup();
    preview();
    const navigation = screen.getByRole('navigation', { name: 'Main navigation' });
    for (const name of ['Experiments', 'Compare', 'Models', 'Reports', 'Methodology', 'Overview']) {
      await user.click(within(navigation).getByRole('link', { name: new RegExp(name) }));
      expect(screen.getByText('DEMO DATA', { selector: '.demo-badge' })).toBeVisible();
      expect(screen.getByText(/No backend or GPU is connected/)).toBeVisible();
      expect(within(navigation).getByRole('link', { current: 'page' })).toHaveTextContent(name);
      expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument();
    }
  });

  it('filters experiments and restores results after a no-match search', async () => {
    const user = userEvent.setup();
    preview('/experiments');
    await user.selectOptions(
      screen.getByRole('combobox', { name: 'Filter by status' }),
      'Completed',
    );
    expect(screen.getByText('3 demo experiments')).toBeVisible();
    await user.type(
      screen.getByRole('textbox', { name: 'Search experiments' }),
      'no matching model',
    );
    expect(screen.getByText('Nothing here yet')).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Reset preview' }));
    expect(screen.getByText('6 demo experiments')).toBeVisible();
  });

  it('updates comparison values and flags identical model selection', async () => {
    const user = userEvent.setup();
    preview('/compare');
    await user.selectOptions(screen.getByRole('combobox', { name: 'Configuration B' }), 'llama');
    expect(screen.getByText(/Same demo model selected/)).toBeVisible();
    expect(screen.getAllByText('41.2 tok/s').length).toBeGreaterThanOrEqual(2);
  });

  it('renders six comparison views with context and unavailable values', () => {
    preview('/compare');
    expect(screen.getByRole('heading', { name: 'Six views of the selected runs' })).toBeVisible();
    for (const name of [
      'Decode throughput',
      'Time to first token',
      'Request latency p95',
      'Aggregate throughput',
      'Peak VRAM',
      'Quality score',
    ]) {
      expect(screen.getByRole('heading', { name })).toBeVisible();
    }
    expect(screen.getByRole('heading', { name: 'Comparison context' })).toBeVisible();
    expect(screen.getByRole('heading', { name: 'Metric summary' })).toBeVisible();
    expect(screen.getByRole('note')).toHaveTextContent(
      'Observational comparison, not a controlled experiment',
    );
    expect(screen.getAllByText('Unavailable (unsupported)').length).toBeGreaterThan(0);
    expect(screen.getAllByText('170.7 tok/s').length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText('DEMO DATA').length).toBeGreaterThan(0);
  });

  it('exports the selected comparison as CSV and JSON', async () => {
    const user = userEvent.setup();
    preview('/compare');

    await user.click(screen.getByRole('button', { name: 'CSV' }));
    const csv = vi.mocked(downloadText).mock.lastCall;
    expect(csv?.[0]).toBe('inferlab-compare-demo.csv');
    expect(csv?.[1]).toContain('text/csv');
    expect(csv?.[2]).toContain('decode_tps');
    expect(csv?.[2]).toContain('Llama 3.2');

    await user.click(screen.getByRole('button', { name: 'JSON' }));
    const json = vi.mocked(downloadText).mock.lastCall;
    expect(json?.[0]).toBe('inferlab-compare-demo.json');
    const exported = JSON.parse(json?.[2] ?? '{}') as {
      observational: boolean;
      causal_claim: boolean;
      sides: Array<{
        prompt: { sample_count: number };
        hardware: unknown;
        measurements: { aggregateThroughput: { value: number } };
      }>;
    };
    expect(exported.observational).toBe(true);
    expect(exported.causal_claim).toBe(false);
    expect(exported.sides).toHaveLength(2);
    expect(exported.sides[0]?.prompt.sample_count).toBe(1);
    expect(exported.sides[0]?.hardware).toBeDefined();
    expect(exported.sides[0]?.measurements.aggregateThroughput.value).toBeGreaterThan(0);
  });

  it('renders a printable report with limitations and accepted run evidence', async () => {
    const user = userEvent.setup();
    const print = vi.fn();
    vi.stubGlobal('print', print);
    preview('/compare/report');

    expect(screen.getByRole('heading', { name: 'Comparison report' })).toBeVisible();
    expect(screen.getByRole('heading', { name: 'Limitations and interpretation' })).toBeVisible();
    expect(screen.getByRole('region', { name: 'Accepted measured run evidence' })).toBeVisible();
    expect(screen.getByText('RUN-006')).toBeVisible();
    expect(screen.getByText(/Aggregate throughput is derived/)).toBeVisible();
    expect(screen.getByText(/uncontrolled/)).toBeVisible();

    await user.click(screen.getByRole('button', { name: 'Print' }));
    expect(print).toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it('recovers a simulated error and exposes labeled loading and empty states', async () => {
    const user = userEvent.setup();
    preview('/?state=error');
    expect(await screen.findByRole('alert')).toHaveTextContent('simulated error');
    await user.click(screen.getByRole('button', { name: 'Restore demo data' }));
    expect(screen.getByRole('heading', { name: 'A clearer view of performance.' })).toBeVisible();
    await user.selectOptions(screen.getByRole('combobox', { name: 'Preview state' }), 'loading');
    expect(screen.getByRole('status', { name: 'Loading demo preview' })).toBeVisible();
    await user.selectOptions(screen.getByRole('combobox', { name: 'Preview state' }), 'empty');
    expect(screen.getByText('No published results yet')).toBeVisible();
  });

  it('does not imply incomplete experiments have published reports', () => {
    preview('/reports?experiment=EXP-002');
    expect(screen.getByText('No report for this demo run')).toBeVisible();
  });

  it('offers an internal way back from an unknown route', async () => {
    const user = userEvent.setup();
    preview('/unknown');
    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeVisible();
    await user.click(screen.getByRole('link', { name: 'Back to overview' }));
    expect(screen.getByRole('heading', { name: 'A clearer view of performance.' })).toBeVisible();
  });
});
