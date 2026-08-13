# connect_book — Module SPEC

Reverse-buildable contract for the module. Rules and shapes, not source.

## Identity & Manifest

- Technical name: `connect_book`
- Display name: `Connect Book`
- Summary: `Live documentation assembled from the doc/ folders of Connect modules`
- Version: `1.0.0` (Odoo 19)
- Category: `Phone` · Author / Maintainer: `Oduist` · Support: `support@oduist.com`
- License: `Other proprietary`
- Flags: `installable = True`, `application = False`, `auto_install = False`
- `depends`: `["connect", "web"]` -- `connect` supplies the parent menu the Book
  hangs under; `web` supplies the client-action/OWL layer.
- External Python libraries: **none**. The only non-Odoo import is `markupsafe`,
  which ships with Odoo.
- `data`: `views/connect_book_views.xml` (the only data file; no security CSV).
- Assets, all in the `web.assets_backend` bundle, in this order:
  `static/src/book/book.scss`, `static/src/book/book.js`,
  `static/src/book/book.xml`, `static/src/admin/adminbook.js`,
  `static/src/changes/changes.js`, `static/src/changes/changes.xml`.
- The module ships its own `doc/` capsule (`user_guide.md`, `admin_guide.md`,
  `tech_spec.md`, `changes/*.md`), which the Book then serves like any other
  module's.

## Models & Fields

- `connect.book` -- `models.AbstractModel`, `_description = "Connect Book"`.
  - **No table, no fields, no persisted state.** It is a read-only service that
    reads other modules' documentation from disk on demand and renders it.
