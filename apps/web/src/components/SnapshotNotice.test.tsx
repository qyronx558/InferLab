import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SnapshotContext, type SnapshotInfo } from '@/api/snapshot-context';
import { SnapshotNotice } from './SnapshotNotice';

function renderNotice(info: SnapshotInfo) {
  return render(
    <SnapshotContext.Provider value={info}>
      <SnapshotNotice />
    </SnapshotContext.Provider>,
  );
}

describe('snapshot disclosure', () => {
  it('shows the published snapshot date, release and static boundary', () => {
    renderNotice({
      status: 'snapshot',
      label: 'MEASURED DATA',
      releaseId: 'REL-20261029T120000Z-abcdef12',
      publishedAt: '2026-10-29T12:00:00Z',
      error: null,
      methodology: null,
    });
    expect(screen.getByText('Published snapshot.')).toBeVisible();
    expect(screen.getByText('October 29, 2026')).toBeVisible();
    expect(screen.getByText('REL-20261029T120000Z-abcdef12')).toBeVisible();
    expect(screen.getByText(/no backend or GPU is connected/)).toBeVisible();
  });

  it('shows an integrity or load error instead of silently claiming success', () => {
    renderNotice({
      status: 'error',
      label: 'DEMO DATA',
      releaseId: null,
      publishedAt: null,
      error: 'Report RPT-003 checksum does not match the manifest.',
      methodology: null,
    });
    expect(screen.getByRole('alert')).toHaveTextContent('Published snapshot unavailable.');
    expect(screen.getByRole('alert')).toHaveTextContent('checksum does not match');
    expect(screen.getByRole('alert')).toHaveTextContent('Showing bundled demo data');
  });
});
