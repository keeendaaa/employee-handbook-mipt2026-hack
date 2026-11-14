import { test, expect, type Page } from "@playwright/test";
async function create(
  page: Page,
  question = "Синтетическая задача для проверки интерфейса",
) {
  await page.goto("/");
  await page.getByLabel("Ваша рабочая задача").fill(question);
  await page.getByRole("button", { name: "Разобрать задачу" }).click();
  await expect(page.getByText("План вашей задачи")).toBeVisible();
}
test("task → decomposition → evidence → progress → resume → material request → completion", async ({
  page,
}) => {
  await create(page);
  await expect(page.getByText("0 из 4 шагов выполнено")).toBeVisible();
  await page.getByRole("checkbox", { name: "Шаг 3 выполнен" }).check();
  await expect(page.getByText("1 из 4 шагов выполнено")).toBeVisible();
  await page
    .getByRole("link", { name: "2. Подготовьте тестовый кабинет." })
    .click();
  await expect(
    page.getByRole("heading", { name: "Подготовьте тестовый кабинет." }),
  ).toBeVisible();
  await page.locator(".sm-evidence-card summary").first().click();
  await page.getByRole("button", { name: "Открыть фрагмент" }).first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.locator("mark")).toHaveText(
    "Подготовьте тестовый кабинет.",
  );
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText("1 из 4 шагов выполнено")).toBeVisible();
  await page.getByRole("button", { name: "Разобрать этот шаг" }).click();
  await expect(
    page.getByRole("heading", { name: "Подробности по регламентам" }),
  ).toBeVisible();
  await page.getByRole("checkbox", { name: "Этот этап уже выполнен" }).check();
  await page.reload();
  await expect(page.getByText("2 из 4 шагов выполнено")).toBeVisible();
  await page
    .getByRole("button", {
      name: "Запросить недостающий материал",
      exact: true,
    })
    .click();
  await page
    .getByLabel("Чего не хватает?")
    .fill("Синтетический запрос материала");
  await page.getByRole("checkbox", { name: /Разрешаю передать/ }).check();
  await page.getByRole("button", { name: "Отправить запрос" }).click();
  await expect(
    page.getByRole("heading", { name: "Запрос сохранён" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Вернуться к задаче" }).click();
  await page.getByRole("link", { name: "Весь план задачи" }).first().click();
  await page.getByRole("checkbox", { name: "Шаг 1 выполнен" }).check();
  await page.getByRole("checkbox", { name: "Шаг 4 выполнен" }).check();
  await expect(page.getByText("4 из 4 шагов выполнено")).toBeVisible();
  await page
    .getByRole("button", { name: "Завершить задачу", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Задача завершена" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Снова открыть задачу" }).click();
  await page.getByRole("checkbox", { name: "Шаг 2 выполнен" }).uncheck();
  await expect(page.getByText("3 из 4 шагов выполнено")).toBeVisible();
  await page.getByRole("link", { name: "Вернуться позже" }).click();
  await page.getByRole("link", { name: /Синтетическая задача/ }).click();
  await expect(page.getByText("3 из 4 шагов выполнено")).toBeVisible();
});
test("technical errors stay errors; no-result has no invented steps", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByLabel("Ваша рабочая задача").fill("Технический сбой");
  await page.getByRole("button", { name: "Разобрать задачу" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Синтетический технический сбой",
  );
  await expect(page.getByLabel("Ваша рабочая задача")).toHaveValue(
    "Технический сбой",
  );
  await create(page, "Неизвестный вопрос");
  await expect(page.getByText("Ответ не подтверждён")).toBeVisible();
  await expect(page.getByRole("checkbox")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Завершить задачу" }),
  ).toHaveCount(0);
});
test("cancelled request cannot overwrite a new task", async ({ page }) => {
  await page.goto("/");
  await page
    .getByLabel("Ваша рабочая задача")
    .fill("Медленная синтетическая задача");
  await page.getByRole("button", { name: "Разобрать задачу" }).click();
  await page.getByRole("button", { name: "Остановить", exact: true }).click();
  await page
    .getByLabel("Ваша рабочая задача")
    .fill("Новая синтетическая задача после отмены");
  await page.getByRole("button", { name: "Разобрать задачу" }).click();
  await expect(async () => {
    const retry = page.getByRole("button", { name: "Повторить", exact: true });
    if (await retry.isVisible()) await retry.click();
    await expect(
      page.getByRole("heading", {
        name: "Новая синтетическая задача после отмены",
      }),
    ).toBeVisible({ timeout: 500 });
  }).toPass({ intervals: [100, 250, 500], timeout: 5000 });
  await expect(page.getByRole("alert")).toHaveCount(0);
});
test("admin: source map, public import, checks, material queue and mail settings", async ({
  page,
}) => {
  await page.goto("/#/admin/map");
  await page
    .getByRole("button", { name: /Тестовая процедура/ })
    .first()
    .click();
  await page.locator(".graph-fragment summary").first().click();
  await page.getByRole("button", { name: "Открыть источник" }).first().click();
  await expect(page.getByRole("dialog").locator("mark")).toHaveText(
    "Проверьте тестовый доступ.",
  );
  await page.keyboard.press("Escape");
  await page.goto("/#/admin/import");
  await page.getByLabel("Файл регламента").setInputFiles({
    name: "synthetic.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF synthetic UI test"),
  });
  await expect(
    page.getByRole("button", { name: "Добавить в базу" }),
  ).toBeDisabled();
  await page
    .getByRole("checkbox", { name: /Документ неконфиденциальный/ })
    .check();
  await page.getByRole("button", { name: "Добавить в базу" }).click();
  await expect(page.getByText("Синтетический импорт завершён.")).toBeVisible();
  await page.goto("/#/admin/checks");
  await page.getByLabel("Рабочая ситуация").fill("Неизвестный вопрос");
  await page
    .getByRole("checkbox", { name: /Вопрос неконфиденциальный/ })
    .check();
  await page.getByRole("button", { name: "Проверить по базе" }).click();
  await expect(
    page.getByText("В тестовой базе ответ не найден.").first(),
  ).toBeVisible();
  await page.goto("/#/admin/requests");
  await page.getByLabel("Доступ администратора").fill("synthetic-e2e-admin");
  await page.getByRole("button", { name: "Подключить" }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await page.goto("/#/admin/mail");
  await expect(page.getByText("synthetic@example.org")).toBeVisible();
  await expect(page.getByText("Доставка неизвестна")).toBeVisible();
  await page.getByLabel("Разрешённые отправители").fill("allowed@example.org");
  await page.getByRole("button", { name: "Сохранить настройки" }).click();
  await expect(page.getByText("Настройки сохранены")).toBeVisible();
  await page.getByRole("button", { name: "Поставить на паузу" }).click();
  await expect(page.getByText("На паузе")).toBeVisible();
});
for (const width of [320, 390, 1024, 1440, 1920])
  test(`responsive ${width}: plan, step and source`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await create(page, "Длинная синтетическая задача ".repeat(8));
    await expect(page.locator("body")).toHaveJSProperty("scrollWidth", width);
    await page
      .getByRole("link", { name: "3. Прочитайте тестовую инструкцию." })
      .click();
    await expect(
      page.getByRole("heading", { name: "Прочитайте тестовую инструкцию." }),
    ).toBeVisible();
    await expect(page.locator("body")).toHaveJSProperty("scrollWidth", width);
    await page.locator(".sm-evidence-card summary").first().click();
    await page
      .getByRole("button", { name: "Открыть фрагмент" })
      .first()
      .click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.locator("body")).toHaveJSProperty("scrollWidth", width);
    await page.keyboard.press("Escape");
    await page.screenshot({
      path: `test-results/step-${width}.png`,
      fullPage: true,
    });
  });
