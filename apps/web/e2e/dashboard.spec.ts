import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const routes = ['/', '/experiments', '/compare', '/models', '/reports', '/methodology'];

test('all routes disclose demo data, fit the viewport and meet automated WCAG checks', async ({
  page,
}, testInfo) => {
  const apiRequests: string[] = [];
  page.on('request', (request) => {
    if (/\/api\/|localhost:8000|127\.0\.0\.1:8000/.test(request.url()))
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
