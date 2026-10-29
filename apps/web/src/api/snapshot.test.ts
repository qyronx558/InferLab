import { describe, expect, it, vi } from 'vitest';
import { toDashboardView } from '@/data/demo';
import { mockFixtures } from './fixtures.generated';
import {
  loadPublishedSnapshot,
  SnapshotError,
  toSnapshotResources,
  type SnapshotBundle,
} from './snapshot';

const encoder = new TextEncoder();

async function digest(data: Uint8Array<ArrayBuffer>) {
  const hash = await crypto.subtle.digest('SHA-256', data);
  return Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

function jsonResponse(value: unknown) {
  return new Response(encoder.encode(JSON.stringify(value)), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

function binaryResponse(value: Uint8Array<ArrayBuffer>) {
  return new Response(value, {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

async function fixture() {
  const reports = mockFixtures.reports.data;
  const reportAssets = await Promise.all(
    reports.map(async (report) => {
      const data = encoder.encode(JSON.stringify(report));
      const sha256 = await digest(data);
      const path = `/data/v1/reports/${report.id}.${sha256}.json`;
      return {
        data,
        entry: {
          id: report.id,
          title: report.title,
          description: report.description,
          category: report.category,
          data_kind: report.data_kind,
          label: report.label,
          published_at: report.published_at,
          experiment_id: report.config.experiment_id,
          engine_id: report.config.engine_id,
          model_id: report.config.model_id,
          methodology_version: report.provenance.methodology_version,
          condition: report.config.condition,
          sample_count: report.summary.sample_count,
          path,
          sha256,
          size: data.byteLength,
        },
      };
    }),
  );
  const modelsData = encoder.encode(
    JSON.stringify({
      schema_version: '1.0',
      label: 'DEMO DATA',
      models: mockFixtures.registry.data.models,
    }),
  );
  const modelsSha256 = await digest(modelsData);
  const modelsPath = `/data/v1/models.${modelsSha256}.json`;
  const methodologyData = encoder.encode(
    JSON.stringify({
      schema_version: '1.0',
      methodology_versions: ['demo-v1'],
      metrics: [
        {
          key: 'ttft',
          label: 'Time to first token',
          unit: 'ms',
          direction: 'lower',
          description: 'Client-observed time to the first streamed token.',
        },
      ],
      conditions: ['warm', 'cold'],
      protocol: ['Keep warm and cold conditions separate.'],
      limitations: ['Missing values remain unavailable.'],
    }),
  );
  const methodologySha256 = await digest(methodologyData);
  const methodologyPath = `/data/v1/methodology.${methodologySha256}.json`;
  const manifest = {
    schema_version: '1.0',
    release_id: 'REL-snapshot-001',
    published_at: '2026-10-29T12:00:00Z',
    label: 'DEMO DATA',
    data_kind: 'demo',
    report_count: reportAssets.length,
    reports: reportAssets.map((asset) => asset.entry),
    models: { path: modelsPath, sha256: modelsSha256, size: modelsData.byteLength },
    methodology: {
      path: methodologyPath,
      sha256: methodologySha256,
      size: methodologyData.byteLength,
    },
    limits: { max_reports: 100, max_files: 2000, max_asset_bytes: 5_242_880 },
  };
  const assets = new Map<string, Uint8Array<ArrayBuffer>>([
    ...reportAssets.map((asset) => [asset.entry.path, asset.data] as const),
    [modelsPath, modelsData],
    [methodologyPath, methodologyData],
  ]);
  const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
    const path = typeof input === 'string' ? input : input.toString();
    if (path === '/data/v1/manifest.json') return jsonResponse(manifest);
    const data = assets.get(path);
    return data ? binaryResponse(data) : new Response(null, { status: 404 });
  });
  return { manifest, assets, fetchImpl, modelsPath, methodologyPath };
}

function loader(source: Awaited<ReturnType<typeof fixture>>) {
  return loadPublishedSnapshot(source.fetchImpl as typeof fetch);
}

describe('published snapshot loading', () => {
  it('verifies checksums and adapts only published reports', async () => {
    const source = await fixture();
    const bundle = await loader(source);
    expect(bundle?.manifest.release_id).toBe('REL-snapshot-001');
    expect(bundle?.reports).toHaveLength(3);
    expect(bundle?.reports.map((report) => report.id)).toEqual(
      mockFixtures.reports.data.map((report) => report.id),
    );
    const resources = toSnapshotResources(bundle as SnapshotBundle);
    const view = toDashboardView(resources, bundle?.manifest.label);
    expect(view.demoModels).toHaveLength(3);
    expect(view.demoExperiments).toHaveLength(3);
    expect(view.demoExperiments.every((row) => row.status === 'complete')).toBe(true);
    expect(view.demoReports).toHaveLength(3);
    expect(view.dataLabel).toBe('DEMO DATA');
    expect(source.fetchImpl).toHaveBeenCalledWith(
      '/data/v1/manifest.json',
      expect.objectContaining({ cache: 'no-cache' }),
    );
  });

  it('rejects a changed asset before it reaches the UI', async () => {
    const source = await fixture();
    const first = source.manifest.reports[0];
    if (!first) throw new Error('Expected a report fixture');
    const data = source.assets.get(first.path);
    if (!data) throw new Error('Expected a report asset');
    data[0] = data[0] === 0 ? 1 : 0;
    await expect(loader(source)).rejects.toThrow(/checksum/);
  });

  it('treats an HTML SPA fallback as no published snapshot', async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response('<html></html>', {
          status: 200,
          headers: { 'Content-Type': 'text/html' },
        }),
    );
    await expect(loadPublishedSnapshot(fetchImpl as typeof fetch)).resolves.toBeNull();
  });

  it('rejects an unknown manifest version and malformed report metadata', async () => {
    const source = await fixture();
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      const path = typeof input === 'string' ? input : input.toString();
      if (path === '/data/v1/manifest.json') {
        return jsonResponse({ ...source.manifest, schema_version: '2.0' });
      }
      return new Response(null, { status: 404 });
    });
    await expect(loadPublishedSnapshot(fetchImpl as typeof fetch)).rejects.toBeInstanceOf(
      SnapshotError,
    );

    const bad = await fixture();
    const first = bad.manifest.reports[0];
    if (!first) throw new Error('Expected a report fixture');
    first.path = first.path.replace(first.id, 'RPT-other');
    await expect(loader(bad)).rejects.toBeInstanceOf(SnapshotError);

    const mislabeled = await fixture();
    mislabeled.manifest.label = 'MEASURED DATA';
    mislabeled.manifest.data_kind = 'measured';
    await expect(loader(mislabeled)).rejects.toThrow(/label does not match/);
  });
});
