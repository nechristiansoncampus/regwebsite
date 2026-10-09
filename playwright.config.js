const { defineConfig, devices } = require('@playwright/test');

const pythonCommand = process.env.CI ? 'python' : 'venv-regwebsite/bin/python';

module.exports = defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: 'http://127.0.0.1:5010',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'desktop-chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'mobile-chromium',
      use: { ...devices['Pixel 5'] },
    },
  ],
  webServer: {
    command: `${pythonCommand} tests/e2e_server.py`,
    url: 'http://127.0.0.1:5010/register',
    reuseExistingServer: !process.env.CI,
    stdout: 'ignore',
    stderr: 'pipe',
    env: {
      ...process.env,
      APP_ENV: 'test',
      FLASK_SECRET_KEY: 'playwright-only-secret',
      PAYPAL_CLIENT_ID: 'playwright-client-id',
      RETREAT_REGISTRATION_AMOUNT: '130.00',
      RETREAT_LATE_FEE_START: '2999-10-12T00:00:00-04:00',
    },
  },
});
