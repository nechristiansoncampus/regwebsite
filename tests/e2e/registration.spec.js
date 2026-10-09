const { test, expect } = require('@playwright/test');

async function startRegistration(page) {
  await page.route('https://www.paypal.com/sdk/js**', async (route) => {
    await route.fulfill({
      contentType: 'application/javascript',
      body: `window.paypal = {
        Buttons: () => ({ render: () => Promise.resolve() })
      };`,
    });
  });
  await page.goto('/register');
  await expect(page.getByRole('heading', { name: 'Contact Info' })).toBeVisible();
}

async function completeContactPage(page) {
  await page.getByLabel('Email *').fill('jamie@example.com');
  await page.getByLabel('Phone Number *').fill('5551234567');
  await page.getByLabel('First Name *').fill('Jamie');
  await page.getByLabel('Last Name *').fill('Student');
  await page.getByLabel('Gender *').selectOption('Female');
  await page.getByRole('button', { name: 'Next' }).click();
  await expect(page.getByRole('heading', { name: 'School Info' })).toBeVisible();
}

async function completeSchoolPage(page, { campus, state, status = 'Freshman' }) {
  await page.getByLabel('Name of college or university *').selectOption(campus);
  await page.locator('select[name="status"]').selectOption(status);
  await page.getByRole('radio', { name: state, exact: true }).check();
}

test.beforeEach(async ({ page }) => {
  await startRegistration(page);
  await completeContactPage(page);
});

test('standard registration reaches PayPal checkout', async ({ page }) => {
  await completeSchoolPage(page, { campus: 'UConn', state: 'Connecticut' });
  await page.getByRole('button', { name: 'Next' }).click();

  await expect(page.getByText('Page 3 of 3')).toBeVisible();
  await page.getByRole('radio', { name: 'I’ll pay for my registration now.' }).check();
  await page.getByRole('radio', { name: 'Yes' }).check();
  await page.getByRole('button', { name: 'Continue to Checkout' }).click();

  await expect(page.getByRole('heading', { name: 'Checkout' })).toBeVisible();
  await expect(page.getByText('$130.00')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Pay with PayPal' })).toBeVisible();
});

test('scholarship registration finishes without PayPal checkout', async ({ page }) => {
  await completeSchoolPage(page, { campus: 'Brown', state: 'Rhode Island' });
  await page.getByRole('button', { name: 'Next' }).click();

  await page.getByRole('radio', { name: 'I’d like to apply for a scholarship' }).check();
  await page.getByRole('radio', { name: 'Yes' }).check();
  await page.getByRole('button', { name: 'Continue to Checkout' }).click();

  await expect(page.getByRole('heading', { name: 'You’re registered' })).toBeVisible();
  await expect(page.getByText('We’ll email the scholarship application form', { exact: false })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Back to home' })).toBeVisible();
});

test('CCSU registration skips payment', async ({ page }) => {
  await completeSchoolPage(page, { campus: 'CCSU', state: 'Connecticut' });

  await expect(page.getByRole('button', { name: 'Complete Registration' })).toBeVisible();
  await expect(page.getByText('Page 2 of 2')).toBeVisible();
  await page.getByRole('button', { name: 'Complete Registration' }).click();

  await expect(page.getByRole('heading', { name: 'You’re registered' })).toBeVisible();
  await expect(page.getByText('contact Charles Savona', { exact: false })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Back to home' })).toBeVisible();
});

test('Massachusetts registration includes transportation', async ({ page }) => {
  await completeSchoolPage(page, { campus: 'MIT', state: 'Massachusetts' });
  await page.getByRole('button', { name: 'Next' }).click();

  await expect(page.getByRole('heading', { name: 'Transportation' })).toBeVisible();
  await expect(page.getByText('Page 3 of 4')).toBeVisible();
  await page.getByRole('radio', { name: 'I have a car and can give rides' }).check();
  await page.getByLabel('If you have a car, how many can you take').fill('4');
  await page.getByRole('button', { name: 'Next' }).click();

  await expect(page.getByText('Page 4 of 4')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Payment Options' })).toBeVisible();
});
