# Language Policy

Rules for how documentation languages work in this repository. This file
defines the fields and their meaning; the actual values for this repo --
which languages are active, the source language, the target list -- live in
[`LANG.local.md`](LANG.local.md). Keeping the rules and the values in
separate files means the values can be reviewed and changed on their own,
without touching the explanation of what they mean.

Read by the agent and by the `connect-doc-i18n` skill.

> Two independent planes of i18n -- do not mix them:
> - **UI strings** of modules (menus, labels, messages) are localised the
>   Odoo way, via `.po` / `.pot` files.
> - **Document content** (the human guides) is governed by this policy and
>   stored as language mirrors under each module's `doc/i18n/<lang>/`.

## Agent communication

`LANG.local.md` -> `Agent communication` -> `primary` records the canonical
language the agent uses when talking to the user. Actual enforcement lives in
the harness / global Claude instructions; this setting only records the
canonical choice.

## Documentation

`LANG.local.md` -> `Documentation` defines four fields -- their meaning:

- **`source`** is the canonical authoring language for every document. The
  agent always writes the source first.
- **`targets`** are mirror languages kept in sync with the source. May be
  empty -- the system is multilingual-ready even when it ships a single
  language.
- **`translate`** lists the human documents mirrored into every target
  language. Only the User Guide and the Admin Guide are translated.
- **`source-only`** documents are never translated: the agent contract
  (`tech_spec.md`) and the change timeline (`changes/`).

Rules that hold regardless of the selected values:

- **Where mirrors live:** a target-language copy of `doc/<file>` lives at
  `doc/i18n/<lang>/<file>`. `connect_book` serves each reader the file
  matching their Odoo language, falling back to the source file when a
  translation is absent.
- **Adding a language:** run the `connect-doc-i18n` skill (`add <lang>`). It
  mirrors every module's `translate` files into `doc/i18n/<lang>/`, stamps
  each with a provenance marker, and registers the new code under `targets`
  in `LANG.local.md`. After a language exists, the agent authors
  documentation in **all** target languages by default -- see the Definition
  of Done in `AGENTS.md` -> "Documentation is part of the change".
