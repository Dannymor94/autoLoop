# autoLoop — подробный план реализации v0.2-r1

**Дата:** 19 ноября 2026 г.  
**Статус:** уточнённый план до старта AL-001; платформа-исполнитель ещё не выбрана.  
**Принцип:** deterministic-first, минимум LLM и ручных действий, управление с мобильного телефона, подписочные Claude Code / Codex CLI без обязательного платного API.  
**Приоритет:** сначала доказать надежность исполнения и QA, затем расширять интерфейсы.

## 1. Целевой результат

Пользователь создаёт задачу с телефона, выбирает проект и ограничения, затем:

1. Диспетчер фиксирует версию спецификации и выбирает исполнителя по детерминированным правилам.
2. Claude Code или Codex запускается через существующий CLI-логин на Mac/Ubuntu/выделенной машине в изолированном рабочем каталоге и ветке Git.
3. Код, тесты, логи и отчёты становятся доступны через GitHub и журнал autoLoop.
4. Независимый QA проверяет результат и CI **на конкретном полном SHA**; устаревший PASS недействителен.
5. При исправлениях применяется конфигурируемый предел повторных циклов, затем ESCALATED.
6. После перезапуска компьютера или смерти процесса система восстанавливает состояние без потери задачи и без дублирования опасных действий.
7. На телефоне видны статусы, токены, заполненность контекста, PR и запросы разрешений; терминал доступен только при необходимости.

**Не входят в первый MVP:** собственная LLM-модель для координации, сложный визуальный редактор workflow, коммерческий SaaS, публично доступный терминал, автоматическое чтение ответов из браузерного ChatGPT.

## 2. Архитектурное решение

```text
Мобильный интерфейс (готовый UI платформы; PWA — только если UI недостаточен)
             │  HTTPS/MCP/WebSocket через приватный туннель
             ▼
autoLoop Core: SQLite/WAL + states.yaml + outbox + evidence/gates
             │  Executor Adapter: унифицированный запуск/статусы/команды
             ▼
Выбранный OSS-исполнитель: Bernstein ИЛИ Kandev ИЛИ Cezar
             │
             ├── CLI Runner Claude Code в отдельном worktree
             └── CLI Runner Codex в отдельном worktree
                         │
                         ▼
                    GitHub + CI

Отдельный Chat Bridge: только доставка текста в выбранный браузерный чат;
не входит в критический путь автоматического QA.
```

**Разделение ответственности:** всё, что входит в `states.yaml`, принадлежит autoLoop. OSS-платформа — только исполнитель: процессы, изоляция рабочих каталогов, сессии и технические события. Её очередь, статус «completed», внутренние retry и merge-гейты не вправе самостоятельно переводить задачу autoLoop в DONE или MERGING. Если готовая платформа не позволяет отключить конкурирующие автоматические действия, она не проходит обязательный критерий 4.

В `docs/ADR-001-executor.md` обязательна таблица владельцев функций; предварительное нормативное распределение:

| Функция | Единственный владелец | Разрешённая роль другого слоя |
|---|---|---|
| Очередь задач, приоритеты и зависимости | **autoLoop** | Платформа принимает только явно выданный run; её внутренняя очередь не назначает следующие задачи |
| Lease, fencing token, восстановление claim | **autoLoop** | Платформа сообщает PID/session и heartbeat без самостоятельного повторного claim |
| Retry на уровне задачи и `repair_count` | **autoLoop** | Только ограниченные транспортные повторы внутри той же attempt, без нового цикла исправлений |
| Создание и уборка Git worktree | **Платформа** | autoLoop фиксирует путь, ветку, base/head SHA и проверяет изоляцию |
| CLI-процесс, сессия, stdout/stderr, токены | **Платформа** | autoLoop собирает события и при необходимости прерывает процесс |
| Присвоение task status: READY/RUNNING/.../DONE | **autoLoop** | Внутренние run-status платформы являются только сигналами, не источником истины |
| Финальный QA PASS/FAIL и журнал evidence | **autoLoop** | Платформа передаёт результаты, не утверждает их |
| GitHub merge, закрытие Issue/PR и релизный gate | **autoLoop** | У платформы отключены auto-merge и auto-close; она не имеет соответствующих credentials |
| Mobile Stop/Resume и owner-policy | **autoLoop** | Платформа выполняет подтверждённый interrupt/resume, но не изменяет canonical state |

