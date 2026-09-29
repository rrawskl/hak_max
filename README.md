# ДЕЛО

Демонстрационный Mini App и бот для собственника ИП или ООО Санкт-Петербурга с 0–30 сотрудниками. Путь: профиль → объяснимый подбор → программа → план с чек-листом → напоминание. Приложение не подаёт заявку и не гарантирует одобрение. Все сведения о бизнесе вводит пользователь; реестры и задолженность автоматически не проверяются.

**Статус:** локальный MVP. Программы вымышлены и помечены «Демонстрационные данные». Реальный запуск в MAX, HTTPS-хостинг и доставку сообщений владельцу ещё нужно проверить с токеном и зарегистрированным ботом; см. [сверку с ТЗ](docs/compliance.md) и [отчёт о тестах](docs/test-report.md).

## Локальный запуск с Docker Compose

Нужны Docker Engine и Compose. Команды ниже — PowerShell из корня проекта:

```powershell
Copy-Item .env.example .env
(Get-Content .env) -replace 'DEV_AUTH_ENABLED=false','DEV_AUTH_ENABLED=true' -replace 'SEED_DEMO=false','SEED_DEMO=true' -replace 'REMINDER_DEMO_ENABLED=false','REMINDER_DEMO_ENABLED=true' | Set-Content .env
docker compose up --build -d
docker compose ps
docker compose logs --tail=80 init backend worker frontend
```

Откройте http://localhost:5173. Локальный demo-вход включён только этими настройками. В интерфейсе mock-уведомление получает статус «Симуляция» после обработки worker и не считается доставленным в MAX. API: http://localhost:8000/docs. Данные хранятся в PostgreSQL volume и сохраняются при `docker compose down` и повторном `up`.

Миграция и повторяемый seed по отдельности:

```powershell
docker compose run --rm init alembic upgrade head
docker compose run --rm init python -m app.seed
```

Повторный seed не сдвигает срок уже существующей программы или плана. Для нового учебного набора удаляйте volume только при осознанной очистке **локального demo**:

```powershell
docker compose down
# ВНИМАНИЕ: удаляет всю локальную demo-базу:
docker compose down -v
```

## Проверки

```powershell
docker compose exec backend pytest -q
docker compose --profile test run --rm frontend-build pnpm test
docker compose --profile test run --rm frontend-build pnpm run build
```

Для Playwright запустите стек, установите зависимости frontend и браузер, затем:

```powershell
cd frontend
pnpm install --frozen-lockfile
pnpm exec playwright install chromium
pnpm run test:e2e
```

На Windows с уже установленным Edge можно задать `$env:PLAYWRIGHT_CHANNEL='msedge'` перед E2E. Эти тесты используют demo-вход; реальный MAX проверяется отдельно.

## Настройка MAX и production

Официальный [MAX Bridge](https://dev.max.ru/docs/webapps/bridge) даёт raw `initData`, который backend проверяет по [официальной схеме](https://dev.max.ru/docs/webapps/validation) и времени выдачи. На клиенте токен сессии хранится только в памяти. Webhook принимает события после проверки заголовка `X-Max-Bot-Api-Secret`; подписка на него настраивается владельцем через [MAX API](https://dev.max.ru/docs-api/methods/POST/subscriptions). Реальная отправка использует [POST /messages](https://dev.max.ru/docs-api/methods/POST/messages). Не включайте polling одновременно с webhook.

Для production нужны зарегистрированный бот и Mini App, публичный HTTPS-домен с сертификатом, `MAX_TOKEN`, `MAX_BOT_NAME`, `MAX_WEBHOOK_SECRET`, `SESSION_SECRET`, точные HTTPS `PUBLIC_APP_URL`/`CORS_ORIGINS`, PostgreSQL и проверенный каталог из официальных источников. Установите `APP_ENV=production`, `USE_MOCK_MAX=false`, `DEV_AUTH_ENABLED=false`, `SEED_DEMO=false`. Приложение остановится при включённом demo или отсутствующих секретах. Synthetic-каталог в production API скрыт.

## Данные и ограничения

В БД хранятся MAX user ID, минимальное имя, профиль, планы, чек-листы, сессии и очередь уведомлений. Сессия живёт 2 часа. Сведения нужны только для персонального плана; хранение и удаление по запросу владельца требуют операционного процесса до пилота. Сканы, паспорт, банковские данные и заявки не хранятся. Статус `sent` означает принятие сообщения API MAX, не прочтение или доставку адресату. После сетевого тайм-аута возможен статус `uncertain`; без подтверждённой внешней идемпотентности нельзя обещать exactly-once.

Спецификация [OpenAPI](openapi.yaml) сгенерирована из FastAPI. [DATA-API.yaml](DATA-API.yaml) — черновик до получения точной схемы организаторов и публичного URL. Архитектура, сценарий и происхождение демоданных описаны в `docs/`.
