// Synthetic UI fixtures only. None of these values is a benchmark measurement.
export type ExperimentStatus = 'Completed' | 'Running' | 'Queued' | 'Failed';
export const demoModels = [
  {
    id: 'llama',
    name: 'Llama 3.2',
    size: '3B',
    quantization: 'Q4_K_M',
    throughput: 41.2,
    ttft: 142,
    memory: '2.4',
    color: '#3563c9',
  },
  {
    id: 'qwen',
    name: 'Qwen 2.5',
    size: '3B',
    quantization: 'Q4_K_M',
    throughput: 36.8,
    ttft: 168,
    memory: '2.7',
    color: '#6382bb',
  },
  {
    id: 'gemma',
    name: 'Gemma 2',
    size: '2B',
    quantization: 'Q4_K_M',
    throughput: 32.4,
    ttft: 195,
    memory: '2.2',
    color: '#94a8cb',
  },
] as const;
export const demoExperiments: {
  id: string;
  name: string;
  model: string;
  engine: string;
  status: ExperimentStatus;
  tokensPerSecond: number | null;
  date: string;
}[] = [
  {
    id: 'EXP-006',
    name: 'Warm inference · baseline',
    model: 'Llama 3.2 · 3B',
    engine: 'Ollama',
    status: 'Completed',
    tokensPerSecond: 41.2,
    date: 'Oct 18, 2026',
  },
  {
    id: 'EXP-005',
    name: 'Context length · 4K',
    model: 'Qwen 2.5 · 3B',
    engine: 'Ollama',
    status: 'Completed',
    tokensPerSecond: 36.8,
    date: 'Oct 18, 2026',
  },
  {
    id: 'EXP-004',
    name: 'Decode throughput',
    model: 'Gemma 2 · 2B',
    engine: 'Ollama',
    status: 'Completed',
    tokensPerSecond: 32.4,
    date: 'Oct 17, 2026',
  },
  {
    id: 'EXP-003',
    name: 'Cold-start latency',
    model: 'Llama 3.2 · 3B',
    engine: 'Ollama',
    status: 'Running',
    tokensPerSecond: null,
    date: 'Oct 17, 2026',
  },
  {
    id: 'EXP-002',
    name: 'Output budget · 512',
    model: 'Qwen 2.5 · 3B',
    engine: 'Ollama',
    status: 'Queued',
    tokensPerSecond: null,
    date: 'Oct 16, 2026',
  },
  {
    id: 'EXP-001',
    name: 'Memory boundary',
    model: 'Gemma 2 · 2B',
    engine: 'Ollama',
    status: 'Failed',
    tokensPerSecond: null,
    date: 'Oct 16, 2026',
  },
];
export const demoReports = [
  {
    id: 'RPT-003',
    title: 'Small models, controlled conditions',
    description: 'A walkthrough of throughput, first-token latency and memory tradeoffs.',
    category: 'Model comparison',
    date: 'October 18, 2026',
    experiments: 'EXP-006, EXP-005, EXP-004',
  },
  {
    id: 'RPT-002',
    title: 'Understanding warm inference',
    description: 'Separating model loading from steady-state generation.',
    category: 'Latency study',
    date: 'October 17, 2026',
    experiments: 'EXP-006',
  },
  {
    id: 'RPT-001',
    title: 'Building a reproducible baseline',
    description: 'Pinning model revisions, workload and inference settings.',
    category: 'Baseline',
    date: 'October 16, 2026',
    experiments: 'EXP-004',
  },
];
