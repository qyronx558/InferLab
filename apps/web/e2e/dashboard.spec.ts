import { createHash } from 'node:crypto';
import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { mockFixtures } from '../src/api/fixtures.generated';

async function captureOverview(page: Page, path: string) {
  for (let attempt = 0; ; attempt += 1) {
    try {
      await page.screenshot({ path, fullPage: true, animations: 'disabled' });
      return;
    } catch (error) {
      if (attempt >= 1) throw error;
    }
  }
}

function encode(value: unknown) {
  return Buffer.from(JSON.stringify(value));
}

function sha256(value: Buffer) {
  return createHash('sha256').update(value).digest('hex');
}

function buildPublishedSnapshot() {
  const reportAssets = mockFixtures.reports.data.map((report) => {
    const data = encode(report);
    const hash = sha256(data);
    return {
      data,
      path: `/data/v1/reports/${report.id}.${hash}.json`,
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
        path: `/data/v1/reports/${report.id}.${hash}.json`,
        sha256: hash,
        size: data.byteLength,
      },
    };
  });
  const modelsData = encode({
    schema_version: '1.0',
    label: 'DEMO DATA',
    models: mockFixtures.registry.data.models,
  });
  const modelsHash = sha256(modelsData);
  const modelsPath = `/data/v1/models.${modelsHash}.json`;
  const methodologyData = encode({
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
  });
  const methodologyHash = sha256(methodologyData);
  const methodologyPath = `/data/v1/methodology.${methodologyHash}.json`;
  const manifestData = encode({
    schema_version: '1.0',
    release_id: 'REL-20261029T120000Z-abcdef12',
    published_at: '2026-10-29T12:00:00Z',
    label: 'DEMO DATA',
    data_kind: 'demo',
    report_count: reportAssets.length,
    reports: reportAssets.map((asset) => asset.entry),
    models: { path: modelsPath, sha256: modelsHash, size: modelsData.byteLength },
    methodology: {
      path: methodologyPath,
      sha256: methodologyHash,
      size: methodologyData.byteLength,
    },
    limits: { max_reports: 100, max_files: 2000, max_asset_bytes: 5_242_880 },
  });
  return {
    manifestData,
    assets: new Map<string, Buffer>([
      ...reportAssets.map((asset) => [asset.path, asset.data] as const),
      [modelsPath, modelsData],
      [methodologyPath, methodologyData],
    ]),
  };
}

const routes = [
  '/',
  '/experiments',
  '/compare',
  '/compare/report',
  '/models',
  '/reports',
  '/methodology',
];

test('cached published fixtures survive network offline and an offline worker', async ({
  page,
  context,
}) => {
  await page.goto('/');
  await expect(page.getByText('offline (demo)', { exact: true })).toBeVisible();
  await context.setOffline(true);
  // In-app navigation uses the cached local snapshot, not a backend request.
  await page.evaluate(() => {
    history.pushState({}, '', '/reports');
    window.dispatchEvent(new PopStateEvent('popstate'));
  });
  await expect(page.getByRole('heading', { name: 'Reports & findings' })).toBeVisible();
  await expect(page.getByText('Small models, controlled conditions')).toBeVisible();
  await context.setOffline(false);
});

test('all routes disclose demo data, fit the viewport and meet automated WCAG checks', async ({
  page,
}, testInfo) => {
  const apiRequests: string[] = [];
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (
      /^\/api(?:\/|$)/.test(url.pathname) ||
      (['localhost', '127.0.0.1'].includes(url.hostname) && url.port === '8000')
    )
      apiRequests.push(request.url());
  });
  for (const route of routes) {
    await page.goto(route);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.locator('.demo-badge')).toHaveText('DEMO DATA');
    if (route === '/') await captureOverview(page, testInfo.outputPath('overview.png'));
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
      .analyze();
    expect(results.violations).toEqual([]);
  }
  expect(apiRequests).toEqual([]);
});

test('published snapshots are verified and disclose their release date', async ({ page }) => {
  const snapshot = buildPublishedSnapshot();
  await page.route('**/data/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/data/v1/manifest.json') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: snapshot.manifestData,
      });
      return;
    }
    const asset = snapshot.assets.get(path);
    if (!asset) {
      await route.fulfill({ status: 404, body: '' });
      return;
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: asset });
  });

  await page.goto('/');
  await expect(page.getByText('Published snapshot.')).toBeVisible();
  await expect(page.getByText('October 29, 2026')).toBeVisible();
  await expect(page.getByText('REL-20261029T120000Z-abcdef12')).toBeVisible();
  await expect(page.locator('.demo-badge')).toHaveText('DEMO DATA');

  await page.goto('/methodology');
  await expect(page.getByRole('heading', { name: 'Published methodology' })).toBeVisible();
  await expect(page.getByText('Time to first token · ms')).toBeVisible();
});

