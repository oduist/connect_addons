# connect_book Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Собрать модуль `connect_book`, который на лету краулит `doc/` папки всех установленных `connect*` модулей и показывает их внутри Odoo как User Guide / Admin Guide / Changes, плюс завести вокруг него тулинг многоязычной документации (LANG.md, скилл, правила в AGENTS.md).

**Architecture:** Порт `odu_book` из OduSphere с переименованием и снятием зависимости от `odu_base`. AbstractModel `connect.book` без таблицы читает Markdown с диска (с приоритетом `doc/i18n/<lang>/`), рендерит своим dependency-free рендерером `markdown.py`, отдаёт через три jsonrpc-роута трём OWL client action'ам. Меню живёт внутри Connect app под `Connect ▸ Documentation`.

**Tech Stack:** Odoo 19.0, Python 3.12+, OWL 2, `markupsafe`, Oduflow MCP для прогона тестов.

**Spec:** `docs/superpowers/specs/2026-08-13-connect-book-design.md`

## Global Constraints

- Ветка: `19.0-connect-book` (правило именования из `~/.claude/CLAUDE.md`; хук выводит версию Odoo из `^(\d+)\.0`).
- Формат коммитов: `[connect_book] <subject>` / `[connect] <subject>` / `[misc] <subject>`, lowercase imperative, **без** `feat:`/`fix:`.
- Источник для порта: `~/Workspace/odusphere/addons/odu_book` — читать оттуда, не выдумывать заново.
- Замены при порте, всегда все три: `odu_book` → `connect_book`, `odu.book` → `connect.book`, `odu-book`/`o_odu_` CSS-классы → `o_connect_book_*`.
- `MODULE_PREFIX = "connect"` (не `"connect_"` — префикс должен покрывать и сам модуль `connect`).
- `ADMIN_GROUP = "base.group_system"`.
- Лицензия/автор как в остальных модулях репо: `"license": "Other proprietary"`, `"author": "Oduist"`, `"maintainer": "Oduist"`, `"support": "support@oduist.com"`, `"category": "Phone"`.
- Odoo 19: роуты — `type="jsonrpc"` (не `type="json"`); переводы — `self.env._(...)`.
- Языковая политика: `source: en`, `targets:` пуст. Вся документация в этой итерации пишется **на английском**.

---

### Task 1: Скелет модуля + Markdown-рендерер

**Files:**
- Create: `connect_book/__init__.py`, `connect_book/__manifest__.py`, `connect_book/models/__init__.py`, `connect_book/models/markdown.py`
- Test: `connect_book/tests/__init__.py`, `connect_book/tests/test_markdown.py`

**Interfaces:**
- Consumes: ничего.
- Produces: `connect_book.models.markdown.md_to_html(text: str) -> str` — единственная публичная функция рендерера; используется Task 2.

- [ ] **Step 1: Создать ветку**

```bash
cd /Users/poligon/Workspace/odoo19/connect_addons
git checkout 19.0 && git pull --ff-only
git checkout -b 19.0-connect-book
```

- [ ] **Step 2: Скопировать рендерер из odusphere**

`markdown.py` переносится байт-в-байт — он не содержит ни одного упоминания `odu`.

```bash
mkdir -p connect_book/models connect_book/tests
cp ~/Workspace/odusphere/addons/odu_book/models/markdown.py connect_book/models/markdown.py
grep -ci odu connect_book/models/markdown.py   # должно быть 0
```

- [ ] **Step 3: Написать `connect_book/__init__.py` и `connect_book/models/__init__.py`**

`connect_book/__init__.py`:
```python
from . import models
from . import controllers
```

`connect_book/models/__init__.py`:
```python
from . import connect_book
```

Контроллеры и модель появятся в Task 2/3 — до тех пор модуль не устанавливается, и это нормально: тесты этой задачи запускаются без Odoo.

- [ ] **Step 4: Написать манифест `connect_book/__manifest__.py`**

```python
# -*- encoding: utf-8 -*-
{
    "name": "Connect Book",
    "version": "1.0.0",
    "author": "Oduist",
    "maintainer": "Oduist",
    "support": "support@oduist.com",
    "license": "Other proprietary",
    "category": "Phone",
    "summary": "Live documentation assembled from the doc/ folders of Connect modules",
    "description": """
Connect Book
============

Crawls every installed ``connect*`` module, collects the Markdown files from
their ``doc`` folders and assembles them into interactive books inside the
Odoo UI: the User Guide, the administrator-only Admin Guide, and a day-by-day
Changes archive.

The documentation lives next to the module code -- no separate wiki.
""",
    "depends": ["connect", "web"],
    "data": [
        "views/connect_book_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "/connect_book/static/src/book/book.scss",
            "/connect_book/static/src/book/book.js",
            "/connect_book/static/src/book/book.xml",
            "/connect_book/static/src/admin/adminbook.js",
            "/connect_book/static/src/changes/changes.js",
            "/connect_book/static/src/changes/changes.xml",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
```

