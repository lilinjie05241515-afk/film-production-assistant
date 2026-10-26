'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const configIndex = process.argv.indexOf('--config');
if (configIndex < 0 || !process.argv[configIndex + 1]) throw new Error('请用 --config 指定用户配置 JSON。');
const config = JSON.parse(fs.readFileSync(process.argv[configIndex + 1], 'utf8').replace(/^\uFEFF/, ''));
const originURL = new URL(config.origin);
if (originURL.protocol !== 'https:' || originURL.username || originURL.password || originURL.pathname !== '/' || originURL.search || originURL.hash) throw new Error('仅允许无路径、无凭据的明确 HTTPS origin。');
const origin = originURL.origin;
if (!path.isAbsolute(config.profile_directory || '')) throw new Error('profile_directory 必须为用户配置的绝对路径。');
const authJson = process.env.FILMPROD_SITE_AUTH;
delete process.env.FILMPROD_SITE_AUTH;
if (!authJson) throw new Error('Protected site credential was not provided.');
const credential = JSON.parse(authJson);
if (!credential.username || !credential.password) throw new Error('Protected site credential is incomplete.');
const moduleOptions = config.node_modules_directory ? { paths: [config.node_modules_directory] } : undefined;
const { chromium } = require(require.resolve('playwright', moduleOptions));
const profileDir = config.profile_directory;
fs.mkdirSync(profileDir, { recursive: true });

async function main() {
  const visible = process.argv.includes('--open');
  const context = await chromium.launchPersistentContext(profileDir, {
    channel: 'msedge',
    headless: !visible,
    viewport: { width: 1280, height: 840 },
  });
  try {
    const page = context.pages()[0] || await context.newPage();
    await page.goto(`${origin}/`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(3500);
    if (new URL(page.url()).origin !== origin) throw new Error('Site redirected outside the authorized domain.');

    const passwordInput = page.locator('input[type="password"]').first();
    if (await passwordInput.count() && await passwordInput.isVisible()) {
      const usernameInput = page.locator('input:not([type="password"]):not([aria-label="搜索影片"])').first();
      if (!await usernameInput.count()) throw new Error('Username field was not found; login was not attempted.');
      if (new URL(page.url()).origin !== origin) throw new Error('登录页 origin 已改变。');
      await usernameInput.fill(credential.username);
      await passwordInput.fill(credential.password);
      const submit = page.getByRole('button', { name: /账号登录|^登录$/ }).first();
      if (!await submit.count()) throw new Error('Login button was not found; login was not attempted.');
      await submit.click({ timeout: 10000 });
      await page.waitForTimeout(3000);
    }

    const formVisible = await passwordInput.count() ? await passwordInput.isVisible() : false;
    const accountMenu = await page.getByRole('button', { name: /退出/ }).first().isVisible().catch(() => false);
    const session = await page.evaluate(async () => {
      const response = await fetch('/api/status');
      const data = await response.json();
      return { httpStatus: response.status, verified: data.verified === true, authMode: data.authMode };
    });
    console.log(JSON.stringify({ origin, loginFormVisible: formVisible,
      accountMenuVisible: accountMenu, session,
      result: session.verified ? 'authenticated' : 'login_unverified' }));
    if (visible) {
      console.log('Browser is open for manual film inspection; close its tab to end this helper.');
      await page.waitForEvent('close', { timeout: 0 });
    }
  } finally {
    await context.close();
  }
}

main().catch(error => { console.error(error.message); process.exitCode = 1; });