test('a corrupt published snapshot is disclosed and falls back to demo data', async ({ page }) => {
  const snapshot = buildPublishedSnapshot();
  const reportPath = [...snapshot.assets.keys()].find((path) => path.includes('/reports/'));
  if (!reportPath) throw new Error('Expected a report asset');
  await page.route('**/data/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/data/v1/manifest.json') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: snapshot.manifestData,
      });
      return;
    }
    const asset = snapshot.assets.get(path);
    if (!asset) {
      await route.fulfill({ status: 404, body: '' });
      return;
    }
    const body = Buffer.from(asset);
    if (path === reportPath) body[0] = body[0] === 0x7b ? 0x5b : 0x7b;
    await route.fulfill({ status: 200, contentType: 'application/json', body });
  });

  await page.goto('/');
  const alert = page.getByRole('alert');
  await expect(alert).toContainText('Published snapshot unavailable.');
  await expect(alert).toContainText('checksum does not match');
  await expect(page.locator('.demo-badge')).toHaveText('DEMO DATA');
});

test('keyboard navigation, mobile dialog focus and route transitions work', async ({
  page,
}, testInfo) => {
  await page.goto('/');
  await expect(page.locator('.demo-badge')).toHaveText('DEMO DATA');
  await page.keyboard.press('Tab');
  await expect(page.getByRole('link', { name: 'Skip to content' })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('#main-content')).toBeFocused();
  if (testInfo.project.name === 'mobile') {
    const trigger = page.getByRole('button', { name: 'Open navigation' });
    await trigger.click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    const dialogAccessibility = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
      .analyze();
    expect(dialogAccessibility.violations).toEqual([]);
    for (let i = 0; i < 12; i++) {
      await page.keyboard.press('Tab');
      expect(await dialog.evaluate((node) => node.contains(document.activeElement))).toBe(true);
    }
    await page.keyboard.press('Escape');
    await expect(dialog).not.toBeVisible();
    await expect(trigger).toBeFocused();
    await trigger.click();
    await page.getByRole('navigation').getByRole('link', { name: 'Experiments' }).click();
    await expect(dialog).not.toBeVisible();
  } else {
    await page.getByRole('navigation').getByRole('link', { name: 'Experiments' }).click();
  }
  await expect(page.getByRole('heading', { name: 'Experiments', exact: true })).toBeVisible();
  await page.getByRole('textbox', { name: 'Search experiments' }).fill('zzzz');
  await expect(page.getByText('Nothing here yet')).toBeVisible();
  await page.getByRole('button', { name: 'Reset preview' }).click();
  await expect(page.getByText('6 demo experiments')).toBeVisible();
});

test('comparison exports carry context and reject causal claims', async ({ page }) => {
  await page.goto('/compare');
  await expect(page.getByRole('heading', { name: 'Six views of the selected runs' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Comparison context' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Decode throughput' })).toBeVisible();
  await expect(page.locator('.plotly-chart[aria-busy="false"]')).toHaveCount(6);
  await expect(page.locator('.plotly-chart .plot-container')).toHaveCount(6);
  await expect(page.locator('.plotly-chart').nth(2)).toContainText('Unavailable');
  await expect(page.locator('.plotly-chart').nth(5)).toContainText('Unavailable');

  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'JSON' }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('inferlab-compare-demo.json');
  const stream = await download.createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream) chunks.push(Buffer.from(chunk));
  const payload = JSON.parse(Buffer.concat(chunks).toString()) as {
    label: string;
    synthetic: boolean;
    observational: boolean;
    causal_claim: boolean;
    sides: Array<{
      model: { revision: string; quantization: string };
      prompt: { distribution: string; sample_count: number };
      hardware: unknown;
    }>;
  };
  expect(payload.label).toBe('DEMO DATA');
  expect(payload.synthetic).toBe(true);
  expect(payload.observational).toBe(true);
  expect(payload.causal_claim).toBe(false);
  expect(payload.sides).toHaveLength(2);
  expect(payload.sides[0]?.model.revision).toBeTruthy();
  expect(payload.sides[0]?.model.quantization).toBeTruthy();
  expect(payload.sides[0]?.prompt.distribution).toBeTruthy();
  expect(payload.sides[0]?.prompt.sample_count).toBeGreaterThan(0);
  expect(payload.sides[0]?.hardware).toBeTruthy();
});

test('report downloads are labeled synthetic JSON', async ({ page }) => {
  await page.goto('/reports');
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export demo JSON' }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('inferlab-demo-reports.json');
  const stream = await download.createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream) chunks.push(Buffer.from(chunk));
  const payload = JSON.parse(Buffer.concat(chunks).toString()) as {
    label: string;
    synthetic: boolean;
  };
  expect(payload.label).toBe('DEMO DATA');
  expect(payload.synthetic).toBe(true);
});
