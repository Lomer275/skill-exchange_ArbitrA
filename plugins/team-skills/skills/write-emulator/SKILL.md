---
name: write-emulator
description: 'Написать эмулятор внешнего сервиса (КадАрбитр, БФЛ+, Руспрофайл, Bitrix, claude CLI и т.п.) для unit-тестов по принятым в проекте паттернам DI-фейков. Use when the user says "напиши эмулятор", "сделай фейк/мок внешнего API", "замокай сервис для тестов", "нужен эмулятор как у руспрофайла/бфл+", or when writing tests for code that calls an external HTTP API, scrapes HTML, or spawns a CLI subprocess.'
---

# write-emulator — эмулятор внешнего сервиса для тестов

В проекте эмулятор — это **не отдельный HTTP-сервер и не nock/msw**. Это фейк,
который подсовывается коду через инжекцию зависимостей (DI): клиент внешнего
сервиса принимает `axios`/`api`/`deps` параметром, тест передаёт фейк с
канированными ответами. Сеть в unit-тестах не поднимается никогда.

Эталонные реализации живут в репо **ARP / multi-agent-app** — пути в таблице
относительно его корня. Если он под рукой — прочитай эталон перед написанием
своего; если работаешь в другом проекте, шаблонов ниже достаточно.

| Что эмулируем | Паттерн | Эталон |
|---|---|---|
| HTML-скрейпинг (Руспрофайл) | A: `fakeAxios` — map URL → страница | `backend/tests/rusprofile-client.test.js` |
| REST JSON API (БФЛ+) | B: `makeAxios` — хендлер на HTTP-метод + журнал вызовов | `backend/tests/bfl-plus-api-client.test.js` |
| Готовый api-клиент целиком (для оркестратора) | C: `makeApi`/`makeDeps` — дефолты + overrides + журнал | `backend/tests/bfl-plus-sync.test.js` |
| CLI-подпроцесс (claude, soffice…) | D: mock-скрипт, режим через ENV | `backend/tests/fixtures/mock-claude.sh` |
| Чистая логика без I/O (КадАрбитр-вотчер) | без эмулятора: литеральные объекты | `backend/tests/bfl-plus-kad-watcher.test.js` |

## Шаг 0. Проверь, что код вообще эмулируем

Клиент должен принимать зависимости параметром:

```js
// Good: test can inject a fake
function buildClient({ axios, cheerio, baseUrl }) { ... }

// Bad: hard require, cannot be faked without network
const axios = require('axios');
```

Если целевой модуль импортирует `axios`/`child_process` жёстко — **сначала
маленький рефактор**: вынеси зависимость в параметр с дефолтом
(`{ axios = require('axios') } = {}`), прод-поведение не меняется. Это
единственное изменение прод-кода, которое разрешает этот скилл. Не переписывай
клиент «заодно».

## Шаг 1. Выбери паттерн по таблице выше

Решающий вопрос: **что стоит между твоим кодом и внешним миром?**
- твой код сам ходит по URL → A или B (фейкается axios);
- твой код зовёт уже написанный клиент → C (фейкается клиент, не axios);
- твой код спавнит процесс → D (фейкается бинарь).

Не эмулируй два слоя сразу: тесту оркестратора не нужен fakeAxios — ему нужен
makeApi.

## Паттерн A — fakeAxios: map «URL → канированный ответ»

Для клиентов, парсящих HTML. Ключи — точные URL; незнакомый URL кидает ошибку
(тест сразу покажет, куда клиент реально сходил).

```js
function fakeAxios(pages) {
  return {
    async get(url) {
      if (!(url in pages)) throw new Error(`unexpected URL ${url}`);
      return { status: 200, data: pages[url] };
    },
  };
}

const client = buildClient({
  axios: fakeAxios({
    'https://rp.test/search?query=7707083893': '<a href="/id/1423041">result</a>',
    'https://rp.test/id/1423041': SBER_PAGE,
  }),
  cheerio,
  baseUrl: 'https://rp.test',
});
```

Канированную страницу (`SBER_PAGE`) держи **минимальной**: только те узлы,
которые парсер реально читает. Базовый URL в тестах — фиктивный (`https://rp.test`),
чтобы случайный реальный запрос был невозможен.

## Паттерн B — makeAxios: хендлеры по методам + журнал вызовов

Для REST-клиентов. Хендлер — значение или функция; каждый вызов пишется в
`calls[]`, по которому ассертятся URL, заголовки, тела.

```js
function makeAxios(handlers = {}) {
  const calls = [];
  function method(name) {
    return async (url, ...rest) => {
      calls.push({ method: name, url, rest });
      const handler = handlers[name];
      if (!handler) throw new Error(`unexpected ${name} ${url}`);
      return typeof handler === 'function' ? handler(url, ...rest) : handler;
    };
  }
  return { get: method('get'), post: method('post'), delete: method('delete'), calls };
}

// happy path + assert on what was actually sent
const ax = makeAxios({ get: { status: 200, data: { data: [{ id: 1 }] } } });
const out = await listCases({ ...CFG, axios: ax });
assert.equal(ax.calls[0].url, 'https://test.bfl.plus/data/v2/cases/all');
assert.equal(ax.calls[0].rest[0].headers['X-API-Key'], 'test-key');

// error mapping: status codes → typed errors
const ax401 = makeAxios({ get: { status: 401, data: '' } });
await assert.rejects(() => listCases({ ...CFG, axios: ax401 }), BflPlusUnauthorizedError);
```

