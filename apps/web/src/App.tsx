export function App() {
  return (
    <main>
      <p className="eyebrow">LOCAL INFERENCE BENCHMARKING</p>
      <h1>{import.meta.env.VITE_APP_TITLE || 'InferLab'}</h1>
      <p>Project scaffold ready. No benchmark results have been published.</p>
      <p>
        Experiment execution, authentication, and snapshot publishing will be added in later stages.
        Public viewers will only read reviewed results.
      </p>
    </main>
  );
}
