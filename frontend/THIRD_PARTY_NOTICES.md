# Источники компонентов и иллюстраций

- UI SDK: @ui-sdk/react и @ui-sdk/core0.1.0-beta.1, [vercel-labs/ui](https://github.com/vercel-labs/ui), Apache-2.0. Использованы Dialog и его части; без копирования стилей сайта.
- Cult UI: Halo Search и AI Instructions из официального registry, получены14 ноября2026: https://www.cult-ui.com/r/halo-search.json и https://www.cult-ui.com/r/ai-instructions.json. Исходники в src/components/ui, вспомогательные компоненты shadcn/ui; форматирование, локализация и токены адаптированы. Лицензия MIT в исходном проекте https://github.com/nolly-studio/cult-ui.
- shadcn/ui и Radix UI: доступные примитивы Popover, Dialog, Command и поля; MIT.
- Inter: @fontsource-variable/inter, SIL Open Font License1.1; файл лицензии поставляется npm-пакетом. Шрифт включён в локальные build assets.
- Lucide: ISC; Hugeicons: лицензии установленных npm-пакетов; Motion: MIT.
- Логотип МФТИ: официальный SVG с https://mipt.ru/upload/iblock/026/gh8ivafm65ve54a6uokw5ahvj8mjmecq/newMIPT-_1_.svg, обнаружен через logo.getItemsShort официального сайта 14 ноября2026. Файл public/brand/mipt-logo.svg используется без изменений. Права на знак принадлежат МФТИ; общий open-source статус логотипу не приписывается.
- Иллюстрации mipt-navigator.png, mipt-materials.png, mipt-completed.png созданы встроенным imagegen по заданию владельца проекта: оригинальные научные сцены с кобальтовыми акцентами, без копирования персонажей Notion. Режим и описания — public/illustrations/asset-manifest.json.
- d3-force3.0.0 и его зависимости: ISC. Используется только для вычисления расположения узлов; непрерывная симуляция останавливается после расчёта.

Ни один скриншот интерфейса Figma не используется как растровая реализация страницы.
