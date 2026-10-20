import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { AppRoutes } from './App';

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
    expect(screen.getByText(/same demo model is selected/)).toBeVisible();
    expect(screen.getAllByText('41.2 tok/s')).toHaveLength(2);
  });

  it('recovers a simulated error and exposes labeled loading and empty states', async () => {
    const user = userEvent.setup();
    preview('/?state=error');
    expect(screen.getByRole('alert')).toHaveTextContent('simulated error');
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