Клиент при этом должен работать с `validateStatus: () => true` или ловить
ошибки axios — сверься с `backend/lib/bfl-plus/api-client.js`.

## Паттерн C — makeApi/makeDeps: фейк клиента целиком

Для тестов оркестраторов (sync, вотчеры, pipeline-хуки). Каждый метод: пишет в
журнал → зовёт override, если задан → иначе возвращает осмысленный дефолт.
Тест переопределяет только то, что важно для сценария.

```js
function makeApi(overrides = {}) {
  const calls = [];
  return {
    calls,
    async createDraft(...a) { calls.push(['createDraft', a]); return overrides.createDraft?.(...a) ?? { id: 100 }; },
    async getDebtor(...a)   { calls.push(['getDebtor', a]);   return overrides.getDebtor?.(...a)   ?? { id: 200, Inn: '123' }; },
    // ...one entry per public method of the real client
  };
}

// scenario: first call throws, second succeeds (retry logic)
let n = 0;
const api = makeApi({ getDebtor: async () => { n++; if (n === 1) throw unauthErr; return { id: 555 }; } });

// scenario: legacy stub without a method
delete api.listCases;
```

Тот же приём для остальных зависимостей — `makeDeps(opts)` с дефолтами на все
поля (`resolveClientFolders`, `fetchFileBytes`, …), см.
`bfl-plus-sync.test.js:104`. Фейк БД там же (`makeDb`, строка 12): собирает
`inserts`/`updates`/`deletes` в массивы, ассерты идут по ним.

**Важно:** сигнатуры и формы ответов фейка обязаны совпадать с реальным
клиентом. Добавил метод в реальный клиент — добавь его в makeApi в том же ПР.

## Паттерн D — mock-скрипт для CLI-подпроцессов

Когда код спавнит бинарь (`claude -p`, `soffice`…). Скрипт кладётся в
`backend/tests/fixtures/`, поведение выбирается через ENV-переменную режима;
путь к бинарю в прод-коде обязан быть настраиваемым через ENV
(`BFL_PACKAGE_CLAUDE_BIN`-паттерн).

```bash
#!/bin/bash
# Mock <tool> CLI for unit tests. Reads stdin to drain it, writes scripted output.
case "$MOCK_FOO_MODE" in
  "happy")   cat > /dev/null; echo '{"ok":true}' ;;
  "timeout") sleep 5 ;;
  "exit_2")  echo "boom" >&2; exit 2 ;;
  "bad_output") cat > /dev/null; echo "not json" ;;
  *)         cat > /dev/null; echo '{"ok":true}' ;;
esac
```

Обязательные режимы: happy, timeout, ненулевой exit, мусор вместо JSON,
отсутствующее поле в JSON. `cat > /dev/null` в начале каждой ветки обязателен —
иначе пишущий в stdin родитель получит EPIPE. Не забудь `chmod +x`.

## Канированные данные

- Бери **из реального ответа сервиса** (curl/логи), не сочиняй структуру по
  памяти — эмулятор, расходящийся с реальностью, вреднее его отсутствия.
- **Вычисти PII**: реальные ИНН/паспорта/ФИО клиентов заменяй на синтетические
  (`123`, `Иванов Иван Иванович`, ИНН тестовой сделки `012345678911`).
  Публичные реквизиты юрлиц (Сбер и т.п.) — можно как есть.
- Минимизируй: оставь только поля, которые код читает, плюс 1–2 соседних для
  реализма формы.

## Обязательный набор сценариев

Happy path — это треть эмулятора. Всегда покрывай:

1. happy path (+ ассерт по журналу вызовов: правильный URL/заголовки/тело);
2. «не найдено» / пустой ответ;
3. ошибки транспорта: 401, 5xx → маппинг на типизированные ошибки клиента;
4. мусор на выходе (битый HTML/JSON, отсутствующее поле);
5. специфичные для домена: ambiguous-результат (Руспрофайл), legacy stub без
   метода (БФЛ+), таймаут (CLI).

## Конвенции тестов проекта

- Раннер: `node:test` + `node:assert/strict`, без jest/vitest в backend.
- Файл: `backend/tests/<module>.test.js`; фейк-хелперы живут в самом
  тест-файле, в `fixtures/` — только данные и mock-скрипты.
- Запуск: `cd backend && node --test tests/<module>.test.js`.
- Первая строка `'use strict';`.

## Definition of done

- [ ] Прод-код не тронут (кроме, при необходимости, выноса зависимости в параметр).
- [ ] Незнакомый вызов фейка кидает ошибку, а не молча возвращает undefined.
- [ ] Покрыты все 5 групп сценариев из чек-листа.
- [ ] `node --test` прогнан, вывод зелёный **показан в отчёте** (не «должно работать»).
- [ ] Регресс существующих тестов затронутого модуля прогнан.
