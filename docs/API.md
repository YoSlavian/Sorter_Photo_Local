# HTTP API

Базовый путь — `/api`. Интерактивная документация с формами для проб —
`http://localhost:8000/docs`, машинописная схема — `/openapi.json`.

Единый принцип: **на входе и на выходе везде стандартный BPMN 2.0 XML**.
Браузерный редактор, Python-движок и любой внешний инструмент работают с одним
представлением, и промежуточного «своего» формата не существует.

## Коды ответов

| Код | Когда |
|---|---|
| `200` | успех |
| `400` | некорректный запрос: пустое описание, повреждённый BPMN, битый файл проекта |
| `422` | схема запроса не сошлась, либо запрошен AI-режим без настроенного провайдера |
| `404` | неизвестный путь под `/api` |

Тело ошибки — `{"detail": "человекочитаемое сообщение"}`.

---

## Состояние сервера

### `GET /api/health`

```json
{ "status": "ok", "version": "1.0.0" }
```

### `GET /api/info`

Возможности сервера: доступные режимы интерпретации, реально настроенные
провайдеры LLM, поддерживаемые языки, полный список типов элементов.

```json
{
  "version": "1.0.0",
  "modes": ["deterministic", "ai", "hybrid"],
  "providers": { "anthropic": false, "openai": false, "local": false },
  "languages": ["ru", "en"],
  "elementTypes": [{ "type": "exclusiveGateway", "category": "gateway" }]
}
```

`providers` показывает фактическую готовность: установлен ли SDK и есть ли
доступ к ключу. Интерфейс по этому полю решает, предлагать ли AI-режимы.

---

## Текст → диаграмма

### `POST /api/build`

Основной вызов: описание на входе, полное состояние диаграммы на выходе.

```json
{
  "text": "Процесс начинается с получения заявки. ...",
  "options": {
    "mode": "deterministic",
    "syntax": "auto",
    "language": null,
    "useLanes": true,
    "infinitiveNames": true,
    "executable": false,
    "includeDocumentation": true,
    "processId": "",
    "processName": "",
    "llmProvider": null,
    "llmModel": ""
  }
}
```

Ответ:

```json
{
  "bpmn": "<?xml version=\"1.0\"?>…",
  "elements": [
    {
      "id": "Activity_1",
      "type": "userTask",
      "name": "Проверить заявку",
      "category": "activity",
      "lane": "Lane_1",
      "laneName": "Менеджер",
      "eventDefinition": null,
      "documentation": "Менеджер проверяет заявку.",
      "incoming": ["Flow_1"],
      "outgoing": ["Flow_2"],
      "attributes": { "source": "Менеджер проверяет заявку.", "line": "4" }
    }
  ],
  "lanes": [{ "id": "Lane_1", "name": "Менеджер", "order": 0 }],
  "flows": [
    { "id": "Flow_3", "source": "Gateway_1", "target": "Activity_2",
      "name": "Да", "condition": "заявка корректна", "isDefault": false }
  ],
  "validation": {
    "ok": true,
    "counts": { "error": 0, "warning": 0, "info": 1 },
    "diagnostics": [
      { "code": "I101", "severity": "info", "message": "…",
        "elementId": "Activity_1", "line": 0 }
    ]
  },
  "sourceMap": {
    "Activity_1": {
      "elementId": "Activity_1",
      "sentence": "Менеджер проверяет заявку.",
      "line": 4, "start": 76, "end": 120, "exact": true
    }
  },
  "clarifications": [],
  "explanation": "process: …\n<xor> Заявка корректна?…",
  "narrative": "Процесс начинается с события …",
  "meta": {
    "processId": "Process_1", "processName": "Обработка заявки",
    "elementCount": 7, "flowCount": 7, "laneCount": 2, "language": "ru",
    "mode": "deterministic", "provider": "", "deterministic": true, "notes": []
  }
}
```