- [ ] **Step 5: Написать падающий тест рендерера**

`connect_book/tests/__init__.py`:
```python
from . import test_markdown
```

`connect_book/tests/test_markdown.py`:
```python
# -*- coding: utf-8 -*-
from odoo.tests.common import BaseCase
from odoo.tests import tagged

from odoo.addons.connect_book.models.markdown import md_to_html


@tagged("post_install", "-at_install", "connect_book")
class TestMarkdown(BaseCase):
    def test_heading_and_paragraph(self):
        html = md_to_html("# Title\n\nHello world\n")
        self.assertIn("<h1>Title</h1>", html)
        self.assertIn("<p>Hello world</p>", html)

    def test_unordered_list(self):
        html = md_to_html("- one\n- two\n")
        self.assertIn("<ul>", html)
        self.assertEqual(html.count("<li>"), 2)

    def test_fenced_code_block_is_not_interpreted(self):
        html = md_to_html("```python\n# not a heading\n```\n")
        self.assertIn("<pre>", html)
        self.assertNotIn("<h1>", html)

    def test_table(self):
        html = md_to_html("| a | b |\n| --- | --- |\n| 1 | 2 |\n")
        self.assertIn("<table>", html)
        self.assertIn("<th>", html)

    def test_html_is_escaped(self):
        html = md_to_html("<script>alert(1)</script>\n")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_javascript_url_is_neutralised(self):
        html = md_to_html("[click](javascript:alert(1))\n")
        self.assertNotIn("javascript:", html)
        self.assertIn('href="#"', html)

    def test_https_url_is_kept(self):
        html = md_to_html("[docs](https://oduist.com/docs)\n")
        self.assertIn('href="https://oduist.com/docs"', html)
```

- [ ] **Step 6: Прогнать тест локально, убедиться что падает по отсутствию модуля**

Быстрый прогон без Odoo (проверяет сам рендерер, минуя тест-раннер):

```bash
cd /Users/poligon/Workspace/odoo19/connect_addons
python3 - <<'PY'
import sys; sys.path.insert(0, "connect_book/models")
from markdown import md_to_html
print(md_to_html("# T\n\n[x](javascript:alert(1))\n"))
PY
```
Expected: `<h1>T</h1>` и `href="#"` в выводе. Если `markupsafe` не установлен — `pip3 install markupsafe`.

- [ ] **Step 7: Коммит**

```bash
git add connect_book
git commit -m "[connect_book] add module skeleton and markdown renderer"
```

---

### Task 2: Модель `connect.book`

**Files:**
- Create: `connect_book/models/connect_book.py`
- Test: `connect_book/tests/test_book.py`
- Modify: `connect_book/tests/__init__.py`

**Interfaces:**
- Consumes: `md_to_html()` из Task 1.
- Produces: AbstractModel `connect.book` c `@api.model` методами `get_book()`, `get_admin_book()`, `get_changes()` и внутренними `_doc_lang()`, `_collect_pages(filename, lang)`, `_read_module_doc(module_name, filename, lang)`, `_render_doc_html(filepath, strip_marker)`, `_read_module_changes(module_name)`. Формы возврата — см. спеку §4.1. Используется Task 3.

- [ ] **Step 1: Портировать модель**

```bash
cp ~/Workspace/odusphere/addons/odu_book/models/odu_book.py connect_book/models/connect_book.py
python3 - <<'PY'
import re, pathlib
p = pathlib.Path("connect_book/models/connect_book.py")
s = p.read_text()
s = s.replace('MODULE_PREFIX = "odu_"', 'MODULE_PREFIX = "connect"')
s = s.replace('#: Prefix of the OduSphere modules that are included in the Book.',
              '#: Prefix of the modules included in the Book (covers ``connect`` itself\n#: and every ``connect_*`` add-on).')
