import { Info } from 'lucide-react';
import type { ComparisonModel } from '@/data/demo';
import { comparisonNotice } from '@/data/comparison';

export function ComparisonNotice({
  left,
  right,
}: {
  left: ComparisonModel;
  right: ComparisonModel;
}) {
  const notice = comparisonNotice(left, right);
  return (
    <div className="comparison-notice" role="note">
      <Info size={18} className="shrink-0" aria-hidden="true" />
      <div>
        <strong>{notice.title}</strong>
        <p>{notice.body}</p>
        <p className="comparison-notice-disclaimer">
          Charts use only the selected fixture values. They are not a benchmark ranking and must not
          be used to infer causation.
        </p>
      </div>
    </div>
  );
}