Технологии собственного слоя: Python 3.12+, FastAPI, **SQLite/WAL через SQLAlchemy + Alembic**, Pydantic, YAML, WebSocket/SSE, GitHub Actions, Tailscale. На MVP один writer/dispatcher и один хост. PostgreSQL вводится в multi-host этапе при нескольких писателях: логическая схема и миграции сохраняются, а сетевые SQLite-файлы не используются. **Не писать второй планировщик задач поверх платформы: autoLoop определяет состояния и очередь, платформе делегируется только исполнение.**

## 3. Этап 0 — стандартизированный пилот OSS (2–4 рабочих дня)

### Кандидаты

| Проект | Зачем тестируем | Риски |
|---|---|---|
| [Bernstein](https://github.com/sipyourdrink-ltd/bernstein) | Python-планировщик без LLM на переходах, worktree, merge-гейты, восстановление | Бета; собственная `.sdd/` очередь/статусы/бюджеты должны быть ограничены режимом исполнителя; проверить отключение auto-merge/auto-close |
| [Kandev](https://github.com/kdlbs/kandev) | MCP, SSH/Docker исполнители, мобильный WebUI, YAML | Большая система, Go+Node toolchain, AGPL-3.0 |
| [Cezar](https://github.com/open-mercato/cezar) | CLI-логины, workflow-граф, webhooks, CI wait, мобильный UI | Доказать запрет авто-merge/auto-close и отключение автономного перехода к следующей задаче |

### Один тестовый репозиторий, одинаковые задания

Создать отдельный **одноразовый** GitHub-репозиторий `autoloop-pilot-fixture` (не запускать тесты на audiobook/Мастерская/production). Зафиксировать baseline SHA, версии платформ и конфиги. В репозитории маленький Python-пакет с `pytest`, `ruff`, `pyright`, простым GitHub Actions workflow; никаких секретов и реальных данных.

Пять идентичных сценариев для **каждого** кандидата:

| ID | Сценарий | Доказательство |
|---|---|---|
| PILOT-T1 | Создать небольшую функцию и тест, получить ветку/PR через Claude Code | PR + HEAD SHA + CI; подтверждён логин по подписке, API-ключ не использован |
| PILOT-T2 | Выполнить фиксированный YAML-план дважды с mock-исполнителями; сравнить задачи, назначения и переходы | Байтово равные нормализованные графы/события (исключая таймстемпы и идентификаторы попыток); LLM вызовы координации = 0 |
| PILOT-T3 | Прервать SIGKILL агенту и диспетчеру после claim и после side effect; перезапустить | Не потеряны записи, нет двух активных владельцев lease, повтор не создаёт второй PR/коммит/действие |
| PILOT-T4 | Попытаться включить авто-merge/auto-close в платформе; послать успешные run/CI события при незавершённом внешнем QA | Платформа не может объединить PR или закрыть **задачу autoLoop**; даже собственное `completed` платформы не переводит autoLoop в DONE/MERGING. Если платформа умеет писать напрямую в GitHub, такие права отсутствуют |
| PILOT-T5 | Смоделировать два FAIL ревью подряд и повторяющуюся ошибку; подключиться с Android через VPN | Лимит `max_repair_cycles=2` соблюдается; повторный `failure_fingerprint` эскалирует сразу; с телефона доступны status/stop/resume/report |

### Бинарный чек-лист допуска

Счёт 0–6, каждый пункт получает только `PASS` или `FAIL`; `NOT_TESTED` не засчитывается. PASS только по воспроизводимому тесту и сохранённым логам:

1. Действительно работают подписочные CLI-логины **обоих** Claude и Codex.
2. Переходы координации определяются кодом и планом, а не LLM. **Обязательно.**
3. После `kill -9` состояние восстанавливается без дублей и потерь. **Обязательно.**
4. Платформа не может сама выполнить merge/auto-close или перевести задачу autoLoop в DONE/MERGING: auto-merge выключен, полномочия отозваны, финальный merge/close выполняет только autoLoop. **Обязательно.**
5. С телефона можно безопасно остановить/продолжить задачу и прочитать статус.
6. Лимит исправлений задан конфигурацией и соблюдается на перезапуске.

**Победитель:** максимум PASS среди прошедших 2–4. При равенстве: меньше специальных патчей, меньше привилегий на хосте, более простой импорт/экспорт состояния и maintenance. Если никто не прошёл 2–4, не объявлять победителя: сначала устранить минимально возможный дефект или сменить исполнителя. Отдельные stale-SHA, base-drift и QA read-only тесты выполняет собственный autoLoop (этап 3), а не оцениваемый OSS-исполнитель.

### Уже выполнено в ознакомительном прогоне

- Исходники всех трёх проектов скачаны в изолированный тестовый каталог.
- Cezar: **51/51 PASS** в пяти родных тестовых модулях: webhooks, workflow graph, graph execution, autonomous recovery и run lease. Это тесты разработчиков Cezar, **не** прохождение PILOT-T1…T5.
- Bernstein: **52 PASS, 3 SKIP** в четырёх родных тестовых модулях (crash recovery, freshness gate, retry budgets, mock adapter). Не заменяет реальный PILOT-T3/T4.
- Kandev: **63/63 PASS** в автономных тестах валидации публичной документации (`scripts/validate-public-docs.test.mjs`). Они не проверяют orchestration; полноценному backend-прогону нужен Go toolchain требуемой версии, PILOT-T1…T5 остаются `NOT_TESTED`.
- Реальные подписочные Claude- и Codex-сессии, мобильный Android и сценарии SIGKILL над тремя реальными демонами ещё **не проверялись**.

## 4. Этап 1 — зафиксировать контракты autoLoop (2 рабочих дня)

### Файлы-контракты

```text
contracts/states.yaml          # единственный нормативный граф переходов
contracts/task.schema.json     # постановка задачи и acceptance_spec_hash
contracts/runner-events.json   # нормализованные события от платформы
contracts/evidence.schema.json # exact-SHA, base, suite и проверенный merge-ref
contracts/policies.yaml        # лимиты циклов, timeout, роли и protected paths
docs/ADR-001-executor.md       # выбор OSS + матрица владельцев + PILOT
scripts/generate_agent_docs.py # детерминированный генератор разделов для агентов
AGENTS.md                      # генерируемый раздел правил и статусов
CLAUDE.md                      # такой же синхронизированный раздел
```

Нормативные статусы v0.2-r1: `READY`, `RUNNING`, `VERIFYING`, `MERGING`, `DONE`, `BLOCKED`, `ESCALATED`, `SUPERSEDED`. Внутренние технические состояния/статусы платформы отображаются в события, но не добавляются произвольно в canonical state machine. При необходимости `RETRY_WAIT` оформляется отдельной архитектурной поправкой.

Из `states.yaml` генерируются: таблица допустимых переходов, отрицательные тесты и диаграмма состояний. Перед записью перехода диспетчер проверяет `expected_state`, `task_version`, `fencing_token` и обязательные evidence-gates.

Правила миграции задач между планами: одинаковые `acceptance_spec_hash` **и** зависимости → перенос без вызова LLM; иначе `SUPERSEDED`. После DONE предшественника зависимые BLOCKED становятся READY при выполнении остальных условий; после отмены предшественника остаются BLOCKED с эскалацией.

**Stop/Resume с телефона:** подтверждённый `Stop` останавливает исполнителя и переводит задачу `RUNNING → BLOCKED(reason=OWNER_STOP)` с checkpoint. До подтверждения сигнал остаётся `STOP_PENDING` в журнале команд, а UI не показывает ложный «остановлено». `Resume` разрешён из `BLOCKED(reason=OWNER_STOP)` после проверки lease и зависимостей; переход — в READY. Отдельную необратимую команду Cancel в MVP не добавлять: если потребуется, она получит свой статус/контракт и отдельный gate.

**Единые инструкции для агентов:** генерировать только явно маркированные разделы `AGENTS.md` и `CLAUDE.md` из контрактов: состояния, allowed transitions, текущие лимиты, protected paths, schema отчёта и правила эскалации. Не перезаписывать свободный текст пользователя вне этих разделов. `scripts/generate_agent_docs.py --check` в CI должен падать при любом несоответствии файлов контрактам. Агент читает нормативные правила из репозитория, а не из непроверенного динамического промпта.

## 5. Этап 2 — durable dispatcher и адаптер исполнителя (3–5 дней)

### Минимальные сущности SQLite/WAL

`projects`, `plans`, `tasks`, `task_dependencies`, `attempts`, `runner_sessions`, `events`, `leases`, `outbox`, `evidence`, `qa_verdicts`, `approvals`, `usage_samples`, `command_receipts`.

Схема описана моделями SQLAlchemy и миграциями Alembic без SQLite-специфичных бизнес-инвариантов. На MVP один диспетчер и один writer, WAL и `busy_timeout`; операции claim + запись outbox совершаются одной транзакцией. Переход на PostgreSQL — отдельный миграционный gate перед несколькими dispatcher-writers или multi-host, с проверкой тех же инвариантов.

Все команды получают `request_id` **от диспетчера**, `idempotency_key`, `payload_hash` и явную целевую пару `(project_id, task_id)`. Повтор команды возвращает старую запись, но не создаёт новый запуск.

Runner API: `start`, `stop`, `interrupt`, `resume`, `status`, `get_logs`, `get_usage`, `checkpoint`, `compact_if_supported`. `/clear` не отправляется вслепую: сначала сохраняется checkpoint, затем инициируется новая сессия. Если метод не поддерживается платформой — явный `UNSUPPORTED`, без имитации успеха.

В адаптере запрещены самостоятельные `merge`, `close issue`, `claim next task`, `retry repair` и обновление autoLoop state. Он получает `task_id/attempt_id`, выполняет одну попытку, возвращает наблюдаемые события и ждёт следующую явную команду. Для каждого OSS зафиксировать флаги отключения встроенной автономии и проверить их после рестарта. Платформа может внутренне отметить **run** завершённым, но не autoLoop **task**.

Lease: только один активный владелец попытки; heartbeat; `fencing_token` монотонно увеличивается при перехвате; устаревший worker не имеет права публиковать итог. Outbox и прием webhook работают по принципу at-least-once delivery + идемпотентная обработка; не обещать exactly-once execution для внешних систем без идемпотентных API.

Результат этапа: из телефона/API можно отправить задачу, получить нормализованные события, остановить/возобновить без потери единого журнала и без скрытого второго scheduler. `OWNER_STOP` является проверяемым блокирующим состоянием.

## 6. Этап 3 — независимый QA и merge-гейты (3–4 дня)

Делать по архитектурным мотивам Chipping Orchestrator, **не включать его как исполняемую production-зависимость**. Все операции merge и закрытия Issue/PR проходят только через autoLoop с отдельным GitHub credential, который не выдаётся платформе и QA. Для любой попытки:

1. Исполнитель публикует **полные** `head_sha`, `base_sha`, diff, список проверок, machine-readable отчёт. Base закрепляется на момент постановки QA.
2. CI проводит статические проверки и тесты. На GitHub PR CI может выполнять тесты на синтетическом merge-ref, поэтому отдельно фиксируются `head_sha`, `base_sha`, `tested_merge_sha` или `tested_tree_sha`, фактически проверенный workflow/ref и его результат. Нельзя подменять проверенный merge-ref простым head SHA.
3. Независимый Codex QA получает acceptance specification, diff, точные SHA, команды и результаты воспроизведения — **без** истории/рассуждений разработчика. Каждый QA начинается в новой сессии и отдельном read-only checkout (или read-only mount), где нет GitHub push/merge credentials. Для логов — отдельная временная writeable директория, не меняющая проверяемый код.
4. `suite_fingerprint = sha256(canonical_json({check_commands, lockfile_sha256_by_path, ci_workflow_sha256_by_path, tool_versions}))`. Если меняется команда, lockfile, CI workflow или версия существенного инструмента — старые evidence недействительны.
5. `evidence_key = sha256(canonical_json({project_id, task_id, acceptance_spec_hash, head_sha, base_sha, tested_tree_sha, suite_fingerprint}))`. Хеши сериализуются без неоднозначных разделителей, с фиксированным порядком ключей.
6. `PASS` валиден только при совпадении `head_sha`, `base_sha`, проверенного дерева/merge-ref, acceptance, suite fingerprint, независимого вердикта и CI success. Перед merge автоLoop заново считывает текущий base: при изменении `base_sha` — возврат в VERIFYING, даже если `head_sha` не изменился. Альтернатива «branch up to date» допускается лишь при доказанном эквивалентном дереве и новой CI-проверке.
7. Любой новый коммит, сдвиг base либо изменение набора проверок инвалидации evidence переводит на повторную VERIFYING. Старая ссылка на green CI не проходит.
8. Для FAIL формируется `failure_fingerprint = sha256(canonical_json({sorted_failed_test_node_ids, normalized_error_code, failure_stage}))`. Нормализация удаляет непостоянные timestamps/пути/stack-адреса; свободный текст LLM не используется как ключ. Если тот же отпечаток возник **вновь в другой попытке той же задачи**, сразу `ESCALATED(reason=REPEATED_FAILURE)` независимо от остатка `max_repair_cycles`. Иначе возможен следующий цикл, пока `repair_count < max_repair_cycles`; при исчерпании — `ESCALATED(reason=REPAIR_LIMIT)`.
9. Два обязательных отрицательных теста: (a) QA PASS по head=A/base=X после обновления base до Y → отказ `STALE_BASE_SHA`; (b) QA-раннер пытается изменить исходники и выполнить `git push` → OS/credentials отказ, ни один ref не изменён.

Protected paths, секреты, действия во внешних системах и публикация остаются под отдельными политиками. Автоматический merge разрешается **только** autoLoop там, где политика проекта явно это допускает и все exact-SHA/base-tree gates выполнены. Наличие зелёного CI, текста `PASS` или статуса `completed` у OSS-платформы само по себе никогда не открывает merge.

## 7. Этап 4 — жизненный цикл и управление контекстом (2–3 дня)

- Collectors читают CLI event stream, token usage, context usage, текущую модель, время работы и ошибки. Ничего не оценивают по тексту ответа, если есть структурированные поля.
- Различать `total_input_tokens`, `total_output_tokens`, кэш, текущую заполненность окна контекста и лимит подписки. Если провайдер не сообщает остаток квоты — `UNKNOWN`.
- Пример настраиваемых порогов: 65% — checkpoint suggested; 80% — подготовка миграции в новую сессию. Порог не обрывает активную запись или merge.
- Checkpoint: план, идентификаторы сессии, repo SHA, summary, evidence, открытые вопросы, следующий безопасный шаг. После рестарта восстановить состояние без повторной LLM-декомпозиции.
- Учитывать код ошибки, timeout, auth rejection, throttling/rate limit, context overflow. События разделять на `RETRYABLE`, `BLOCKED_CREDENTIALS`, `REQUIRES_OWNER`, `FATAL` с настраиваемыми retry/backoff.

## 8. Этап 5 — мобильное управление (2–4 дня)

Сначала оценить встроенный WebUI победителя **как отображение наблюдений**. Все изменяющие команды (`Stop`, `Resume`, merge, retry, закрытие задачи) должны проходить через autoLoop API и `states.yaml`; если встроенный UI позволяет обойти их, он непригоден как управляющий интерфейс. В таком случае — минимальная PWA поверх autoLoop API: проекты, задачи, очереди, статусы, логи, отчёты, QA-решения, model/session, токены, `Stop/Resume`, кнопка открытия SSH-туннеля.

Подключение через Tailscale/WireGuard с авторизацией, журналом управляющих действий и подтверждениями опасных операций. Никаких публичных терминалов, постоянных bearer-токенов в фронтенде или неограниченной команды shell из WebUI.

## 9. Этап 6 — связь с браузерными чатами (2–3 дня, после MVP)

Чат архитектуры не участвует в автоматических scheduler-tick. Главный канал передачи результатов — GitHub + MCP/ссылки на evidence. Расширение Chrome только доставляет явно адресованный текст в выбранный чат; оно не читает ответы модели и не запускает команды на компьютере.

Обязательные свойства собственного bridge: `request_id` от диспетчера, `sha256(text) == payload_hash`, строгая идентификация браузерного профиля/чата, занятый editor → `UNKNOWN`/отказ, никакого повторного `send` без подтверждения статуса. Разделить `DRAFTED`, `UI_CONFIRMED`, `UNKNOWN`; UI_CONFIRMED не означает обработку моделью. Для claude.ai предпочтителен ручной click пользователя. ChatCMD использовать только как источник идей по chat binding и composer readiness.

## 10. Этап 7 — распределённые runner-узлы и безопасность (3–5 дней)

Начальный runner на Mac; Ubuntu/gamebox подключать после стабильного локального контура. VPS в Германии опционален как relay/панель без размещения пользовательских исходных данных. Агентский runner инициирует исходящее шифрованное соединение, подтверждает идентичность и получает scoped commands. Источник истины остаётся один. При добавлении второго writer выполнить миграцию SQLite → PostgreSQL через Alembic + проверяемый перенос текущего состояния/счётчиков/evidence/outbox; одновременно писать в оба хранилища запрещено.

Отдельный Git worktree **не является** OS-песочницей. При полном shell-доступе использовать dedicated OS user / container / VM с минимальными правами; никогда не размещать `--dangerously-skip-permissions` на хосте с приватными файлами без дополнительной изоляции. Chipping Orchestrator напрямую допустим только в отдельной VM для исследований.

## 11. Плановые задачи разработки

| ID | Этап | Результат | Гейт |
|---|---|---|---|
| AL-001 | Pilot | Тестовый repo + пять воспроизводимых сценариев | Acceptance fixtures frozen |
| AL-002 | Pilot | Bernstein результаты 1–6 | Evidence links, PASS/FAIL/NOT_TESTED |
| AL-003 | Pilot | Kandev результаты 1–6 | То же |
| AL-004 | Pilot | Cezar результаты 1–6 | То же |
| AL-005 | Pilot | ADR победителя + матрица единственных владельцев | Обязательные 2–4 PASS; auto-merge/close платформы выключены |
| AL-101 | Contracts | states.yaml, схемы, переходы, OWNER_STOP, генерация AGENTS.md/CLAUDE.md | CI + проверка синхронизации generated docs |
| AL-102 | Dispatcher | SQLite/WAL, SQLAlchemy/Alembic, leases, outbox, idempotency | Crash tests, single-writer invariant |
| AL-103 | Runner | Адаптер выбранного OSS, CLI events | End-to-end fixture |
| AL-104 | QA | head/base/tested-tree evidence, independent read-only QA, CI webhook, failure fingerprint | stale-head, stale-base, denied QA-push, duplicate-failure tests |
| AL-105 | Context | checkpoints, token metrics, recovery | restart/compact tests |
| AL-106 | Mobile | Закрытый доступ, статусы и команды | Android E2E |
| AL-107 | Browser | Односторонний delivery bridge | fail-closed UI tests |
| AL-108 | Hardening | Multi-host, RBAC, recovery chaos | Final acceptance |

Пример задания агенту (на английском — рабочий стандарт проекта):

> **Task AL-001 — Build a reproducible OSS orchestrator pilot fixture.** Create a disposable Python repository with five deterministic tasks, mock Claude/Codex adapters, SIGKILL crash points, and a bounded two-cycle repair fixture. The platform must only execute; task queue, canonical state, task retry, and final merge/close are owned by autoLoop. Prove that built-in auto-merge and auto-close are disabled and cannot bypass autoLoop gates. Add separate autoLoop fixture tests for stale head/base SHA, repeated failure fingerprints, STOP→BLOCKED(reason=OWNER_STOP), and denied Git push from a fresh read-only QA runner. Do not access production repositories or credentials. Provide commands, baseline SHA, normalized JSON event traces, test logs, and a PASS/FAIL/NOT_TESTED report per candidate. Do not infer PASS from documentation. Do not merge to any production branch.

## 12. Приёмка MVP / Definition of Done

MVP выпускается только когда:

- Исполнитель выбран на воспроизводимом пилоте, пункты 2–4 имеют PASS.
- Одна задача создана с Android и выполнена на Mac с локальным CLI-логином; владелец не копирует отчёты вручную.
- После принудительной остановки runner и dispatcher восстановлены сессия, очередь, lease и журнал; дубли внешних действий отсутствуют.
- PASS по устаревшему head **или base** SHA гарантированно отклонён; CI и независимый QA подтверждают фактически протестированное дерево, включая merge-ref.
- QA имеет read-only доступ, fresh context, не получает историю рассуждений разработчика; попытка push из QA технически отклоняется.
- Число циклов исправления ограничено YAML; повторный `failure_fingerprint` вызывает досрочную ESCALATED.
- Stop с телефона после подтверждения прерывания переводит задачу в BLOCKED(reason=OWNER_STOP), Resume возвращает READY.
- Generated-разделы AGENTS.md/CLAUDE.md синхронизированы с contracts/ и проверяются CI.
- Есть доступный с телефона progress/status tracker, токены и ошибки отображаются честно, без выдумывания подписочных квот.
- Безопасность: нет публичного shell, опасные права изолированы, protected paths и секреты недоступны агентам по умолчанию.
- Документация и тестовые доказательства хранятся рядом с кодом, обновляются в одном PR.

## 13. Сроки, зависимости, риски

Оценка для одного разработчика при поддержке CLI-агентов (не обещание календарных сроков): **основной MVP с мобильным доступом 14–22 рабочих дня**, включая пилот; browser bridge, multi-host и дополнительное hardening — ещё **5–8 дней**. Реальный срок зависит от качества внешних hooks выбранной платформы и стабильности авторизации.

**Критические блокеры:** отсутствие проверенного CLI-логина одного из провайдеров; невозможность выключить платформенный auto-merge/auto-close; отсутствие настоящего crash recovery; неполная изоляция shell/QA; неопределённость политики merge для конкретного production repo.

**Снижение рисков:** пилот на одноразовом репозитории, mock-agents для координатора, фиксированные версии OSS, `states.yaml` как single source, минимальный adapter layer; browser bridge и multi-host только после принятия исполнительного ядра.

## 14. Проверенные источники и версии

- Bernstein: [GitHub](https://github.com/sipyourdrink-ltd/bernstein), [архитектура](https://docs.bernstein.run/en/latest/architecture/ARCHITECTURE/), локальный ознакомительный commit `b6eea60f4d7a7e7523a28ea4f38abd76b2b4fc3c`.
- Kandev: [GitHub](https://github.com/kdlbs/kandev), [automation and MCP](https://github.com/kdlbs/kandev/blob/main/docs/public/automation-and-mcp.md), локальный commit `70875454752757e9a5c131a3df6ceb2c0c386dbd`.
- Cezar: [GitHub](https://github.com/open-mercato/cezar), [workflow reference](https://github.com/open-mercato/cezar/blob/main/docs/reference.md), локальный commit `0272089546279584f976dfcf9081ff8a477b80f3`.
- QA inspiration: [Chipping Orchestrator](https://github.com/chippingway/chipping-orchestrator).
- Browser design inspiration: [ChatCMD](https://github.com/int04/ChatCmd).

**План является проектным решением; матрица кандидатов останется `NOT_TESTED`, пока независимые acceptance-сценарии не завершены.**
