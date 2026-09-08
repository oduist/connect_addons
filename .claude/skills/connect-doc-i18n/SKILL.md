---
name: connect-doc-i18n
description: >
  Manage multilingual Connect documentation. Use when adding, syncing,
  checking, or removing a documentation language — when the user says "add a
  language to the docs", "translate the documentation", "mirror the guides to
  <lang>", "sync translations", "check translation drift", or mentions LANG.md /
  LANG.local.md targets. Translates each module's human guides (user_guide.md, admin_guide.md)
  from the source language into target-language mirrors under doc/i18n/<lang>/,
  keeping them in sync with the source.
---

# connect-doc-i18n — multilingual documentation

Mirror this repository's **human** documentation into additional languages
and keep the mirrors in sync with the source. This skill operates only on
files; the translation itself is done by you (the agent).

## Scope — read `LANG.md` + `LANG.local.md` first

`LANG.md` (repo root) is the **policy** (what the fields mean); `LANG.local.md`
(repo root) is the **selection** — the actual values you read and write.
Honour its `Documentation` section:

- `source` — canonical authoring language (do not translate away from it).
- `targets` — languages to mirror into.
- `translate` — the files mirrored per module (currently `user_guide.md`,
  `admin_guide.md`). **Only these.**
- `source-only` — never translate (`tech_spec.md`, `changes/`).

Mirrors live at `<module>/doc/i18n/<lang>/<file>`, a per-language copy of the
`translate` files. `connect_book` serves the reader the mirror matching their
Odoo language and falls back to the source file when a mirror is missing.

## Commands

Invoke as `connect-doc-i18n <command> [lang]`.

### `add <lang>`
1. Confirm `<lang>` is a valid short ISO code (e.g. `fr`, `de`); refuse the `source`.
2. For **every** installed `connect*` module, for each file in `translate` that
   exists in the source: translate it and write the mirror at
   `doc/i18n/<lang>/<file>` (create dirs as needed).
3. Stamp each mirror with the provenance marker (see below).
4. Add `<lang>` to `targets` in `LANG.local.md`.
5. Append a `doc/changes/<today>.md` entry per touched module (the change log is
   itself source-only — write the entry in the `source` language).
6. Run `check <lang>` and report it is clean.

### `sync [lang]`
Re-translate only what is **stale or missing**: for each mirror, compare the
recorded source SHA in its marker against the current source file SHA; if they
differ, or the mirror is absent while the source exists, (re)translate and
re-stamp. Leave up-to-date mirrors untouched. Also delete orphaned mirrors whose
source file no longer exists. With no `lang`, do every target.

### `check [lang]`
Read-only. Report, per language: `stale` (source changed since translation),
`missing` (source exists, mirror absent), `orphaned` (mirror exists, source
gone). Exit clean only when all three are empty. Use this in the Definition of
Done before declaring a docs task complete.

### `remove <lang>`
Delete every `doc/i18n/<lang>/` folder and remove `<lang>` from `targets` in
`LANG.local.md`.

## Provenance marker

Each mirror's **first line** records what it was translated from:

```
<!-- i18n source=user_guide.md sha=<first 12 hex of sha256 of the source file> lang=<lang> -->
```

`connect_book` strips this line before rendering, so it never shows in the
Book. The SHA is over the **raw bytes of the source file** at translation
time and is what `sync`/`check` compare against.

## Translation rules (must hold for every mirror)

- Preserve Markdown structure exactly: same headings (and their order), lists,
  tables, links, and heading anchor text.
- **Never translate:** fenced code blocks, inline code, identifiers, module
  names (`connect_book`), field/method names, file paths, and the content of
  ```` ```diff ```` blocks. Translate only prose, heading text, and prose inside
  table cells.
- Keep the same filename and section layout, so the Book renders structurally
  identically — only the natural-language text differs.
- One file in → one file out. Do not merge, split, or reorder documents.

## Definition of Done (after any command that writes)

1. `check` is clean for every target language.
2. `LANG.local.md` `targets` reflects reality.
3. The matching `doc/changes/<today>.md` entries exist (source language).
4. Nothing under `source-only` was translated.

See `AGENTS.md` → "Documentation is part of the change" for how this fits
into the wider Definition of Done for a code change.
