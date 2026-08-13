# connect_book — Layered Live Documentation for Connect (Design)

Дата: 2026-08-13
Статус: согласовано (4 развилки закрыты пользователем), готово к плану реализации

## 1. Задача

Портировать в `connect_addons` механику «многоязычной документации, живущей внутри
модулей» из OduSphere (`~/Workspace/odusphere`): модуль `odu_book` + слой правил
(ODUSPHERE.md §6 «Layered Live Documentation»), политика языков (`LANG.md` /
`LANG.local.md`) и скилл сопровождения переводов (`odu-doc-i18n`).

Результат первой итерации — модуль `connect_book`, который на лету собирает
документацию из `doc/` папок всех установленных `connect*` модулей и показывает её
внутри Odoo как три client action: **User Guide**, **Admin Guide**, **Changes**.

Вторая (будущая) итерация, вне этого документа: Astro-сборка тех же `doc/` папок в
публичный сайт.

## 2. Принятые решения

| # | Развилка | Решение |
|---|----------|---------|
| 1 | Legacy `connect.documentation` (RST) | **Заменить полностью.** Удалить модель, view, action и menuitem; `connect/doc/index.rst` (по факту — 12-строчный changelog релизов, а не гайд) перенести в `connect/doc/changes/`. Меню `Connect ▸ Documentation` переиспользуется под Book. |
| 2 | Какие модули краулит | **Все `connect%`**: `ir.module.module` c `state = installed AND name =like 'connect%'` (покрывает и сам `connect`, и все `connect_*`). |
| 3 | Доступ к Admin Guide | **`base.group_system`**, гейт в двух слоях: `groups` на menuitem + `AccessError` в `get_admin_book()`. |
| 4 | Объём итерации 1 | Модуль + тулинг + doc-капсула самого `connect_book`. Контент по остальным модулям — отдельными задачами. |

## 3. Что переносится из `odu_book`

Исходник: `~/Workspace/odusphere/addons/odu_book` (21 файл, ~1400 строк).
Перенос практически 1:1 с переименованием `odu_book` → `connect_book`,
`odu.book` → `connect.book`, `MODULE_PREFIX = "odu_"` → `"connect"`.

| Файл источника | Назначение в `connect_book` | Изменения |
|---|---|---|
| `models/odu_book.py` (258) | `models/connect_book.py` | `_name = "connect.book"`, `MODULE_PREFIX = "connect"`, docstrings под Connect |
| `models/markdown.py` (275) | `models/markdown.py` | без изменений (dependency-free MD→HTML, экранирование, whitelist схем URL) |
| `controllers/main.py` (20) | `controllers/main.py` | роуты `/connect_book/book`, `/connect_book/admin`, `/connect_book/changes` |
| `static/src/book/{book.js,book.xml,book.scss}` | то же | шаблон `connect_book.BookApp`, action tag `connect_book.book` |
| `static/src/admin/adminbook.js` | то же | импорт `@connect_book/book/book`, tag `connect_book.admin` |
| `static/src/changes/{changes.js,changes.xml}` | то же | tag `connect_book.changes` |
| `views/odu_book_views.xml` | `views/connect_book_views.xml` | меню **не корневое**, а под `connect.connect_documentation_menu` |
| `doc/*` (user_guide, admin_guide, tech_spec, changes/) | `connect_book/doc/*` | переписывается под Connect (это и есть doc-капсула из решения №4) |

Зависимость `odu_base` **снимается** — код из него не используется, она была нужна
только ради governance-политики «только `odu_`-модули». Вместо неё: `depends: ["connect", "web"]`.

## 4. Архитектура модуля

### 4.1 Модель `connect.book` (AbstractModel, без таблицы)

Читает файлы с диска, ничего не хранит.

