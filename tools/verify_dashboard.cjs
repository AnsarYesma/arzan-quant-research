// Run with Playwright available through NODE_PATH or a local installation.
const { chromium } = require('playwright');
const path = require('path');
const { pathToFileURL } = require('url');

(async () => {
  const input = path.resolve(process.argv[2]);
  const screenshot = path.resolve(process.argv[3]);
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
    const errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.goto(pathToFileURL(input).href);
    await page.waitForSelector('#models th');
    const count = await page.locator('#retailer option').count();
    if (count > 1) {
      await page.selectOption('#retailer', { index: 1 });
      if (!(await page.locator('#details').textContent()).length) throw Error('Missing details');
      await page.locator('#minimum').fill('500');
      await page.locator('#minimum').dispatchEvent('input');
      if (await page.locator('#threshold').textContent() !== '500') throw Error('Filter did not update');
      await page.selectOption('#retailer', '');
      await page.locator('#minimum').fill('20');
      await page.locator('#minimum').dispatchEvent('input');
    }
    await page.screenshot({ path: screenshot, fullPage: true });
    if (errors.length) throw Error(errors.join('\n'));
    console.log(JSON.stringify({ status: 'passed', retailerOptions: count, screenshot }));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
