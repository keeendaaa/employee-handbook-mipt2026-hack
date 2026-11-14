import {test,expect,type Page} from '@playwright/test';
async function create(page:Page,question='Синтетическая задача для проверки интерфейса'){
 await page.goto('/');await page.getByLabel('Ваша рабочая задача').fill(question);await page.getByRole('button',{name:'Разобрать задачу'}).click();
 await expect(page.getByText('План вашей задачи')).toBeVisible();
}
test('task → decomposition → evidence → progress → resume → material request → completion',async({page})=>{
 await create(page);await expect(page.getByText('0 из 4 шагов выполнено')).toBeVisible();
 await page.getByRole('checkbox',{name:'Шаг 3 выполнен'}).check();await expect(page.getByText('1 из 4 шагов выполнено')).toBeVisible();
 await page.getByRole('link',{name:'2. Подготовьте тестовый кабинет.'}).click();await expect(page.getByRole('heading',{name:'Подготовьте тестовый кабинет.'})).toBeVisible();
 await page.getByRole('button',{name:'Открыть фрагмент'}).click();
 const dialog=page.getByRole('dialog');await expect(dialog).toBeVisible();await expect(dialog.locator('mark')).toHaveText('Подготовьте тестовый кабинет.');
 await page.keyboard.press('Escape');await expect(dialog).toHaveCount(0);await expect(page.getByText('1 из 4 шагов выполнено')).toBeVisible();
 await page.getByRole('button',{name:'Разобрать этот шаг'}).click();await expect(page.getByRole('heading',{name:'Подробности по регламентам'})).toBeVisible();
 await page.getByRole('checkbox',{name:'Этот этап уже выполнен'}).check();await page.reload();await expect(page.getByText('2 из 4 шагов выполнено')).toBeVisible();
 await page.getByRole('button',{name:'Запросить недостающий материал',exact:true}).click();await page.getByLabel('Чего не хватает?').fill('Синтетический запрос материала');
 await page.getByRole('checkbox',{name:/Разрешаю передать/}).check();await page.getByRole('button',{name:'Отправить запрос'}).click();await expect(page.getByRole('heading',{name:'Запрос сохранён'})).toBeVisible();await page.getByRole('button',{name:'Вернуться к задаче'}).click();
 await page.getByRole('link',{name:'Весь план задачи'}).first().click();
 await page.getByRole('checkbox',{name:'Шаг 1 выполнен'}).check();await page.getByRole('checkbox',{name:'Шаг 4 выполнен'}).check();await expect(page.getByText('4 из 4 шагов выполнено')).toBeVisible();await page.getByRole('button',{name:'Завершить задачу',exact:true}).click();await expect(page.getByRole('heading',{name:'Задача завершена'})).toBeVisible();
 await page.getByRole('button',{name:'Снова открыть задачу'}).click();await page.getByRole('checkbox',{name:'Шаг 2 выполнен'}).uncheck();await expect(page.getByText('3 из 4 шагов выполнено')).toBeVisible();
 await page.getByRole('link',{name:'Вернуться позже'}).click();await page.getByRole('link',{name:/Синтетическая задача/}).click();await expect(page.getByText('3 из 4 шагов выполнено')).toBeVisible();
});
test('technical errors stay errors; no-result has no invented steps',async({page})=>{
 await page.goto('/');await page.getByLabel('Ваша рабочая задача').fill('Технический сбой');await page.getByRole('button',{name:'Разобрать задачу'}).click();await expect(page.getByRole('alert')).toContainText('Синтетический технический сбой');await expect(page.getByLabel('Ваша рабочая задача')).toHaveValue('Технический сбой');
 await create(page,'Неизвестный вопрос');await expect(page.getByText('Ответ не подтверждён')).toBeVisible();await expect(page.getByRole('checkbox')).toHaveCount(0);await expect(page.getByRole('button',{name:'Завершить задачу'})).toHaveCount(0);
});
test('cancelled request cannot overwrite a new task',async({page})=>{
 await page.goto('/');await page.getByLabel('Ваша рабочая задача').fill('Медленная синтетическая задача');await page.getByRole('button',{name:'Разобрать задачу'}).click();await page.getByRole('button',{name:'Остановить',exact:true}).click();await page.getByLabel('Ваша рабочая задача').fill('Новая синтетическая задача после отмены');await page.getByRole('button',{name:'Разобрать задачу'}).click();await expect(async()=>{const retry=page.getByRole('button',{name:'Повторить',exact:true});if(await retry.isVisible())await retry.click();await expect(page.getByRole('heading',{name:'Новая синтетическая задача после отмены'})).toBeVisible({timeout:500});}).toPass({intervals:[100,250,500],timeout:5000});await expect(page.getByRole('alert')).toHaveCount(0);
});
test('admin: source map, public import, checks, material queue and mail settings',async({page})=>{
 await page.goto('/#/admin/map');await page.getByRole('button',{name:/Тестовая процедура/}).first().click();await page.getByRole('button',{name:'Открыть источник'}).first().click();await expect(page.getByRole('dialog').locator('mark')).toHaveText('Проверьте тестовый доступ.');await page.keyboard.press('Escape');
 await page.goto('/#/admin/import');await page.getByLabel('Файл регламента').setInputFiles({name:'synthetic.pdf',mimeType:'application/pdf',buffer:Buffer.from('%PDF synthetic UI test')});await expect(page.getByRole('button',{name:'Добавить в базу'})).toBeDisabled();await page.getByRole('checkbox',{name:/Документ неконфиденциальный/}).check();await page.getByRole('button',{name:'Добавить в базу'}).click();await expect(page.getByText('Синтетический импорт завершён.')).toBeVisible();
 await page.goto('/#/admin/checks');await page.getByLabel('Рабочая ситуация').fill('Неизвестный вопрос');await page.getByRole('checkbox',{name:/Вопрос неконфиденциальный/}).check();await page.getByRole('button',{name:'Проверить по базе'}).click();await expect(page.getByText('В тестовой базе ответ не найден.').first()).toBeVisible();
 await page.goto('/#/admin/requests');await page.getByLabel('Доступ администратора').fill('synthetic-e2e-admin');await page.getByRole('button',{name:'Подключить'}).click();
 await expect(page.getByRole('alert')).toHaveCount(0);
 await page.goto('/#/admin/mail');await expect(page.getByText('synthetic@example.org')).toBeVisible();await expect(page.getByText('Доставка неизвестна')).toBeVisible();
 await page.getByLabel('Разрешённые отправители').fill('allowed@example.org');await page.getByRole('button',{name:'Сохранить настройки'}).click();await expect(page.getByText('Настройки сохранены')).toBeVisible();await page.getByRole('button',{name:'Поставить на паузу'}).click();await expect(page.getByText('На паузе')).toBeVisible();
});
for(const width of [320,390,1024,1440,1920])test(`responsive ${width}: plan, step and source`,async({page})=>{
 await page.setViewportSize({width,height:1000});await create(page,'Длинная синтетическая задача '.repeat(8));
 await expect(page.locator('body')).toHaveJSProperty('scrollWidth',width);
 await page.getByRole('link',{name:'3. Прочитайте тестовую инструкцию.'}).click();await expect(page.getByRole('heading',{name:'Прочитайте тестовую инструкцию.'})).toBeVisible();await expect(page.locator('body')).toHaveJSProperty('scrollWidth',width);
 await page.getByRole('button',{name:'Открыть фрагмент'}).click();await expect(page.getByRole('dialog')).toBeVisible();await expect(page.locator('body')).toHaveJSProperty('scrollWidth',width);await page.keyboard.press('Escape');
 await page.screenshot({path:`test-results/step-${width}.png`,fullPage:true});
});
for(const width of [320,390,1024,1440,1920])test(`admin responsive ${width}`,async({page})=>{
 await page.setViewportSize({width,height:1000});
 for(const section of ['documents','import','map','checks','mail']){
  await page.goto(`/#/admin/${section}`);
  if(section==='mail'){await page.getByLabel('Доступ администратора').fill('synthetic-e2e-admin');await page.getByRole('button',{name:'Подключить'}).click();await expect(page.getByText('synthetic@example.org')).toBeVisible();}
  await expect(page.locator('body')).toHaveJSProperty('scrollWidth',width);
  if(width===390||width===1440)await page.screenshot({path:`test-results/${section}-${width}.png`,fullPage:true});
 }
});
test('new task, plan, search controls, feedback queue and dirty mail settings',async({page})=>{
 await page.goto('/');await page.getByRole('button',{name:/Вид ответа/}).click();await expect(page.getByText('Краткое резюме',{exact:true})).toBeVisible();await page.keyboard.press('Escape');
 await page.screenshot({path:'test-results/new-task-1440.png',fullPage:true});await create(page);await page.screenshot({path:'test-results/plan-1440.png',fullPage:true});
 await page.goto('/#/tasks');await page.getByRole('textbox',{name:'Найти задачу'}).fill('нет такой задачи');await expect(page.getByRole('heading',{name:'Задачи не найдены'})).toBeVisible();
 await page.request.post('/api/material-requests',{data:{question:'Синтетическая проверка очереди',message:'Проверяем маршрут до администратора',public_data:true}});
 await page.goto('/#/admin/requests');await page.getByLabel('Доступ администратора').fill('synthetic-e2e-admin');await page.getByRole('button',{name:'Подключить'}).click();await expect(page.getByRole('heading',{name:'Проверяем маршрут до администратора'})).toBeVisible();await page.getByRole('article').filter({hasText:'Проверяем маршрут до администратора'}).getByRole('button',{name:'Взять на проверку'}).click();await expect(page.getByRole('article').filter({hasText:'Проверяем маршрут до администратора'})).toContainText('На проверке');
 await page.goto('/#/admin/mail');await expect(page.getByText('synthetic@example.org')).toBeVisible();await page.clock.install();await page.getByLabel('Разрешённые отправители').fill('dirty@example.org');await page.clock.fastForward(11000);await expect(page.getByLabel('Разрешённые отправители')).toHaveValue('dirty@example.org');
});
