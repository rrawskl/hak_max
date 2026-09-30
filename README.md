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

Для запуска в рамках хакатона используйте **выданного организаторами бота**. Если есть только токен, узнайте его `username` запросом `GET https://platform-api2.max.ru/me` с заголовком `Authorization: <токен>` и укажите его в `MAX_BOT_NAME`. Не меняйте имя, ник или логотип выданного бота: согласно [общему FAQ](https://cloud.mail.ru/public/THoi/7pmGKgDYK) на онлайн-этапе это недоступно.

Разместите frontend и backend по публичному HTTPS-адресу. Ссылку Mini App передайте через [форму организаторов](https://sbor-ssylok-dlya-mini-prilojeniy.testograf.ru/); привязку к выданному боту выполняют они. Регистрироваться в «MAX для партнёров» для этого сценария не требуется. Для webhook настройте HTTPS endpoint через MAX API. Локальный `localhost` проверяет интерфейс и логику, но для теста внутри MAX нужен привязанный публичный адрес. После сдачи бот и приложение должны оставаться доступными на весь период проверки.

Для production также нужны `MAX_TOKEN`, `MAX_WEBHOOK_SECRET`, `SESSION_SECRET`, точные HTTPS `PUBLIC_APP_URL`/`CORS_ORIGINS`, PostgreSQL и проверенный каталог из официальных источников. Установите `APP_ENV=production`, `USE_MOCK_MAX=false`, `DEV_AUTH_ENABLED=false`, `SEED_DEMO=false`. Приложение остановится при включённом demo или отсутствующих секретах. Synthetic-каталог в production API скрыт. Административные настройки выданного бота меняют только организаторы; для недоступного через API действия обращайтесь к ним.

## Данные и ограничения

В БД хранятся MAX user ID, минимальное имя, профиль, планы, чек-листы, сессии и очередь уведомлений. Сессия живёт 2 часа. Сведения нужны только для персонального плана; хранение и удаление по запросу владельца требуют операционного процесса до пилота. Сканы, паспорт, банковские данные и заявки не хранятся. Статус `sent` означает принятие сообщения API MAX, не прочтение или доставку адресату. После сетевого тайм-аута возможен статус `uncertain`; без подтверждённой внешней идемпотентности нельзя обещать exactly-once.

Спецификация [OpenAPI](openapi.yaml) сгенерирована из FastAPI. [DATA-API.yaml](DATA-API.yaml) соответствует присланной [схеме DATA-API 1.0](https://gitverse.ru/stasnorman/example-data-api), но остаётся **шаблоном для сдачи**: `api.baseUrl` указывает на зарезервированный `api.example.org`, `teamId` не выдан, а подписанный `maxInitData`, `runId` и будущий `planDueAt` должны поступить проверяющей системе закрытым каналом. Тестовый MAX-пользователь должен иметь сохранённый профиль; каталог должен содержать хотя бы одну открытую подходящую программу с документом. Не отправляйте этот файл на проверку до заполнения реального адреса и тестовых данных. Архитектура, сценарий и происхождение демоданных описаны в `docs/`.

Проверка формата DATA-API из корня проекта (инструмент организаторов скачивается в игнорируемую папку):

```powershell
git clone --depth 1 https://gitverse.ru/stasnorman/example-data-api.git .reference/example-data-api
python -m pip install -r .reference/example-data-api/requirements.txt
python .reference/example-data-api/validate_data_api.py DATA-API.yaml --schema .reference/example-data-api/Example/DATA-API.schema.json --openapi openapi.yaml
```