Константы:
```
DOC_DIRNAME = "doc"
GUIDE_FILENAME = "user_guide.md"
ADMIN_GUIDE_FILENAME = "admin_guide.md"
CHANGES_DIRNAME = "changes"
CHANGE_FILE_RE = ^(\d{4}-\d{2}-\d{2})\.md$
I18N_DIRNAME = "i18n"
I18N_MARKER_RE = \A<!--\s*i18n\b[^>]*-->[ \t]*\r?\n?
MODULE_PREFIX = "connect"
ADMIN_GROUP = "base.group_system"
LANG_CODE_RE = ^[a-z]{2,3}(@[a-z0-9]+)?$
MAX_DOC_BYTES = 1 MiB
```

Публичные методы (`@api.model`):

- `get_book()` → `{"pages": [{"id", "module", "title", "html"}]}` — по одной странице на
  модуль, из `doc/user_guide.md`, в языке читателя.
- `get_admin_book()` → та же форма из `doc/admin_guide.md`; при отсутствии
  `base.group_system` — `AccessError`.
- `get_changes()` → `{"days": [{"date": "YYYY-MM-DD", "entries": [{"module", "title", "html"}]}]}`,
  дни по убыванию.

Внутренние: `_doc_lang()` (из `context['lang']`/`user.lang`, `en_US → en`, валидация
`LANG_CODE_RE` против path traversal), `_collect_pages()`, `_read_module_doc()`
(сначала `doc/i18n/<lang>/<file>`, потом `doc/<file>`), `_render_doc_html()`
(кеш по `(filepath, strip_marker) → (mtime, html)`, скип файлов > 1 MiB, ошибка
рендера изолируется одним файлом), `_read_module_changes()`.

### 4.2 Безопасность

- Read-path целиком read-only, никаких записей.
- `search` по `ir.module.module` через `sudo()` — модель системная, но наружу
  отдаётся только имя/shortdesc установленных модулей.
- Admin Guide: `groups="base.group_system"` на menuitem **и** `AccessError` в модели
  (контроллер сам не проверяет — проверку делает модель).
- `markdown.py`: всё экранируется через `markupsafe.escape`, в ссылках/картинках
  разрешены только `http`, `https`, `mailto` (иначе `#`), лимит вложенности списков 12.
- `_doc_lang()` отбрасывает любой `lang`, не подходящий под `LANG_CODE_RE`, — крафтовый
  `lang` не может выйти из папки `doc/`.

### 4.3 UI

Три client action на OWL, ассеты в `web.assets_backend`:

- `connect_book.book` — двухпанельный просмотрщик: слева поиск + список модулей,
  справа HTML гайда (`markup()`).
- `connect_book.admin` — наследует `BookApp`, меняет только `static endpoint`.
- `connect_book.changes` — таймлайн дней, сгруппированный по месяцам (архив «как блог»).

### 4.4 Размещение меню

`odu_book` ставил корневое меню `Book`. В Connect меню живёт **внутри Connect app**,
под существующим `connect.connect_documentation_menu`:

```
Connect ▸ Documentation ▸ User Guide     (action connect_book.book)
Connect ▸ Documentation ▸ Admin Guide    (groups=base.group_system)
Connect ▸ Documentation ▸ Changes
```

С `connect.connect_documentation_menu` снимается `groups="base.group_no_one"`
(в `connect/views/menu.xml`) — иначе меню видно только в dev-режиме.

## 5. Изменения в модуле `connect` (решение №1)

Удаляется:

- `connect/models/documentation.py` (модель `connect.documentation` + самописный
  RST→HTML, ~170 строк) и её строка в `connect/models/__init__.py`;
- `connect/views/documentation.xml` (form view, act_window, menuitem) и её строка в
  `data` манифеста;
- `connect/doc/index.rst` — после переноса содержимого.

Уточнение по факту содержимого: `index.rst` — это **changelog релизов** (записи
`1.0.8 (2025-10-07)`, `1.0.7 (2025-10-01)`), а не пользовательский гайд. Поэтому
конвертация идёт не в `user_guide.md`, а в таймлайн:

- `connect/doc/changes/2025-10-07.md` и `connect/doc/changes/2025-10-01.md` —
  записи из changelog в Markdown;
- `connect/doc/changes/2026-08-13.md` — запись о самой замене системы документации.

Написание `connect/doc/user_guide.md` и `admin_guide.md` — **вне этой итерации**
(решение №4: контент по остальным модулям отдельными задачами). До тех пор
User Guide просто не показывает страницу для модуля `connect` — это корректное
поведение, не дефект.

Снимается `groups="base.group_no_one"` с `connect_documentation_menu`.

Существующая `connect/docs/s3-recordings-setup.md` — отдельная папка `docs/` (не `doc/`),
Book её не видит; в этой итерации не трогаем.

## 6. Тулинг и правила (решение №4)

1. **`LANG.md`** (корень репо) — политика языков, портируется из odusphere с заменой
   `odu_book` → `connect_book`, `odu-doc-i18n` → `connect-doc-i18n`.
2. **`LANG.local.md`** — выбор для этого репо: `source: en`, `targets:` (пусто),
   `translate: user_guide.md, admin_guide.md`,
   `source-only: tech_spec.md, changes/`.
   Система мультиязычна-ready даже при одном языке.
3. **Скилл `.claude/skills/connect-doc-i18n/SKILL.md`** — команды `add <lang>` /
   `sync [lang]` / `check [lang]` / `remove <lang>`; provenance-маркер первой строкой
   мирора:
   `<!-- i18n source=user_guide.md sha=<12 hex sha256 источника> lang=<lang> -->`.
   Book срезает маркер перед рендером; `sync`/`check` сравнивают SHA.
4. **`AGENTS.md`** репозитория — добавить раздел «Documentation is part of the change»:
   три слоя (`user_guide.md` / `admin_guide.md`; `tech_spec.md`; `doc/changes/YYYY-MM-DD.md`),
   правило «настройки и админ-задачи — только в Admin Guide», Definition of Done.
   Формулировки — сокращённый пересказ ODUSPHERE.md §6 под Connect
   (без `.docs/architecture.md`, который в odusphere upstream-owned).

## 7. Тесты

Репо небогато тестами (3 файла), но read-path легко покрывается без окружения:

- `connect_book/tests/test_markdown.py` — рендер заголовков/списков/таблиц/кода;
  экранирование HTML; `javascript:`-ссылка → `#`.
- `connect_book/tests/test_book.py` — `get_book()` возвращает страницу для модуля с
  `doc/user_guide.md`; `get_admin_book()` бросает `AccessError` не-админу;
  `_doc_lang()` нормализует `en_US → en` и отбивает `../`; предпочтение
  `doc/i18n/<lang>/` над источником; `get_changes()` группирует по датам и игнорирует
  файлы не по маске.

## 8. Definition of Done итерации 1

- `connect_book` устанавливается на чистой 19.0-базе, три меню видны в Connect app.
- Admin Guide недоступен не-админу (и в меню, и по RPC).
- Модель `connect.documentation` и её XML удалены, `index.rst` сконвертирован,
  апгрейд `connect` проходит без ошибок.
- `LANG.md`, `LANG.local.md`, скилл `connect-doc-i18n`, раздел в `AGENTS.md` на месте.
- У самого `connect_book` есть полная doc-капсула: `user_guide.md`, `admin_guide.md`,
  `tech_spec.md`, `changes/2026-08-13.md`.
- Тесты из §7 проходят.

## 9. Вне объёма

- Написание doc-капсул для остальных 11 модулей репо (отдельные задачи).
- Astro-сборка сайта из `doc/` папок (итерация 2).
- Перевод на конкретные языки (`targets` пуст; включается скиллом по запросу).
- Портирование `.docs/architecture.md` (в odusphere он upstream-owned; в Connect
  системная карта пока не заводится).
