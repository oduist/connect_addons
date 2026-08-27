# Agent Instructions

## Plan First, Then Act

Before making any code changes, always:
1. Explain your understanding of the task
2. Present a detailed plan of changes (which files will be created/modified, what exactly will change)
3. Ask for explicit confirmation before proceeding with implementation

Do NOT write or modify any code until the user explicitly approves the plan.

## Odoo development workflow
When Oduflow MCP is connected, call 'get_agents_guide' to get development workflow instructions.

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