`sourceMap` — то, на чём держится двусторонняя связь текста и схемы:
`start`/`end` — смещения в символах внутри присланного текста.

`meta.deterministic` говорит, воспроизводим ли результат: для
`deterministic` — всегда, для `hybrid` — если модель не понадобилась.

### `POST /api/parse`

Разбор без построения диаграммы: быстрая проверка того, как понят текст.

```json
{ "explanation": "process: …", "language": "ru",
  "mode": "deterministic", "deterministic": true, "notes": [] }
```

---

## Операции над диаграммой

Все принимают `{ "bpmn": "<xml>" }` и, кроме `/validate` и `/describe`,
возвращают то же тело, что и `/build`.

| Метод | Что делает |
|---|---|
| `POST /api/validate` | 15 структурных правил; возвращает только блок `validation` |
| `POST /api/layout` | заново раскладывает диаграмму движком компоновки |
| `POST /api/clarify` | применяет ответы на уточняющие вопросы |
| `POST /api/describe` | возвращает `{ "text": "…" }` — описание схемы словами |
| `POST /api/bpmn/import` | открывает файл BPMN 2.0, в том числе из чужого редактора |

`POST /api/clarify` принимает `{ "bpmn": "<xml>", "answers": { "ask_1_naming": "Обработать обращение" } }`.
Вопросы не хранятся на сервере: они заново вычисляются из диаграммы, а
идентификаторы стабильны для одной и той же модели — эндпоинт остаётся
без состояния.

`POST /api/bpmn/import` дополнительно принимает `sourceText`, чтобы восстановить
связь с описанием, и сообщает в `meta.layoutWasGenerated`, была ли геометрия в
файле или её построили заново.

---

## Выгрузка

| Метод | Content-Type | Примечание |
|---|---|---|
| `POST /api/bpmn/export` | `application/xml` | перед выдачей файл проверяется на читаемость |
| `POST /api/export/svg` | `image/svg+xml` | серверная отрисовка той же геометрии |
| `POST /api/export/json` | `application/json` | модель и геометрия как данные |

PNG и PDF формируются в браузере из SVG самого редактора — так экспорт
совпадает с тем, что на экране, пиксель в пиксель, и на сервере не нужен
безголовый рендерер.

---

## Проекты

### `POST /api/project/export`

```json
{ "bpmn": "<xml>", "sourceText": "…", "name": "Обработка заявки",
  "settings": { "options": { "mode": "deterministic" } } }
```

Ответ: `{ "project": "…json…", "filename": "obrabotka-zayavki.bpmn-project" }`.

### `POST /api/project/import`

Принимает `{ "project": "…содержимое файла…" }`, возвращает готовую диаграмму,
исходный текст, настройки и метаданные. Файл более новой версии формата
отклоняется с понятным сообщением, а не читается наполовину.

Формат проекта:

```json
{
  "version": 1,
  "sourceText": "Процесс начинается …",
  "bpmn": "<?xml …?>",
  "settings": { "options": {} },
  "metadata": { "name": "…", "createdAt": "…", "updatedAt": "…", "generator": "bpmn-architect 1.0.0" }
}
```

Диаграмма внутри — обычный BPMN 2.0, поэтому проект всегда можно распаковать
в стандартный файл.

---

## Использование из кода

```bash
curl -s localhost:8000/api/build \
  -H 'Content-Type: application/json' \
  -d '{"text":"Процесс начинается с заявки. Менеджер проверяет заявку. Процесс завершается."}' \
  | python -c 'import json,sys; print(json.load(sys.stdin)["bpmn"])' > process.bpmn
```

```python
import httpx

response = httpx.post("http://localhost:8000/api/build", json={"text": description})
response.raise_for_status()
diagram = response.json()
Path("process.bpmn").write_text(diagram["bpmn"], encoding="utf-8")
```

Если сервер не нужен, тот же результат даёт библиотека напрямую —
см. [DEVELOPMENT.md](DEVELOPMENT.md#библиотека).
