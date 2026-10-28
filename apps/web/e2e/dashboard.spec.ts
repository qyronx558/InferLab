import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

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
    if (route === '/')
      await page.screenshot({ path: testInfo.outputPath('overview.png'), fullPage: true });
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

test('keyboard navigation, mobile dialog focus and route transitions work', async ({
  page,
}, testInfo) => {
  await page.goto('/');
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
