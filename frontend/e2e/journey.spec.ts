import { expect, test } from '@playwright/test';

test('profile → catalogue → plan → saved checklist across widths', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.getByRole('heading', { name: /Поддержка для вашего бизнеса|Здравствуйте/ })).toBeVisible();
  if (await page.getByRole('link', { name: 'Заполнить профиль' }).isVisible().catch(() => false)) {
    await page.getByRole('link', { name: 'Заполнить профиль' }).click();
    await page.getByLabel('Название бизнеса').fill('Проверка ДЕЛО');
    await page.getByLabel('Код отрасли').fill('services');
    await page.getByLabel('Число сотрудников').fill('3');
    await page.getByLabel('Дата регистрации').fill('2024-01-15');
    await page.getByRole('button', { name: 'Продолжить' }).click();
    await page.getByRole('button', { name: 'Сохранить профиль' }).click();
    await expect(page).toHaveURL('/');
  }
  await page.getByRole('link', { name: 'Поддержка' }).click();
  await page.getByLabel('Поиск').fill('консультационная');
  await expect(page.getByRole('heading', { name: 'Учебная консультационная поддержка' })).toBeVisible();
  await page.getByRole('link', { name: 'Подробнее' }).click();
  await expect(page).toHaveURL(/\/support\/consulting/);
  await expect(page.getByText('Срок не указан · МСК')).toBeVisible();
  const due = new Date(Date.now() + 20 * 86400_000);
  const local = `${due.getFullYear()}-${String(due.getMonth() + 1).padStart(2, '0')}-${String(due.getDate()).padStart(2, '0')}T12:00`;
  await page.getByLabel('Дата подготовки · МСК').fill(local);
  await page.getByRole('button', { name: 'Создать план подготовки' }).click();
  await page.waitForURL(/\/plans\//, { timeout: 2000 }).catch(async () => {
    await expect(page.getByRole('alert')).toContainText('Активный план');
    await page.getByRole('link', { name: 'Планы' }).click();
    await page.locator('article').filter({ hasText: 'Учебная консультационная поддержка' }).getByRole('link', { name: 'Открыть план' }).click();
  });
  await expect(page).toHaveURL(/\/plans\//);
  const item = page.getByRole('checkbox', { name: 'Описание запроса' });
  if (!(await item.isChecked())) await item.click();
  await expect(item).toBeChecked();
  await expect(page.getByText('100% выполнено')).toBeVisible();
  await page.reload();
  await expect(page.getByRole('checkbox', { name: 'Описание запроса' })).toBeChecked();
  for (const width of [360, 390, 480, 768, 1366, 1920]) {
    await page.setViewportSize({ width, height: 900 });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow, `horizontal overflow at ${width}px`).toBe(false);
  }
});

test('filters survive detail navigation; draft survives resize; API error can be retried', async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.goto('/support');
  await page.getByLabel('Поиск').fill('цифровизация');
  await page.getByRole('link', { name: 'Подробнее' }).click();
  await expect(page).toHaveURL(/\/support\/digital\?search=/);
  await page.getByRole('button', { name: '← К каталогу' }).click();
  await expect(page.getByLabel('Поиск')).toHaveValue('цифровизация');
  await page.getByRole('link', { name: 'Профиль' }).click();
  await page.getByLabel('Название бизнеса').fill('Черновик при изменении ширины');
  await page.setViewportSize({ width: 480, height: 900 });
  await expect(page.getByLabel('Название бизнеса')).toHaveValue('Черновик при изменении ширины');

  await page.route('**/api/v1/dashboard', route => route.abort());
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Не удалось загрузить данные' })).toBeVisible();
  await page.unroute('**/api/v1/dashboard');
  await page.getByRole('button', { name: 'Повторить' }).click();
  await expect(page.getByRole('heading', { name: /Здравствуйте/ })).toBeVisible();
});

test('program-specific answer changes matching without a percentage', async ({ page }) => {
  await page.goto('/support/equipment');
  await expect(page.locator('article').last().getByText('Нужно уточнить условия')).toBeVisible();
  await page.getByLabel('Есть налоговая задолженность?').selectOption('no');
  await page.getByRole('button', { name: 'Сохранить уточнение' }).click();
  await expect(page.locator('article').last().getByText('Предварительно подходит')).toBeVisible();
  await page.getByLabel('Есть налоговая задолженность?').selectOption('yes');
  await page.getByRole('button', { name: 'Сохранить уточнение' }).click();
  await expect(page.locator('article').last().getByText('Не подходит по условиям')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Создать план подготовки' })).toHaveCount(0);
  await page.getByLabel('Есть налоговая задолженность?').selectOption('unknown');
  await page.getByRole('button', { name: 'Сохранить уточнение' }).click();
  await expect(page.locator('article').last().getByText('Нужно уточнить условия')).toBeVisible();
});

test('confirmation closes with Escape and returns focus', async ({ page }) => {
  await page.goto('/plans');
  await page.locator('article').filter({ hasText: 'Учебная компенсация оборудования' }).getByRole('link', { name: 'Открыть план' }).click();
  const trigger = page.getByRole('button', { name: 'Завершить план' });
  await trigger.click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(trigger).toBeFocused();
});