- Module-level constants (in the model's Python module) and their meaning:

| Constant | Value | Role |
|---|---|---|
| `DOC_DIRNAME` | `"doc"` | Folder inside a module holding its documentation |
| `GUIDE_FILENAME` | `"user_guide.md"` | End-user guide file name (the Userbook) |
| `ADMIN_GUIDE_FILENAME` | `"admin_guide.md"` | Administrator guide file name (the Adminbook) |
| `CHANGES_DIRNAME` | `"changes"` | Folder inside `doc/` holding the per-day timeline |
| `CHANGE_FILE_RE` | `^(\d{4}-\d{2}-\d{2})\.md$` | Accepts a change file and captures its date |
| `I18N_DIRNAME` | `"i18n"` | Folder inside `doc/` holding translated mirrors |
| `I18N_MARKER_RE` | leading `<!-- i18n … -->` line, with its trailing newline | Provenance marker stripped before render |
| `MODULE_PREFIX` | `"connect"` | Only modules whose name starts with this are crawled |
| `ADMIN_GROUP` | `"base.group_system"` | Group required to read the Adminbook |
| `LANG_CODE_RE` | `^[a-z]{2,3}(@[a-z0-9]+)?$` | Accepts a documentation-language tag |
| `MAX_DOC_BYTES` | `1024 * 1024` (1 MiB) | Files above this size are skipped |
| `_RENDER_CACHE` | module-level `dict` | `(filepath, strip_marker) -> (mtime, html)` |

- The markdown renderer lives in a separate, Odoo-free Python module next to the
  model and exposes one public function, `md_to_html(text) -> str`. Its own
  constants: `_SAFE_URL_SCHEMES = {"http", "https", "mailto"}` and
  `_MAX_LIST_DEPTH = 12`.

## Constraints & Invariants

- No SQL constraints, no `@api.constrains`, no `ir.model.access.csv` -- an
  AbstractModel with no table needs none.
- **Language-tag validation.** Any language code that is joined into a
  filesystem path must first match `LANG_CODE_RE`. A value that fails (it may
  then contain `/`, `.` or `..`) is replaced by `"en"`. This is the
  path-traversal guard for `doc/i18n/<lang>/`.
- **Change-file naming.** Only files in `doc/changes/` named exactly
  `YYYY-MM-DD.md` are read; every other name is ignored without a warning.
- **Size bound.** A file whose `st_size` exceeds `MAX_DOC_BYTES` is never read
  or rendered; it is skipped with a log warning.
- **Nesting bound.** List rendering recurses at most `_MAX_LIST_DEPTH` levels;
  deeper items are emitted flat rather than recursing further.
- **Total error isolation.** No documentation file, however malformed, may raise
  out of the public methods. Stat failure, read failure, decode failure, size
  overflow and render failure all resolve to "this one file is absent".

## Business Rules & State

- The module serves **three views**, each aggregating **one page (or entry) per
  crawled module** that ships the matching file:
  - **Userbook** -- `doc/user_guide.md`, for every internal user.
  - **Adminbook** -- `doc/admin_guide.md`, administrators only.
  - **Changes** -- `doc/changes/*.md`, the per-day documentation timeline.
- **Module selection (all three views).** Search `ir.module.module` with
  `sudo()` for `state = "installed"` AND `name =like "connect%"`, ordered by
  `name` ascending. That covers `connect` itself and every `connect_*` add-on;
  being a plain prefix match, it would also cover an unrelated module whose name
  merely begins with `connect`.
- **Page/entry title rule:** `module.shortdesc or module.name`.
- **Page skipping.** A module contributes nothing to a view when: the module
  path cannot be resolved, the file does not exist, it is oversized, it cannot
  be stat'ed / read / decoded as UTF-8, or rendering raises. Failures are logged
  (warning, or exception traceback for a render failure) and the module is
  simply absent from that view. One bad file never sinks a book.
- **`doc/tech_spec.md` is never read** by any code path. It is the agent-facing
  contract, deliberately excluded from both human books.
- **Multilingual read path (Userbook and Adminbook only).**
  - The documentation language for a request is derived by `_doc_lang`:
    take `context["lang"]`, else `user.lang`, else `"en"`; keep the part before
    the first `_` (so `en_US` -> `en`); if the result does not match
    `LANG_CODE_RE`, use `"en"`.
  - Candidate order for a module's file, first hit wins:
    1. `<module_path>/doc/i18n/<lang>/<filename>`
    2. `<module_path>/doc/<filename>`
  - The fallback is **per file**, so a partially translated installation renders
    fully, mixing translated and source pages.
  - There is **no runtime dependency on `LANG.md` / `LANG.local.md`**. Those
    files govern authoring; the read path is purely "translated-if-present, else
    source".
  - The leading provenance marker (`I18N_MARKER_RE`, one substitution, anchored
    at the start of the text) is stripped before rendering, so it never reaches
    the reader. Guides are read with `strip_marker=True` -- which means the
    marker is also stripped from a source file that happens to carry one.
- **Changes archive.**
  - Per module: list `doc/changes/`, sorted by file name ascending; keep the
    names matching `CHANGE_FILE_RE`; render each with `strip_marker=False`
    (change files are never translated, so they carry no marker); the captured
    `YYYY-MM-DD` is the entry's date. A missing module path or missing
    `doc/changes/` folder yields no entries.
  - Aggregation axis is the **day**: entries from all modules that carry a file
    for the same date are grouped under that date.
  - Days are ordered **most recent first** (reverse lexicographic sort of the
    `YYYY-MM-DD` strings, which equals reverse chronological). Entries within a
    day follow the module iteration order, i.e. module name ascending.
  - The archive is the timeline; the two guides are the current snapshot. The
    duplication is intentional.
- **Render cache.** Keyed `(filepath, strip_marker)`, storing `(st_mtime, html)`.
  A hit requires the stored mtime to equal the file's current mtime, so a
  changed file invalidates its own entry. The cache is a plain module-level dict
  -- per worker process, never persisted, unbounded in principle but bounded in
  practice by the number of documentation files across installed modules. Its
  practical effect: a redeploy that only rewrites `doc/` files is picked up on
  the next read with no restart and no module upgrade.

## Methods & Actions

All three public methods are `@api.model`, read-only (no writes, no side effects
beyond logging and the in-memory render cache), and take no arguments.

- `get_book()`
  - Assembles the Userbook in the reader's documentation language.
  - Returns `{"pages": [{"id", "module", "title", "html"}, ...]}` where `id` and
    `module` are both the technical module name, `title` is
    `shortdesc or name`, and `html` is the rendered `user_guide.md`.
  - `pages` is `[]` when no crawled module ships a readable guide.
  - Triggered by `POST /connect_book/book` and by any server-side caller.
- `get_admin_book()`
  - Same shape and same ordering as `get_book`, reading `admin_guide.md`.
  - **Access rule:** raises `AccessError` ("Administrator access is required to
    read the Admin Book.", translatable) unless the caller
    `has_group("base.group_system")`. The check precedes any file access.
  - Triggered by `POST /connect_book/admin` and by any server-side caller.
- `get_changes()`
  - Assembles the archive. Returns
    `{"days": [{"date": "YYYY-MM-DD", "entries": [{"module", "title", "html"}, ...]}, ...]}`,
    days descending, entries by module name.
  - Not language-aware: it reads only the source `doc/changes/*.md`.
  - Triggered by `POST /connect_book/changes` and by any server-side caller.

Private helpers, given as behavioral contracts:

- `_doc_lang() -> str` -- the language-derivation rule above; always returns a
  value matching `LANG_CODE_RE`.
- `_collect_pages(filename, lang) -> list` -- the shared collector behind both
  books: module selection, per-module read, page-dict assembly, skip-on-failure.
- `_read_module_doc(module_name, filename, lang) -> html | None` -- resolves the
  module path, walks the i18n-then-source candidate list, and delegates to
  `_render_doc_html(..., strip_marker=True)`. `None` when the module path is
  unknown or neither candidate exists.
- `_render_doc_html(filepath, strip_marker) -> html | None` -- the single
  read+render funnel shared by guides and change files. Order of operations:
  stat (failure -> `None`); size check (over `MAX_DOC_BYTES` -> `None`); cache
  lookup by `(filepath, strip_marker)` with mtime equality; read as UTF-8
  (`OSError` / `UnicodeDecodeError` -> `None`); strip the marker when asked;
  render (any exception -> logged traceback, `None`); store in the cache; return
  the HTML.
- `_read_module_changes(module_name) -> [(date_str, html), ...]` -- the
  per-module change-file scan described above.

The renderer's public contract, `md_to_html(text) -> str`:

- Empty or falsy input returns `""`. Line endings are normalised (`\r\n`, `\r`
  -> `\n`) before parsing.
- Block syntax supported: ATX headings `#`..`######` (each emitted with an `id`
  slug derived from the heading text: tags stripped, non-word characters
  dropped, lower-cased, runs of whitespace/underscores replaced by `-`);
  paragraphs (consecutive non-blank lines joined by a single space); unordered
  (`-`, `*`, `+`) and ordered (`1.`, `1)`) lists with nesting by indentation and
  lazy continuation of an indented, marker-less line into the previous item;
  fenced code blocks (three or more backticks or tildes, optional language token
  emitted as `class="language-<lang>"`); blockquotes (`>` prefix, content
  rendered recursively); GFM pipe tables (a header row plus a dash/colon
  separator row, then body rows until a blank or pipe-less line); horizontal
  rules (three or more `-`, `*` or `_`).
- Inline syntax: `**bold**`, `*italic*`, backtick-delimited inline code,
  `[text](url)` links rendered with `target="_blank" rel="noreferrer noopener"`,
  and `![alt](src)` images. Underscores are deliberately **not** emphasis
  markers, so identifiers such as `res_partner` or `connect_book` survive
  intact. Note that the renderer supports single-backtick code spans only --
  the double-backtick form is not parsed.
- **`diff` fenced blocks** are rendered line by line: a line starting with `+`
  is wrapped in `<span class="o_diff_add">`, a line starting with `-` in
  `<span class="o_diff_del">`, others plain. This is what colours the Changes
  archive.
- **Escaping is total.** Every piece of text passes through HTML escaping;
  inline code is stashed before escaping so its content is never re-formatted.
  No raw markup from a documentation file can reach the page.
- **URL-scheme allowlist.** A link or image URL carrying an explicit scheme
  outside `{http, https, mailto}` is rewritten to `#`. Scheme-relative and
  relative URLs pass through unchanged.

## Security

- No security groups of its own, no record rules, no `ir.model.access.csv`.
- All three HTTP routes are `auth="user"` -- an authenticated internal user.
- **The Adminbook is admin-only, enforced in two independent layers:**
  1. UI: the `Admin Guide` menu item carries `groups="base.group_system"`, so it
     is hidden from everyone else.
  2. Server: `get_admin_book` itself raises `AccessError` for a caller outside
     `base.group_system`. **The method is the defence of record**; hiding the
     menu is convenience only, and calling `/connect_book/admin` directly gains
     nothing.
- The Userbook and Changes menus and actions carry **no** group restriction.
- `sudo()` is used in exactly one place: the `ir.module.module` search that
  enumerates installed modules. It grants no other elevated access, and the user
  never reaches the registry directly.
- **Rendered-HTML trust boundary.** Guide and change HTML is injected
  client-side through OWL `markup()` / `t-out` with no further sanitisation.
  `md_to_html` is therefore the sanitiser of record: it escapes all text and
  allowlists URL schemes, so a `javascript:` or `data:` link in a documentation
  file cannot execute in the reader's authenticated session.
- The language code is validated before it is joined into a path, so a crafted
  `lang` in the context cannot escape the module's `doc/` folder.

## Views & UI

Client actions (`ir.actions.client`, no `res_model`, no context):

| XML id | Name | Tag |
|---|---|---|
| `action_connect_book` | `User Guide` | `connect_book.book` |
| `action_connect_book_admin` | `Admin Guide` | `connect_book.admin` |
| `action_connect_book_changes` | `Changes` | `connect_book.changes` |

Menu items -- the module defines **no root menu**; all three hang under the
`Documentation` menu that the `connect` module provides
(`connect.connect_documentation_menu`, itself under the `Connect` top menu):

| XML id | Name | Sequence | Action | Groups |
|---|---|---|---|---|
| `menu_connect_book_doc` | `User Guide` | 5 | `action_connect_book` | none |
| `menu_connect_book_admin` | `Admin Guide` | 7 | `action_connect_book_admin` | `base.group_system` |
| `menu_connect_book_changes` | `Changes` | 10 | `action_connect_book_changes` | none |

OWL components, registered in the `actions` registry under the tags above:

- `BookApp` (template `connect_book.BookApp`, tag `connect_book.book`).
  - Two-pane viewer: left = search input + table of contents, right = the
    rendered guide inside `.o_connect_book_doc`.
  - Reactive state: `pages`, `activeId`, `search`, `loaded`.
  - On start it fetches `this.constructor.endpoint` -- a **static class
    property** defaulting to `/connect_book/book`, which is the whole extension
    point -- stores `data.pages || []`, sets `loaded`, and auto-selects the
    first page when there is one.
  - The table of contents lists pages whose `title`, lower-cased, contains the
    trimmed lower-cased search string; an empty search shows all. Filtering is
    by title only, never by body text.
  - The active page's `html` is wrapped in `markup()` and rendered with `t-out`;
    the active entry is highlighted with the `o_active` class.
  - UI states: `Loading…` before the fetch resolves; `No documentation found.`
    when the filtered list is empty; and a right-pane placeholder
    `Select a section on the left to start reading.` when nothing is selected.
- `AdminBookApp` (tag `connect_book.admin`) -- subclasses `BookApp` and
  overrides `static endpoint = "/connect_book/admin"`. Nothing else differs:
  same template, same state, same behaviour.
- `ChangesApp` (template `connect_book.ChangesApp`, tag `connect_book.changes`).
  - Two-pane archive: left = the day timeline, right = every module's entry for
    the selected day.
  - Reactive state: `days`, `activeDate`, `loaded`. On start it fetches
    `/connect_book/changes` and auto-selects the most recent day.
  - The timeline groups the (already descending) days by their `YYYY-MM` prefix
    under a `Month Year` header; each day link shows `Weekday, D` plus a badge
    with the number of entries. Month and weekday names are formatted
    client-side in English from the `YYYY-MM-DD` string; the full heading of the
    selected day reads `D Month YYYY`.
  - Each entry renders its module title above its `markup()`-wrapped HTML.
  - UI states: `Loading…`, `No changes recorded yet.`, and the placeholder
    `Select a day on the left to see what changed.`
- Styling (`static/src/book/book.scss`): a fixed 280 px sidebar, hover and
  `o_active` highlighting for list entries, month headers and count badges for
  the archive, `.o_diff_add` / `.o_diff_del` colouring for diff lines, and
  typography for headings, code, tables, blockquotes and images inside
  `.o_connect_book_doc`.

## API Endpoints

Three routes on one controller, each `type="jsonrpc"`, `auth="user"`, taking no
parameters and returning the corresponding model payload verbatim:

| Route | Model call | Response |
|---|---|---|
| `/connect_book/book` | `connect.book.get_book()` | `{"pages": [{id, module, title, html}, ...]}` |
| `/connect_book/admin` | `connect.book.get_admin_book()` | same shape, admin guides; `AccessError` for non-administrators |
| `/connect_book/changes` | `connect.book.get_changes()` | `{"days": [{date, entries: [{module, title, html}, ...]}, ...]}` |

The controller adds no logic of its own -- no argument parsing, no access check
(the model performs the admin check), no response reshaping.

## Automation

- None. No crons, no server actions, no automated actions, no hooks
  (`post_init_hook` / `uninstall_hook` and friends are all absent).

## Seed / Demo Data

- No records are created, in either normal or demo mode. The only data file
  defines the three client actions and three menu items listed above.
- The module does ship its own documentation capsule under `doc/`, which
  surfaces as `connect_book`'s own pages in the Userbook, the Adminbook and the
  Changes archive -- content, not database seed data.
