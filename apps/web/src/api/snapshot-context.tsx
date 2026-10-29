import { createContext, useContext } from 'react';
import type { DataLabel } from '@/data/demo';
import type { MethodologySnapshot } from './snapshot';

export type SnapshotInfo = {
  status: 'demo' | 'snapshot' | 'error';
  label: DataLabel;
  releaseId: string | null;
  publishedAt: string | null;
  error: string | null;
  methodology: MethodologySnapshot | null;
};

const demoInfo: SnapshotInfo = {
  status: 'demo',
  label: 'DEMO DATA',
  releaseId: null,
  publishedAt: null,
  error: null,
  methodology: null,
};

export const SnapshotContext = createContext<SnapshotInfo>(demoInfo);

export function useSnapshotInfo() {
  return useContext(SnapshotContext);
}

export function demoSnapshotInfo(): SnapshotInfo {
  return demoInfo;
}

export function errorSnapshotInfo(error: unknown): SnapshotInfo {
  const message =
    error instanceof Error && error.name === 'AbortError'
      ? 'Snapshot loading timed out.'
      : error instanceof Error
        ? error.message
        : 'Published snapshot validation failed.';
  return { ...demoInfo, status: 'error', error: message };
}