s = s.replace("class OduBook", "class ConnectBook")
s = s.replace('_name = "odu.book"', '_name = "connect.book"')
s = s.replace('_description = "User Book"', '_description = "Connect Book"')
s = s.replace("odu_book:", "connect_book:")          # log prefixes
s = s.replace("``odu_*``", "``connect*``")
s = s.replace("odu_*", "connect*")
p.write_text(s)
PY
grep -n "odu" connect_book/models/connect_book.py   # ожидается пусто
```

Если `grep` что-то нашёл (например, «OduSphere» в докстрингах) — переписать эти фразы под Connect вручную; в файле не должно остаться ни одного `odu`.

- [ ] **Step 2: Написать падающие тесты модели**

Добавить в `connect_book/tests/__init__.py`:
```python
from . import test_book
```

`connect_book/tests/test_book.py`:
```python
# -*- coding: utf-8 -*-
import os
import tempfile
from unittest.mock import patch

from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "connect_book")
class TestConnectBook(TransactionCase):
    """The read path is exercised against a fake module directory on disk."""

    def setUp(self):
        super().setUp()
        self.book = self.env["connect.book"]
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.module_path = self.tmp.name
        os.makedirs(os.path.join(self.module_path, "doc", "changes"))

    def _write(self, relpath, content):
        path = os.path.join(self.module_path, "doc", relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)

    def _patch_path(self):
        """Point get_module_path() at the temporary module directory."""
        return patch(
            "odoo.addons.connect_book.models.connect_book.get_module_path",
            return_value=self.module_path,
        )

    def test_doc_lang_normalises_locale(self):
        self.assertEqual(
            self.book.with_context(lang="en_US")._doc_lang(), "en"
        )

    def test_doc_lang_rejects_path_traversal(self):
        self.assertEqual(
            self.book.with_context(lang="../../etc")._doc_lang(), "en"
        )

    def test_read_module_doc_prefers_translation(self):
        self._write("user_guide.md", "# Source\n")
        self._write("i18n/fr/user_guide.md", "<!-- i18n source=user_guide.md sha=abc lang=fr -->\n# Source FR\n")
        with self._patch_path():
            html = self.book._read_module_doc("connect", "user_guide.md", "fr")
        self.assertIn("Source FR", html)
        self.assertNotIn("i18n source=", html)

    def test_read_module_doc_falls_back_to_source(self):
        self._write("user_guide.md", "# Source\n")
        with self._patch_path():
            html = self.book._read_module_doc("connect", "user_guide.md", "de")
        self.assertIn("Source", html)

    def test_read_module_doc_missing_returns_none(self):
        with self._patch_path():
            self.assertIsNone(
                self.book._read_module_doc("connect", "admin_guide.md", "en")
            )

    def test_get_admin_book_requires_system_group(self):
        user = self.env["res.users"].create({
            "name": "Book Reader",
            "login": "book.reader@example.com",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        with self.assertRaises(AccessError):
            self.env["connect.book"].with_user(user).get_admin_book()

    def test_get_admin_book_allows_system_group(self):
        result = self.book.get_admin_book()   # test env user is a superuser
        self.assertIn("pages", result)

    def test_get_changes_groups_by_day_and_ignores_stray_files(self):
        self._write("changes/2026-08-13.md", "### Added\nsomething\n")
        self._write("changes/2026-08-12.md", "### Changed\nsomething else\n")
        self._write("changes/notes.md", "ignored\n")
        with self._patch_path():
            changes = self.book._read_module_changes("connect")
        dates = [date for date, _html in changes]
        self.assertEqual(sorted(dates), ["2026-08-12", "2026-08-13"])

    def test_get_book_returns_page_shape(self):
        self._write("user_guide.md", "# Guide\n")
        with self._patch_path():
            pages = self.book.get_book()["pages"]
        self.assertTrue(pages)
        self.assertEqual(
            sorted(pages[0]), ["html", "id", "module", "title"]
        )
```

- [ ] **Step 3: Поднять окружение Oduflow и прогнать тесты**

Один раз на весь план. Перед первым вызовом MCP-инструментов вызвать `get_agent_instructions` (режим доставки кода) и `get_odoo_development_guide(version="19")`.

```
mcp__oduflow__create_environment(name="connect-book", odoo_image="odoo:19.0", git_branch="19.0-connect-book")
mcp__oduflow__install_odoo_modules(environment="connect-book", modules=["connect_book"])
mcp__oduflow__run_odoo_tests(environment="connect-book", modules=["connect_book"])
```

Expected на этом шаге: тесты **падают** — `connect.book` ещё не зарегистрирована как модель (нет контроллеров и view из Task 3, модуль не встаёт). Это ожидаемый красный.

- [ ] **Step 4: Довести модель до установки без UI**

Временно убрать из манифеста ключи `data` и `assets` (Task 3 вернёт их), убрать `from . import controllers` из `connect_book/__init__.py`, переустановить и прогнать:

```
mcp__oduflow__install_odoo_modules(environment="connect-book", modules=["connect_book"])
mcp__oduflow__run_odoo_tests(environment="connect-book", modules=["connect_book"])
```
Expected: все тесты `test_markdown.py` и `test_book.py` — PASS.

- [ ] **Step 5: Вернуть манифест и `__init__.py` в вид из Task 1**

`data`, `assets` и `from . import controllers` возвращаются на место — Task 3 создаёт файлы, на которые они ссылаются.

- [ ] **Step 6: Коммит**

```bash
git add connect_book
git commit -m "[connect_book] add connect.book documentation collector"
```

---

### Task 3: Контроллер, client actions и меню в Connect app

**Files:**
- Create: `connect_book/controllers/__init__.py`, `connect_book/controllers/main.py`, `connect_book/views/connect_book_views.xml`, `connect_book/static/src/book/{book.js,book.xml,book.scss}`, `connect_book/static/src/admin/adminbook.js`, `connect_book/static/src/changes/{changes.js,changes.xml}`
- Modify: `connect/views/menu.xml:26-28`

**Interfaces:**
- Consumes: `connect.book.get_book()/get_admin_book()/get_changes()` из Task 2.
- Produces: роуты `/connect_book/book`, `/connect_book/admin`, `/connect_book/changes`; client action tags `connect_book.book`, `connect_book.admin`, `connect_book.changes`; XML id меню `connect_book.menu_connect_book_doc`, `connect_book.menu_connect_book_admin`, `connect_book.menu_connect_book_changes`.

- [ ] **Step 1: Портировать контроллер**

`connect_book/controllers/__init__.py`:
```python
from . import main
```

`connect_book/controllers/main.py`:
```python
# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request


class ConnectBookController(http.Controller):
    """Thin JSON wrapper over the ``connect.book`` model for the client actions."""

    @http.route("/connect_book/book", type="jsonrpc", auth="user")
    def book(self):
        return request.env["connect.book"].get_book()

    @http.route("/connect_book/admin", type="jsonrpc", auth="user")
    def admin_book(self):
        # get_admin_book enforces the system-admin group itself.
        return request.env["connect.book"].get_admin_book()

    @http.route("/connect_book/changes", type="jsonrpc", auth="user")
    def changes(self):
        return request.env["connect.book"].get_changes()
```

- [ ] **Step 2: Портировать фронтенд**

```bash
mkdir -p connect_book/static/src/{book,admin,changes}
cp ~/Workspace/odusphere/addons/odu_book/static/src/book/book.js connect_book/static/src/book/book.js
cp ~/Workspace/odusphere/addons/odu_book/static/src/book/book.xml connect_book/static/src/book/book.xml
cp ~/Workspace/odusphere/addons/odu_book/static/src/book/book.scss connect_book/static/src/book/book.scss
cp ~/Workspace/odusphere/addons/odu_book/static/src/admin/adminbook.js connect_book/static/src/admin/adminbook.js
cp ~/Workspace/odusphere/addons/odu_book/static/src/changes/changes.js connect_book/static/src/changes/changes.js
cp ~/Workspace/odusphere/addons/odu_book/static/src/changes/changes.xml connect_book/static/src/changes/changes.xml

# одна согласованная замена по всем шести файлам
python3 - <<'PY'
import pathlib
for p in pathlib.Path("connect_book/static/src").rglob("*"):
    if p.is_file():
        s = p.read_text()
        s = s.replace("odu_book", "connect_book").replace("o_odu_", "o_connect_book_")
        s = s.replace("OduSphere", "Connect")
        p.write_text(s)
PY
grep -rn "odu" connect_book/static/src || echo "clean"
```

Ожидаемый результат замены (проверить глазами): в `book.js` — `static template = "connect_book.BookApp"`, `static endpoint = "/connect_book/book"`, `registry...add("connect_book.book", BookApp)`; в `adminbook.js` — `import { BookApp } from "@connect_book/book/book"` и `static endpoint = "/connect_book/admin"`; в `changes.js` — `rpc("/connect_book/changes")` и tag `connect_book.changes`; в обоих `.xml` — `t-name="connect_book.BookApp"` / `connect_book.ChangesApp` и классы `o_connect_book_*`; в `book.scss` селекторы `.o_connect_book*` (класс `o_odu_changes` станет `o_connect_book_changes` — согласованно с `changes.xml`).

- [ ] **Step 3: Написать `connect_book/views/connect_book_views.xml`**

Меню — не корневое: три пункта под существующим `connect.connect_documentation_menu`.

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="action_connect_book" model="ir.actions.client">
        <field name="name">User Guide</field>
        <field name="tag">connect_book.book</field>
    </record>

    <record id="action_connect_book_admin" model="ir.actions.client">
        <field name="name">Admin Guide</field>
        <field name="tag">connect_book.admin</field>
    </record>

    <record id="action_connect_book_changes" model="ir.actions.client">
        <field name="name">Changes</field>
        <field name="tag">connect_book.changes</field>
    </record>

    <menuitem id="menu_connect_book_doc"
              name="User Guide"
              parent="connect.connect_documentation_menu"
              action="action_connect_book"
              sequence="5"/>

    <menuitem id="menu_connect_book_admin"
              name="Admin Guide"
              parent="connect.connect_documentation_menu"
              action="action_connect_book_admin"
              groups="base.group_system"
              sequence="7"/>

    <menuitem id="menu_connect_book_changes"
              name="Changes"
              parent="connect.connect_documentation_menu"
              action="action_connect_book_changes"
              sequence="10"/>
</odoo>
```

- [ ] **Step 4: Открыть меню Documentation обычным пользователям**

В `connect/views/menu.xml` у `connect_documentation_menu` сейчас стоит `groups="base.group_no_one"` — меню видно только в dev-режиме. Убрать эту строку:

```xml
  <menuitem id="connect_documentation_menu" name="Documentation"
      sequence="600" parent="connect_top_menu"/>
```

- [ ] **Step 5: Установить и проверить в окружении**

```
mcp__oduflow__upgrade_odoo_modules(environment="connect-book", modules=["connect"])
mcp__oduflow__install_odoo_modules(environment="connect-book", modules=["connect_book"])
mcp__oduflow__run_odoo_tests(environment="connect-book", modules=["connect_book"])
```
Expected: установка без ошибок, тесты PASS. Затем в браузере (URL окружения, `?debug=1`): `Connect ▸ Documentation` содержит три пункта, User Guide открывается, Changes открывается.

- [ ] **Step 6: Проверить admin-гейт руками**

```
mcp__oduflow__run_odoo_shell(environment="connect-book", code="""
user = env['res.users'].create({'name': 'Plain', 'login': 'plain@example.com',
    'groups_id': [(6, 0, [env.ref('base.group_user').id])]})
try:
    env['connect.book'].with_user(user).get_admin_book()
    print('FAIL: no AccessError')
except Exception as e:
    print('OK:', type(e).__name__)
env.cr.rollback()
""")
```
Expected: `OK: AccessError`. (Помнить: в oduflow shell записи без явного `cr.commit()` не сохраняются — здесь это и нужно, поэтому `rollback`.)

- [ ] **Step 7: Коммит**

```bash
git add connect_book connect/views/menu.xml
git commit -m "[connect_book] add book, adminbook and changes client actions"
```

---

### Task 4: Убрать legacy `connect.documentation`

**Files:**
- Delete: `connect/models/documentation.py`, `connect/views/documentation.xml`, `connect/doc/index.rst`
- Modify: `connect/models/__init__.py`, `connect/__manifest__.py` (строка `"views/documentation.xml",`)
- Create: `connect/doc/changes/2025-10-01.md`, `connect/doc/changes/2025-10-07.md`, `connect/doc/changes/2026-08-13.md`

**Interfaces:**
- Consumes: меню `connect.connect_documentation_menu` (уже переиспользовано Task 3).
- Produces: ничего для последующих задач; удаляет модель `connect.documentation` и её действие.

- [ ] **Step 1: Перенести changelog из `index.rst` в таймлайн**

`connect/doc/index.rst` — это changelog релизов, а не гайд. Содержимое (проверить `cat connect/doc/index.rst` перед переносом, там записи `1.0.8 (2025-10-07)` и `1.0.7 (2025-10-01)`) раскладывается по дням.

`connect/doc/changes/2025-10-07.md`:
```markdown
### Added

- Release 1.0.8: Twilio "get balance" button; call price feature.
- Release 1.0.8: call limit on external calls, set via the
  `connect.call_duration_limit` system parameter (seconds).
```

`connect/doc/changes/2025-10-01.md`:
```markdown
### Added

- Release 1.0.7: full support for Twilio Regions and Edges.
```

- [ ] **Step 2: Записать сам факт замены в таймлайн**

`connect/doc/changes/2026-08-13.md`:
```markdown
### Removed

- The `connect.documentation` transient model, its form view, window action and
  menu item -- the built-in RST page is superseded by Connect Book.
- `doc/index.rst`; its release notes moved into `doc/changes/`.

### Changed

- `Connect > Documentation` is no longer hidden behind `base.group_no_one`; it
  now hosts the Connect Book menus (User Guide, Admin Guide, Changes).
```

- [ ] **Step 3: Удалить код legacy-документации**

```bash
git rm connect/models/documentation.py connect/views/documentation.xml connect/doc/index.rst
```

Убрать `from . import documentation` из `connect/models/__init__.py` и строку `"views/documentation.xml",` из `data` в `connect/__manifest__.py`.

- [ ] **Step 4: Проверить, что на удалённое ничего не ссылается**

```bash
grep -rn "connect.documentation\|connect\.doc\b\|documentation\.xml\|action_connect_documentation\|view_connect_documentation_form" \
  --include="*.py" --include="*.xml" --include="*.js" . | grep -v docs/superpowers
```
Expected: пусто (кроме самого `connect_documentation_menu`, который остаётся жить). Любое найденное вхождение — починить до апгрейда.

- [ ] **Step 5: Апгрейд и прогон тестов**

```
mcp__oduflow__upgrade_odoo_modules(environment="connect-book", modules=["connect", "connect_book"])
mcp__oduflow__run_odoo_tests(environment="connect-book", modules=["connect", "connect_book"])
```
Expected: апгрейд без ошибок (Odoo сам снимает `ir.model` / `ir.ui.view` / `ir.actions` исчезнувшей модели), тесты PASS. Проверить в UI: `Connect ▸ Documentation` больше не содержит пункта «Connect» со старой RST-страницей.

- [ ] **Step 6: Коммит**

```bash
git add -A connect
git commit -m "[connect] replace rst documentation page with connect_book"
```

---

### Task 5: Языковая политика и скилл переводов

**Files:**
- Create: `LANG.md`, `LANG.local.md`, `.claude/skills/connect-doc-i18n/SKILL.md`
- Modify: `AGENTS.md`

**Interfaces:**
- Consumes: read-path `doc/i18n/<lang>/` из Task 2 (формат provenance-маркера должен совпадать с `I18N_MARKER_RE`).
- Produces: правила, на которые ссылаются doc-капсулы (Task 6) и все будущие docs-задачи.

- [ ] **Step 1: Портировать `LANG.md`**

```bash
cp ~/Workspace/odusphere/LANG.md LANG.md
cp ~/Workspace/odusphere/LANG.local.md LANG.local.md
python3 - <<'PY'
import pathlib
for name in ("LANG.md", "LANG.local.md"):
    p = pathlib.Path(name)
    s = p.read_text()
    s = s.replace("odu-doc-i18n", "connect-doc-i18n").replace("odu_book", "connect_book")
    s = s.replace("an OduSphere", "this repository").replace("OduSphere", "Connect")
    s = s.replace("a sphere's", "the repository's").replace("sphere-owned", "repo-owned")
    s = s.replace("sphere", "repository")
    p.write_text(s)
PY
```

Затем вычитать оба файла и вручную убрать то, чего в этом репо нет: упоминания `.docs/architecture.md` / `.docs/architecture.local.md` (системная карта не заводится — спека §9) и абзац про `merge=ours` upstream-шаблон. В `LANG.local.md` должно остаться ровно:

```markdown
## Documentation

- source: en
- targets:
- translate: user_guide.md, admin_guide.md
- source-only: tech_spec.md, changes/
```

- [ ] **Step 2: Портировать скилл**

```bash
mkdir -p .claude/skills/connect-doc-i18n
cp ~/Workspace/odusphere/.claude/skills/odu-doc-i18n/SKILL.md .claude/skills/connect-doc-i18n/SKILL.md
python3 - <<'PY'
import pathlib
p = pathlib.Path(".claude/skills/connect-doc-i18n/SKILL.md")
s = p.read_text()
s = s.replace("odu-doc-i18n", "connect-doc-i18n").replace("odu_book", "connect_book")
s = s.replace("odu_*", "connect*").replace("OduSphere", "Connect")
p.write_text(s)
PY
```

Правки после замены, обязательные:
- во фронтматтере `name: connect-doc-i18n`;
- в `source-only` убрать `.docs/architecture.md`;
- ссылку на `ODUSPHERE.md §6` заменить на `AGENTS.md` → раздел «Documentation is part of the change»;
- provenance-маркер оставить дословно — он должен матчиться `I18N_MARKER_RE` из Task 2:
  `<!-- i18n source=user_guide.md sha=<first 12 hex of sha256 of the source file> lang=<lang> -->`.

- [ ] **Step 3: Дописать правила документирования в `AGENTS.md`**

Добавить в конец `AGENTS.md`:

```markdown
## Documentation is part of the change

Documentation lives inside the module, in its `doc/` folder, and `connect_book`
serves it live inside Odoo. A code change is not finished until the docs for it
are in the same commit. Three layers, three audiences:

1. **User Guide — `doc/user_guide.md`** (every internal user). Plain language,
   for the person running the workflow: what the feature does, how to use it.
   Any user-visible change (new field, button, workflow) rewrites this file.
2. **Admin Guide — `doc/admin_guide.md`** (system administrators only). Every
   configurable setting the module exposes -- what it controls, allowed values,
   default, consequences -- and every task that needs admin rights.
   **Hard rule:** if it is a setting or needs admin rights, it goes here, never
   in the User Guide. A module with no settings ships no `admin_guide.md`.
3. **Tech Spec — `doc/tech_spec.md`** (agents). The reverse-buildable contract:
   an agent handed only the spec must be able to rebuild a behaviorally
   identical module without reading the code. Models, fields with all
   non-default attributes, constraints as rules, business rules and state
   flows, public methods with triggers and side effects, security matrix,
   behavior-bearing UI, endpoints, crons, seed data. Rules and formulas -- never
   copied source.

Plus the timeline: **`doc/changes/YYYY-MM-DD.md`**, one file per calendar day,
appended to (never duplicated). It records the *documentation* delta with
`### Added` / `### Changed` / `### Removed` sections naming the affected file
and section; structural deltas go in a ```diff fenced block. Files not matching
`YYYY-MM-DD.md` are ignored by the crawler.

Languages: authored in the `source` language from `LANG.local.md` and mirrored
into every `target` under `doc/i18n/<lang>/` in the same commit -- use the
`connect-doc-i18n` skill. Only the two human guides are translated. (UI strings
stay on the usual Odoo `.po`/`.pot` path -- a separate plane.)

**Definition of Done:** the touched module's `tech_spec.md` matches the code,
the affected guide is rewritten, today's `doc/changes/` entry exists, and
`connect-doc-i18n check` is clean. A snapshot edit with no timeline entry is
drift.
```

- [ ] **Step 4: Проверить консистентность маркера**

```bash
python3 - <<'PY'
import re, pathlib
marker_re = re.compile(r"\A<!--\s*i18n\b[^>]*-->[ \t]*\r?\n?")
sample = "<!-- i18n source=user_guide.md sha=0123456789ab lang=fr -->\n# Titre\n"
assert marker_re.match(sample), "marker does not match I18N_MARKER_RE"
assert "connect-doc-i18n" in pathlib.Path(".claude/skills/connect-doc-i18n/SKILL.md").read_text()
print("ok")
PY
grep -rn "odu" LANG.md LANG.local.md .claude/skills/connect-doc-i18n/SKILL.md || echo "clean"
```
Expected: `ok` и `clean`.

- [ ] **Step 5: Коммит**

```bash
git add LANG.md LANG.local.md .claude/skills/connect-doc-i18n/SKILL.md AGENTS.md
git commit -m "[misc] add documentation language policy and connect-doc-i18n skill"
```

---

### Task 6: Doc-капсула самого `connect_book`

**Files:**
- Create: `connect_book/doc/user_guide.md`, `connect_book/doc/admin_guide.md`, `connect_book/doc/tech_spec.md`, `connect_book/doc/changes/2026-08-13.md`

**Interfaces:**
- Consumes: правила из Task 5, read-path из Task 2 (капсула — первый живой контент, который Book покажет).
- Produces: эталон, по которому пишутся капсулы остальных модулей.

- [ ] **Step 1: Написать `connect_book/doc/user_guide.md`**

Английский, для конечного пользователя. Разделы: What Connect Book is; Opening the User Guide (`Connect ▸ Documentation ▸ User Guide`); how the left pane search works; what the Changes archive shows; why some modules have no page (module ships no `user_guide.md`); why the Admin Guide may be absent from the menu (not an administrator). Никаких настроек — их в этом модуле нет, о чём прямо сказать в Admin Guide.

За образцом структуры и тона: `~/Workspace/odusphere/addons/odu_book/doc/user_guide.md` (56 строк).

- [ ] **Step 2: Написать `connect_book/doc/admin_guide.md`**

Английский, для системного администратора. Разделы: who can read the Admin Guide (`base.group_system`, enforced on the menu *and* in `get_admin_book`); where documentation files must live (`doc/user_guide.md`, `doc/admin_guide.md`, `doc/changes/YYYY-MM-DD.md`, `doc/i18n/<lang>/`); which modules are crawled (installed modules named `connect*`); render limits (files over 1 MiB skipped, a broken file drops out of the book without breaking it); caching by file mtime — docs refresh on redeploy without restarting Odoo; the module itself exposes **no** configuration settings.

Образец: `~/Workspace/odusphere/addons/odu_book/doc/admin_guide.md` (64 строки).

- [ ] **Step 3: Написать `connect_book/doc/tech_spec.md`**

По канонической структуре из `AGENTS.md` (Task 5): Identity & Manifest; Models & Fields (AbstractModel `connect.book`, без полей — сказать явно); Constraints & Invariants (`LANG_CODE_RE`-валидация языка; только `YYYY-MM-DD.md` в changes; `MAX_DOC_BYTES`); Business Rules & State (порядок кандидатов i18n → source; strip маркера; кеш по `(filepath, strip_marker) → (mtime, html)`; изоляция ошибок рендера); Methods & Actions (`get_book`, `get_admin_book`, `get_changes` + формы возврата); Security (`base.group_system` в двух слоях; `sudo()` только на `ir.module.module`; whitelist схем URL в рендерере); Views & UI (три client action, tags); API Endpoints (три jsonrpc-роута, auth=user); Automation (нет); Seed/Demo Data (нет).

Образец: `~/Workspace/odusphere/addons/odu_book/doc/tech_spec.md` (150 строк) — но переписать под фактический код `connect_book`, а не копировать.

- [ ] **Step 4: Написать `connect_book/doc/changes/2026-08-13.md`**

```markdown
### Added

- `user_guide.md`: initial guide -- opening the books, searching, the Changes
  archive, why a module may have no page.
- `admin_guide.md`: initial guide -- who may read the Admin Guide, where doc
  files live, which modules are crawled, render limits and caching.
- `tech_spec.md`: initial module SPEC for `connect.book`, the three jsonrpc
  endpoints and the three client actions.
```

- [ ] **Step 5: Проверить капсулу в живом Book**

```
mcp__oduflow__upgrade_odoo_modules(environment="connect-book", modules=["connect_book"])
```
Затем в UI: `Connect ▸ Documentation ▸ User Guide` показывает страницу «Connect Book»; `Admin Guide` — свою; `Changes` — дни `2026-08-13`, `2025-10-07`, `2025-10-01` (последние два от модуля `connect` из Task 4).

- [ ] **Step 6: Финальный прогон тестов**

```
mcp__oduflow__run_odoo_tests(environment="connect-book", modules=["connect", "connect_book"])
```
Expected: PASS. Записать фактический вывод — заявлять готовность только по нему.

- [ ] **Step 7: Коммит и пуш**

```bash
git add connect_book/doc
git commit -m "[connect_book] add user, admin and tech documentation capsule"
git push -u origin 19.0-connect-book
```

---

## Definition of Done всего плана

- `connect_book` ставится на чистой 19.0-базе; три пункта видны в `Connect ▸ Documentation`.
- Admin Guide закрыт для не-админа и в меню, и по RPC (проверено шагом Task 3.6).
- `connect.documentation`, её view и `index.rst` удалены; апгрейд `connect` проходит.
- `LANG.md`, `LANG.local.md`, `.claude/skills/connect-doc-i18n/SKILL.md`, раздел в `AGENTS.md` на месте; ни одного `odu` в портированных файлах.
- У `connect_book` есть полная doc-капсула из четырёх файлов.
- `run_odoo_tests` по `connect` и `connect_book` — зелёный.

## Вне объёма (следующие итерации)

- doc-капсулы для остальных 11 модулей репо.
- Astro-сборка публичного сайта из тех же `doc/` папок.
- Реальные переводы (`targets` пуст; включаются скиллом `connect-doc-i18n add <lang>`).
