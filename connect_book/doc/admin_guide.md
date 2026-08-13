# Connect Book — Administration

This page is for administrators. It explains who may read which part of the
Book, where the documentation files must live on disk for the Book to find
them, and the limits the crawler applies. It is itself visible only to
administrators.

## Connect Book has no settings

The module exposes **no configuration at all** -- no Settings page, no system
parameters, no per-user options, nothing to switch on or tune. What the Book
shows is decided entirely by two things: which `connect*` modules are installed,
and which documentation files those modules carry on disk. To change the Book,
change the files.

## The three sections and who sees them

| Section | Reads | Who can open it |
|---|---|---|
| **User Guide** | each module's `doc/user_guide.md` | every internal user |
| **Admin Guide** | each module's `doc/admin_guide.md` | administrators only |
| **Changes** | each module's `doc/changes/YYYY-MM-DD.md` | every internal user |

The **Admin Guide** is restricted to the *Settings* group
(`base.group_system`), and the restriction is enforced twice:

- **In the menu** -- `Connect ▸ Documentation ▸ Admin Guide` carries
  `groups="base.group_system"`, so a user outside that group never sees it.
- **On the server** -- the method behind the menu re-checks the group itself and
  refuses with an access error for anyone else. Calling the admin endpoint
  directly from a browser or a script returns nothing but that error, so hiding
  the menu is a convenience, not the actual protection.

The **User Guide** and **Changes** menus carry no group restriction: any
authenticated internal user can open them.

## Where documentation files must live

The Book reads files from the module directory on disk -- never from the
database. Inside a module, the layout is fixed:

```
<module>/
  doc/
    user_guide.md              # the User Guide page for this module
    admin_guide.md             # the Admin Guide page for this module
    tech_spec.md               # never shown in the Book (agent-facing)
    changes/
      2026-08-13.md            # one file per calendar day
    i18n/
      fr/
        user_guide.md          # translated mirrors
        admin_guide.md
```

Rules that follow from that layout:

- The two guide file names are exact: `user_guide.md` and `admin_guide.md`.
  Any other file in `doc/` is ignored.
- `doc/tech_spec.md` is deliberately **not** part of the Book. It is the
  technical contract for developers and agents, and it is never rendered for
  human readers.
- In `doc/changes/`, only names matching `YYYY-MM-DD.md` are read. A
  `notes.md` or a `2026-8-13.md` in that folder is silently ignored. A module
  with no `doc/changes/` folder simply contributes no days.
- A module with no `doc/` folder, or with none of these files, does not appear
  in the Book at all. That is not an error.

## Which modules are crawled

Every module whose technical name **starts with** `connect` and whose state is
`installed` is crawled -- that is `connect` itself plus every `connect_*`
add-on. Modules that are only *downloadable*, *uninstalled*, *to upgrade* or in
any other state are not read, so the Book always reflects the code that is
actually running. Pages are listed in ascending module-name order, and a page's
title is the module's display name (its manifest `name`), falling back to the
technical name.

Note that the match is a plain prefix on the technical name, so a third-party
module named, say, `connectivity_x` would also be crawled if it happened to
carry a `doc/user_guide.md`.

## Render limits and error isolation

- **Size cap.** A documentation file larger than **1 MiB** is skipped and a
  warning is written to the Odoo log. Documentation files are prose; if you hit
  this limit, split the guide instead of raising anything.
- **One bad file never breaks the Book.** If a file cannot be read (permissions,
  invalid UTF-8) or fails to render, that single page -- or that single day's
  entry -- drops out of the Book and a warning is logged. The rest of the Book
  renders normally. If a module's page is unexpectedly missing, the Odoo log is
  where the reason is.
- **Rendered HTML is escaped.** Markdown is converted to HTML by the module's
  own renderer; all text is escaped, and links or images whose URL uses a scheme
  other than `http`, `https` or `mailto` are neutralised. A documentation file
  therefore cannot inject script into a reader's session.

## Caching and deployment

Rendered HTML is cached per file, keyed on the file's modification time, and
held in the memory of each Odoo worker process. Nothing is written to the
database.

The practical consequence: **editing a documentation file on disk is enough.**
The next reader who opens the Book gets the new text, because the cache entry is
invalidated as soon as the file's modification time changes. No Odoo restart, no
module upgrade, no cache-clearing action is required after a redeploy that only
touches `doc/` files. (Adding a *new module* is different -- a module must be
installed before its documentation joins the Book.)

## Documentation languages

The Book serves each reader in their own language: for a given module and page
it first looks for a translated mirror at `doc/i18n/<lang>/<file>` matching the
reader's Odoo language, and falls back to the source file when that mirror does
not exist. The fallback is per file, so a partially translated installation
still reads cleanly. The language code is taken from the user's Odoo language
(`en_US` becomes `en`); an unrecognised value falls back to English.

- Translations are **pre-generated files** committed next to the code, not live
  machine translation. There is no per-request cost and no external service.
- The **Changes** archive is never translated -- it is kept in the source
  language only.
- Which languages exist is a repository decision recorded in `LANG.local.md`
  (the meaning of those fields lives in `LANG.md`). Today the documentation
  ships in English only: `source: en`, no targets. Adding a language is a
  maintainer task performed with the `connect-doc-i18n` skill.
- A mirror begins with an HTML comment recording what it was translated from.
  The Book strips that line before rendering, so it never appears on screen.
