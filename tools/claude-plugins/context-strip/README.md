# context-strip

Полоска заполнения контекста Claude Code над полем ввода, с разбивкой по категориям — те же строки, что считает `/context` (System prompt, System tools, MCP tools, Memory files, Skills, Messages, буфер автокомпакта, свободное место).

```
████████▓▓▓▓██████████████▒▒▒▒▒░░░░░░░░░░ 42% 84k/200k
■ Messages 61k  ■ System tools 16k  ■ System prompt 4.1k  ■ Memory files 2.3k
```

- обновляется на старте сессии, после каждого промпта и хода, и (не чаще раза в 3 с) после вызовов инструментов;
- процент желтеет от 65 %, краснеет от 85 %;
- `/ctx` — скрыть/показать полоску.

Счёт идёт локальной оценкой (`breakdown: "summary"`), без запросов к API.

## Установка

```
/plugin install context-strip --marketplace YoSlavian/Sorter_Photo_Local
```

Ответьте `y` на добавление маркетплейса и выберите scope (user — во всех проектах).
