# Разработка

## Требования

* Python 3.10+ (для Studio достаточно 3.10; в Docker используется 3.12)
* Node.js 20+ — только если нужно пересобирать фронтенд
* Docker — необязательно

## Быстрый запуск

### Всё в одном процессе (как у пользователя)

```bash
pip install -e ".[studio]"
cd frontend && npm install && npm run build && cd ..
bpmn-architect studio
```

`npm run build` кладёт собранное приложение прямо в
`src/bpmn_architect/server/static/`, откуда его отдаёт сервер. Открывается
`http://localhost:8000`, документация API — `/docs`.

### Режим разработки с горячей перезагрузкой

Два терминала:

```bash
# 1. backend
bpmn-architect studio --reload --no-browser     # http://localhost:8000
```

```bash
# 2. frontend
cd frontend && npm run dev                      # http://localhost:5173
```

Dev-сервер Vite проксирует `/api` на backend, поэтому пути запросов в коде
одинаковы и в разработке, и в продакшене — переменных вида `API_BASE_URL` в
коде нет.

### Docker

```bash
cp .env.example .env         # необязательно: без ключей работает детерминированный режим
docker compose up            # http://localhost:8000
docker compose --profile dev up   # http://localhost:3000 + API на :8000
```

> Образ собирается многоступенчато: Node собирает SPA, Python-слой ставит пакет
> и забирает готовую сборку. В окружении, где писался этот код, демон Docker
> недоступен, поэтому `docker compose config` проверен, а сборка образа —
> нет.

## Структура репозитория

```
src/bpmn_architect/      движок (без зависимостей) + сервер (extra «studio»)
  domain/                модель BPMN и промежуточное представление
  parsing/               два фронтенда: естественный язык и DSL
  interpreters/          детерминированный / AI / гибридный режимы
  building/              сборка графа
  validation/            15 структурных правил
  layout/                послойная компоновка
  rendering/             BPMN 2.0 XML + DI, SVG, JSON
  interop/               чтение чужих BPMN-файлов
  analysis/              неоднозначности и обратное описание схемы
  sourcemap.py           связь «текст ↔ элемент»
  server/                FastAPI: API и раздача SPA
  cli.py                 build / validate / explain / studio
frontend/                React + TypeScript + Vite + bpmn-js
tests/                   тесты Python
examples/                примеры описаний
docs/                    документация
```

## Проверки

```bash
make check         # lint + типы + тесты Python
make test          # pytest
make lint          # ruff
make types         # mypy --strict
make examples      # пересобрать docs/images/*.svg

cd frontend
npm test           # vitest
npm run typecheck  # tsc --noEmit
npm run lint       # eslint
npm run build      # сборка (включает typecheck)
```

Ожидаемое состояние: Python — 327 тестов, фронтенд — 30 тестов, `ruff`,
`mypy --strict` и `eslint` — без замечаний.

### Сквозная проверка в браузере

`tests/e2e/studio.py` прогоняет полный сценарий в реальном Chromium:
текст → создание → правка свойств → undo → авто-компоновка → тема →
экспорт BPMN/PNG → сохранение проекта, с проверкой отсутствия ошибок в консоли.

```bash
pip install playwright
bpmn-architect studio --no-browser &          # или uvicorn
python tests/e2e/studio.py
```

Скрипт намеренно не в `pytest`: он требует запущенного сервера и браузера, и
его место — в отдельной стадии CI, а не в наборе, который разработчик гоняет
каждую минуту.

## Библиотека

Сервер — не единственный способ пользоваться движком:

```python
from pathlib import Path
from bpmn_architect import generate

result = generate(Path("описание.txt").read_text(encoding="utf-8"))
Path("process.bpmn").write_text(result.to_bpmn(), encoding="utf-8")
print(result.explain())
print(result.diagnostics.format())
```

Сервисный слой Studio тоже доступен напрямую и не тянет за собой web-фреймворк
в момент использования:

```python
from bpmn_architect.server.service import DiagramService, BuildRequestOptions

service = DiagramService()
payload = service.build_from_text(text, BuildRequestOptions(mode="hybrid"))
print(payload.validation["ok"], len(payload.elements))
```

## Соглашения

* Код и комментарии — на английском, документация и интерфейс — на русском.
  Так код остаётся переносимым, а продукт — понятным своей аудитории.
* Комментарий объясняет **почему**, а не пересказывает код.
* Движок не зависит ни от чего. Всё новое, что требует зависимости, попадает в
  optional extra.
* Никаких `type: ignore` и `any` без причины: `mypy --strict` и `eslint`
  проходят чисто.
* Любое изменение компоновки требует пересборки `docs/images/*.svg`
  (`make examples`) — CI сверяет их побайтово.
