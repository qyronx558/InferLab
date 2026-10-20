import type { components } from './generated';

export type ContractCatalog = components['schemas']['ContractCatalog'];
export type Engine = components['schemas']['Engine'];
export type Model = components['schemas']['Model'];
export type ExperimentConfig = components['schemas']['ExperimentConfig'];
export type ExperimentSubmitRequest = components['schemas']['ExperimentSubmitRequest'];
export type SubmissionReceipt = components['schemas']['SubmissionReceipt'];
export type Job = components['schemas']['Job'];
export type RunMetrics = components['schemas']['RunMetrics'];
export type Summary = components['schemas']['Summary'];
export type PublishedReport = components['schemas']['PublishedReport'];
export type WorkerHeartbeat = components['schemas']['WorkerHeartbeat'];
export type Registry = components['schemas']['Registry'];
export type Experiment = components['schemas']['Experiment'];
export type Unavailable = components['schemas']['Unavailable'];
export type ExecutionState = ContractCatalog['display_states'][number];
export type ResourceName = 'registry' | 'experiments' | 'runs' | 'summaries' | 'reports' | 'worker';