for (const width of [320, 390, 1024, 1440, 1920])
  test(`admin responsive ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    for (const section of ["documents", "import", "map", "checks", "mail"]) {
      await page.goto(`/#/admin/${section}`);
      if (section === "mail") {
        await page
          .getByLabel("Доступ администратора")
          .fill("synthetic-e2e-admin");
        await page.getByRole("button", { name: "Подключить" }).click();
        await expect(page.getByText("synthetic@example.org")).toBeVisible();
      }
      await expect(page.locator("body")).toHaveJSProperty("scrollWidth", width);
      if (width === 390 || width === 1440)
        await page.screenshot({
          path: `test-results/${section}-${width}.png`,
          fullPage: true,
        });
    }
  });
test("new task, plan, search controls, feedback queue and dirty mail settings", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: /Вид ответа/ }).click();
  await expect(page.getByText("Краткое резюме", { exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator(".page-content")).toHaveCSS("opacity", "1");
  await page.screenshot({
    path: "test-results/new-task-1440.png",
    fullPage: true,
  });
  await create(page);
  await expect(page.locator(".page-content")).toHaveCSS("opacity", "1");
  await page.screenshot({ path: "test-results/plan-1440.png", fullPage: true });
  await page.goto("/#/tasks");
  await page
    .getByRole("textbox", { name: "Найти задачу" })
    .fill("нет такой задачи");
  await expect(
    page.getByRole("heading", { name: "Задачи не найдены" }),
  ).toBeVisible();
  await page.request.post("/api/material-requests", {
    data: {
      question: "Синтетическая проверка очереди",
      message: "Проверяем маршрут до администратора",
      public_data: true,
    },
  });
  await page.goto("/#/admin/requests");
  await page.getByLabel("Доступ администратора").fill("synthetic-e2e-admin");
  await page.getByRole("button", { name: "Подключить" }).click();
  await expect(
    page.getByRole("heading", { name: "Проверяем маршрут до администратора" }),
  ).toBeVisible();
  await page
    .getByRole("article")
    .filter({ hasText: "Проверяем маршрут до администратора" })
    .getByRole("button", { name: "Взять на проверку" })
    .click();
  await expect(
    page
      .getByRole("article")
      .filter({ hasText: "Проверяем маршрут до администратора" }),
  ).toContainText("На проверке");
  await page.goto("/#/admin/mail");
  await expect(page.getByText("synthetic@example.org")).toBeVisible();
  await page.clock.install();
  await page.getByLabel("Разрешённые отправители").fill("dirty@example.org");
  await page.clock.fastForward(11000);
  await expect(page.getByLabel("Разрешённые отправители")).toHaveValue(
    "dirty@example.org",
  );
});
test("collapsed references, binary checkboxes and one field focus boundary", async ({
  page,
}) => {
  await create(page);
  const check = page.getByRole("checkbox", { name: "Шаг 1 выполнен" });
  await check.click();
  await expect(check).toBeChecked();
  await check.click();
  await expect(check).not.toBeChecked();
  await expect(page.getByText("0 из 4 шагов выполнено")).toBeVisible();
  const evidence = page.locator(".sm-evidence-card").first();
  await expect(evidence.locator("blockquote")).toBeHidden();
  await evidence.locator("summary").click();
  await expect(evidence.locator("blockquote")).toBeVisible();
  await evidence.locator("summary").click();
  await expect(evidence.locator("blockquote")).toBeHidden();
  await page.goto("/#/documents");
  const input = page.getByRole("textbox", { name: "Найти регламент" });
  await input.click();
  await expect(input).toHaveCSS("outline-style", "none");
  await expect(input).toHaveCSS("box-shadow", "none");
  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Tab");
  await expect(input).toBeFocused();
  await expect(page.locator(".halo-search")).toHaveCSS(
    "outline-style",
    "solid",
  );
});
test("regulation opens complete extracted text and immutable snapshot errors stay visible", async ({
  page,
}) => {
  await page.goto("/#/documents");
  await page.getByRole("button", { name: /Синтетический регламент/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Конец тестового материала.");
  await expect(dialog).toContainText("Версия aaaaaaaa");
  await page.screenshot({ path: "test-results/document-reader-1440.png" });
  await page.keyboard.press("Escape");
  const stale = await page.request.get(
    "/api/documents/" + "b".repeat(64) + "?corpus_revision=old",
  );
  expect(stale.status()).toBe(409);
  const missing = await page.request.get(
    "/api/documents/missing?corpus_revision=synthetic-e2e",
  );
  expect(missing.status()).toBe(404);
  await page.route("**/api/documents/**", (route) =>
    route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({
        detail: "Документ отсутствует в этой версии базы.",
      }),
    }),
  );
  await page.getByRole("button", { name: /Синтетический регламент/ }).click();
  await expect(page.getByRole("alert")).toContainText("Документ отсутствует");
});
for (const width of [320, 390, 1024, 1440, 1920])
  test(`graph navigation and fullscreen ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/#/admin/map");
    const svg = page.locator(".obsidian-graph");
    await expect(page.locator(".graph-point")).toHaveCount(3);
    const old = await page.locator("[data-camera]").getAttribute("transform");
    await page.getByRole("button", { name: "Увеличить карту" }).click();
    await expect(page.locator("[data-camera]")).not.toHaveAttribute(
      "transform",
      old!,
    );
    await page
      .getByRole("textbox", { name: "Найти узел на карте" })
      .fill("Тестовая процедура");
    await page.locator(".graph-search-results button").click();
    await expect(
      page.getByRole("complementary", { name: "Выбранный узел" }),
    ).toContainText("Тестовая процедура");
    await page.getByRole("button", { name: "Снять выбор узла" }).click();
    const node = page.getByRole("button", { name: "Темы: Тестовая процедура" }),
      before = await node.getAttribute("transform"),
      box = await node.locator(".graph-point").boundingBox();
    expect(box).not.toBeNull();
    await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
    await page.mouse.down();
    await page.mouse.move(
      box!.x + box!.width / 2 + 40,
      box!.y + box!.height / 2 + 20,
      { steps: 5 },
    );
    await page.mouse.up();
    await expect(node).not.toHaveAttribute("transform", before!);
    await page
      .getByRole("button", { name: "Развернуть карту на весь экран" })
      .click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    const rect = await dialog.boundingBox();
    expect(rect!.width).toBe(width);
    expect(rect!.height).toBe(1000);
    await expect(dialog.locator(".obsidian-graph")).toBeVisible();
    await expect(page.locator("body")).toHaveJSProperty("scrollWidth", width);
    await page.screenshot({
      path: `test-results/graph-fullscreen-${width}.png`,
    });
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(svg).toBeVisible();
    await page.getByRole("button", { name: "Фильтры карты" }).click();
    await page.getByRole("checkbox", { name: "Темы", exact: true }).uncheck();
    await expect(page.locator(".obsidian-node.topic")).toHaveCount(0);
    await page.getByRole("checkbox", { name: "Темы", exact: true }).check();
    await expect(page.locator(".obsidian-node.topic")).toHaveCount(1);
  });

test("dense graph keeps readable labels separate through resizing and zoom", async ({ page }) => {
  const original = await (await page.request.get("/api/map")).json();
  const documents = Array.from({ length: 20 }, (_, i) => ({ id: `dense-doc-${i}`, name: `Синтетический регламент ${i} с длинным названием` }));
  const topics = Array.from({ length: 32 }, (_, i) => ({ id: `dense-topic-${i}`, label: `Синтетическая область ${i} для проверки подписей`, count: 20,
    documents: [{ id: documents[i % documents.length].id, count: 20 }] }));
  await page.route(/\/api\/map(?:\?.*)?$/, route => route.fulfill({ json: { ...original, documents, topics, questions: [],
    edges: topics.slice(1).map((t, i) => ({ source: topics[i].id, target: t.id, kind: "similarity", similarity: 0.8 })) } }));
  await page.goto("/#/admin/map");
  await expect(page.locator(".graph-point")).toHaveCount(52);
  await page.evaluate(() => document.fonts.ready);
  for (const width of [1440, 390, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    await expect(async () => {
      const pairs = await page.locator("[data-graph-label]").evaluateAll(nodes => {
        const boxes = nodes.map(n => n.getBoundingClientRect());
        let overlaps = 0;
        for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
          const a = boxes[i], b = boxes[j];
          if (a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top) overlaps++;
        }
        return overlaps;
      });
      expect(pairs).toBe(0);
    }).toPass();
    await expect(page.locator("[data-graph-label]").first()).toBeVisible();
    await page.getByRole("button", { name: "Увеличить карту" }).click();
  }
});
test("static emblem, fragment-only highlight and reduced motion", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await create(page);
  await expect(page.locator(".page-content")).toHaveCSS("transform", "none");
  const check = page.getByRole("checkbox", { name: "Шаг 1 выполнен" });
  await check.click();
  await expect(check).toBeChecked();
  await check.click();
  await expect(check).not.toBeChecked();
  const logo = page.locator(".sm-sidebar .brand-emblem img");
  await expect(logo).toHaveAttribute("src", "/brand/mipt-emblem.jpg");
  await expect(logo).toHaveCSS("animation-name", "none");
  await expect(logo).toHaveCSS("transform", "none");
  expect(
    await logo.evaluate(
      (img: HTMLImageElement) => img.complete && img.naturalWidth > 0,
    ),
  ).toBe(true);
  const evidence = page.locator(".sm-evidence-card").first();
  await evidence.locator("summary").press("Enter");
  await expect(evidence.locator("summary")).toHaveAttribute(
    "aria-expanded",
    "true",
  );
  await expect(evidence.locator("blockquote")).toBeVisible();
  await expect(evidence.locator("mark")).toHaveCount(0);
  await expect(evidence.locator("blockquote")).toHaveCSS(
    "background-color",
    "rgba(0, 0, 0, 0)",
  );
  await expect(evidence.locator(".evidence-reveal")).toHaveCSS("opacity", "1");
  await evidence
    .locator("summary")
    .evaluate((node: HTMLElement) => node.blur());
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: "test-results/evidence-neutral-1440.png",
    fullPage: true,
  });
  await evidence.getByRole("button", { name: "Открыть фрагмент" }).click();
  await expect(page.getByRole("dialog").locator("mark")).toHaveCount(1);
  await expect(page.getByRole("dialog").locator(".modal-body")).toHaveCSS(
    "opacity",
    "1",
  );
  await page.screenshot({ path: "test-results/source-highlight-1440.png" });
  await page.keyboard.press("Escape");
  await expect(page.locator("mark")).toHaveCount(0);
  await evidence.locator("summary").press("Space");
  await expect(evidence.locator("summary")).toHaveAttribute(
    "aria-expanded",
    "false",
  );
  await expect(evidence.locator("blockquote")).toBeHidden();
});
for (const width of [320, 390, 1024, 1440, 1920])
  test(`checked situation spacing ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.route("**/api/map?include_questions=true", async (route) => {
      const response = await route.fetch();
      const data = await response.json();
      data.questions[0].question =
        "Как оформить заявку на отпуск и согласовать её с несколькими подразделениями?";
      data.questions[0].result.missing_information = [
        "В найденных фрагментах не описан порядок оформления заявки. ".repeat(
          8,
        ),
      ];
      await route.fulfill({ response, json: data });
    });
    await page.goto("/#/admin/checks");
    const card = page.locator(".checked-situation").first();
    await expect(card).toBeVisible();
    const text = await card.locator(".situation-description").boundingBox(),
      button = await card
        .getByRole("button", { name: "Открыть проверку" })
        .boundingBox(),
      heading = await card.locator("h3").boundingBox(),
      badge = await card.locator(".sm-badge").boundingBox();
    expect(button!.y - (text!.y + text!.height)).toBeGreaterThanOrEqual(20);
    expect(heading!.y - (badge!.y + badge!.height)).toBeGreaterThanOrEqual(12);
    await expect(page.locator("body")).toHaveJSProperty("scrollWidth", width);
    if (width === 390 || width === 1440) {
      await expect(card).toHaveCSS("opacity", "1");
      await expect(page.locator(".page-content")).toHaveCSS("opacity", "1");
      await page.screenshot({
        path: `test-results/checks-spacing-${width}.png`,
        fullPage: true,
      });
    }
  });
