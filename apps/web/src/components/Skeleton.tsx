import { Skeleton as Primitive } from '@/components/ui/skeleton';

export function Skeleton() {
  return (
    <div
      role="status"
      aria-label="Loading demo preview"
      className="space-y-5 rounded-xl border bg-white p-6"
    >
      <span className="sr-only">Loading demo preview. This is an illustrative loading state.</span>
      <div aria-hidden="true">
        <Primitive className="h-5 w-40" />
        <div className="mt-6 grid gap-4 sm:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <Primitive key={i} className="h-24" />
          ))}
        </div>
        <div className="mt-6 space-y-4">
          {[1, 2, 3, 4].map((i) => (
            <Primitive key={i} className="h-10 w-full" />
          ))}
        </div>
      </div>
    </div>
  );
}
