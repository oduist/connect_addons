---
name: writing-odoo-module-description
description: Use when writing or regenerating an Odoo module's Apps Store page (static/description/index.html) for an Oduist/connect addon — the store "description", app listing, module landing page, or features/marketing HTML shown in Odoo Apps and the Apps Store.
---

# Writing an Odoo Module Description

## Overview

The "description" of an Odoo module is its **Apps Store page**:
`static/description/index.html`. It follows the fixed Oduist "Connect" house
style: a hero (with signal rings), a feature-card grid, a docs band and a
footer, using Font Awesome (`fa-*`) icons. Regenerating it means **filling the
known `template.html` with content extracted from the module's own code**, not
inventing markup or a new visual language.

> ⚠️ **All CSS must be inline `style=""` attributes — never a `<style>`
> block.** Odoo's `html_sanitize` strips `<style>` and `<script>` tags out of
> module descriptions (verified on Odoo 19 — a `<style>`-based design renders
> completely unstyled in the backend Apps view), but it **keeps** inline
> `style=""` attributes, including `linear-gradient`, `box-shadow`, `display:grid`
> and `flex`. `template.html` is already written this way; keep it that way.
> The trade-off is no `:hover` and no `@media` — responsiveness comes from
> `grid-template-columns:repeat(auto-fit,minmax(280px,1fr))` and `flex-wrap`.

Do not add external fonts, JS, `<link>`s or remote images; only the local
`icon.png` is referenced.

Do not confuse it with `doc/index.rst`, which is only a version **Change Log**.

## When to Use

- "Generate/write/regenerate the description for module X"
- A new addon under `connect_addons*` has no `static/description/index.html`
- Refreshing the features list after adding functionality

## Anatomy (fixed section order)

Everything lives inside one outer `<div style="…">` (font + padding). Every
element carries its own inline `style=""`.

1. **Hero** — an inline gradient card holding: an **eyebrow** (uppercase, amber;
   the provider / role label, e.g. `TWILIO INTEGRATION`), the **title** (benefit
   slogan, ends `!`), a **sub** line, the shared `icon.png` in a glass badge,
   and a decorative **signal-rings** `<div>` (`aria-hidden`).
2. **Trial note** — one slim amber strip: "30-day free trial …". Keep it for
   every standalone, purchasable module; **delete** it only for an
   `auto_install` bridge (e.g. `connect_crm_twilio`).
3. **Features** — a dark "What's inside" eyebrow + a heading + a
   `repeat(auto-fit,minmax(280px,1fr))` grid of cards. Each card is an icon
   chip (a `fa-*` icon) + a bold title + a one-line description. The **last**
   card is the CTA (dashed amber chip + border) for an upcoming feature or call
   to action.
4. **Docs band** — "Docs & support" + a pill link to oduist.com.
5. **Footer** — `Oduist` wordmark + `Connecting Odoo to Everything` tagline.

Start from `template.html` in this skill directory — it is the full inline-styled
block with `{{PLACEHOLDER}}`s.

## Procedure

1. **Read `__manifest__.py`.** Take `name`, `summary`, `category`, `depends`
   and `auto_install`.
   - If `depends` includes `connect` (and the module isn't `connect` itself),
     it is an **extension module** → make the first feature card
     `fa-plug` / "Built for Connect" / "An extension of the Connect
     communication platform." (for modules that also need FreeSWITCH, say
     "Built for Connect & FreeSWITCH").
   - `auto_install: True` (a bridge) → **delete** the `.ocx-note` trial strip.
     Every other standalone module keeps it.
2. **Derive the feature cards from the code**, in user-facing terms — not model
   names. Each card is `(fa-icon, short title, one-line description)`. Scan:
   - `models/` — new business capabilities (a `connect.agent` model → `fa-microchip`
     "AI voice agents"; a recording field → `fa-microphone` "Call recording").
   - `views/` — buttons/actions the user sees (a "Call" button on a form →
     `fa-phone` "One-click calling").
   - `controllers/` — webhooks/external endpoints exposed.
   - `data/` — shipped templates, crons, automated flows.
   Write 4–7 cards; titles 2–4 words, descriptions one plain sentence. Pick
   **Font Awesome 4.7** icon names only (they render on the Apps Store): e.g.
   `fa-plug fa-phone fa-headphones fa-microphone fa-sitemap fa-comments
   fa-whatsapp fa-server fa-shield fa-random fa-microchip fa-bolt
   fa-video-camera fa-magic fa-paper-plane-o`.
3. **Eyebrow + slogan + sub** from `summary`/`name`, phrased as a customer
   benefit. The eyebrow is the provider/role label (e.g. `INFOBIP INTEGRATION`,
   `CORE PLATFORM`).
4. **Fill `template.html`**, deleting the `.ocx-note` block if it doesn't apply,
   and write it to `<module>/static/description/index.html`. Keep the `<style>`
   block byte-for-byte identical to the template.
5. **Images & manifest wiring** (do NOT invent PNGs):
   - **`icon.png` is shared across ALL connect addons — present and future.**
     The canonical file ships **inside this skill** as `icon.png`. Every
     module's `static/description/icon.png` must be a byte-for-byte copy of it;
     never fabricate or reuse a different icon. Copy it in:
     `cp "$SKILL_DIR/icon.png" <module>/static/description/icon.png`
     (`$SKILL_DIR` = this skill's directory). It is identical to
     `connect/static/description/icon.png`.
   - The manifest `'images'` preview should point at
     `static/description/logo.png` when a dedicated store banner exists. When
     there is no `logo.png` (the common case in this repo), reuse the shared
     icon instead: `'images': ['static/description/icon.png']`. Never fabricate
     a `logo.png`.

## Common Mistakes

- **Using a `<style>` block or CSS classes for styling** — Odoo strips `<style>`
  from module descriptions and the page renders unstyled. All CSS must be inline
  `style=""` attributes.
- Adding external fonts, `<link>`s, `<script>`s or remote images — the page must
  stay self-contained; only local `icon.png` is referenced.
- Using Font Awesome 5/6 icon names (`fa-robot`, `fa-solid …`) — the Apps Store
  ships FA **4.7**; stick to 4.7 names.
- Listing model/technical names instead of user benefits.
- Forgetting the `ocx-card--cta` modifier on the last (call-to-action) card.
- Keeping the `.ocx-note` trial strip on an `auto_install` bridge module.
- Regenerating `doc/index.rst` (that's the changelog) when asked for the
  description.
- Using a per-module or fabricated `icon.png` — always copy the canonical
  `icon.png` bundled in this skill. Never fabricate a `logo.png`; point
  `'images'` at `icon.png` when no `logo.png` exists.
