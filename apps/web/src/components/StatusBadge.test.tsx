import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { mockFixtures } from '@/api/fixtures.generated';
import { StatusBadge } from './StatusBadge';

it('can render every contract state without reducing cancellation or unavailability to failure', () => {
  render(
    <div>
      {mockFixtures.display_states.map((state) => (
        <StatusBadge key={state} status={state} />
      ))}
    </div>,
  );
  for (const text of ['Unavailable', 'Pending', 'Running', 'Completed', 'Failed', 'Cancelled']) {
    expect(screen.getByText(text)).toBeVisible();
  }
});
