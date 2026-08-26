---
name: writing-odoo-module-description
description: Use when writing or regenerating an Odoo module's Apps Store page (static/description/index.html) for an Oduist/connect addon — the store "description", app listing, module landing page, or features/marketing HTML shown in Odoo Apps and the Apps Store.
---

# Writing an Odoo Module Description

## Overview

The "description" of an Odoo module is its **Apps Store page**:
`static/description/index.html`. It follows the Oduist **"Aurora"** house
style, the same palette the marketing site uses (`oduist-com/PALLETE.md`): one
dark void slab holding a hero, a feature-card grid, a docs band and a footer,
with Font Awesome (`fa-*`) icons. Regenerating it means **filling the known
`template.html` with content extracted from the module's own code**, not
inventing markup or a new visual language.

The palette is dark-only by design — the block paints its own `#04050a` ground
so it reads as a deliberate panel on Odoo's light Apps page. `template-classic.html`
holds the retired purple/amber skin for reference; never generate from it.

> ⚠️ **All CSS must be inline `style=""` attributes — never a `<style>`
> block.** Odoo's `html_sanitize` strips `<style>` and `<script>` tags out of
> module descriptions (verified on Odoo 19 — a `<style>`-based design renders
> completely unstyled in the backend Apps view), but it **keeps** inline
> `style=""` attributes. Verified end-to-end on Odoo 19 for everything the
> template uses: `linear-gradient`, `conic-gradient`, `filter:blur()`,
> `background-clip:text` + `-webkit-text-fill-color`, `rgb(r g b / a)`,
> `box-shadow` (incl. `inset`), `display:grid`, `clamp()`, `letter-spacing`,
> `text-wrap:balance`. `template.html` is already written this way; keep it
> that way. The trade-off is no `:hover` and no `@media` — responsiveness comes
> from `grid-template-columns:repeat(auto-fit,minmax(288px,1fr))`, `flex-wrap`
> and `clamp()`.

> ⚠️ **Geist cannot be loaded.** A web font needs `<link>` or an `@font-face`
> inside `<style>`, and the sanitizer removes both. The template asks for a
> locally installed Geist and otherwise falls back to the system UI face; it is
> designed to hold up on that fallback. Never add a font `<link>` to "fix" this.

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

1. **Hero** — a void panel holding: a **kicker** (mono, uppercase, cyan
   `#2dd4ff`; the provider / role label, e.g. `TWILIO INTEGRATION`), the
   **title** (benefit slogan, ends `!`), a **sub** line, the shared `icon.png`
   in a raised badge, and one blurred **aurora bloom** (`aria-hidden`).
2. **Trial note** — one slim cyan-tinted strip: "30-day free trial …". Keep it
   for every standalone, purchasable module; **delete** it only for an
   `auto_install` bridge (e.g. `connect_crm_twilio`).
3. **Features** — a cyan mono "What's inside" kicker + a heading + a
   `repeat(auto-fit,minmax(288px,1fr))` grid of cards. Each card is an icon
   chip (a `fa-*` icon in cyan on `#14161f`) + a title + a one-line
   description. The **last** card is the CTA — a gradient hairline border and a
   gradient icon chip — for an upcoming feature or call to action.
4. **Docs band** — "Docs & support" + a gradient button to oduist.com.
5. **Footer** — `Oduist` wordmark in gradient text + the
   `Connecting Odoo to Everything` tagline in mono.

### Palette discipline

Aurora has two rules worth honouring, both from `PALLETE.md`:

- **One Gradient** — `linear-gradient(100deg,#2dd4ff,#7c83ff 42%,#e16bff)` is
  the only multi-hue element, and only for actions, the brand mark and aurora
  blurs. In this template that is exactly four places: the hero bloom, the CTA
  card, the docs button, the wordmark. Every other accent is flat cyan.
- **Earned glow** — one focal glow per section. The template spends its on the
  hero bloom; do not add another.

| Role | Value |
| --- | --- |
| Void / page ground | `#04050a` |
| Panel (cards, bands) | `#0e0f14` |
| Raised (icon chips) | `#14161f` |
| Ink / muted / faint | `#eef0fa` / `#9aa1bd` / `#5b6184` |
| Accent (kickers, icons) | `#2dd4ff` |
| Hairline / strong | `rgb(255 255 255 / .08)` / `.16` |
| Ink on gradient fills | `#06070d` |

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
- **Adding a font `<link>` so Geist loads** — the sanitizer removes it; the
  fallback stack is the design, not a bug.
- **Reaching for a second gradient or a second glow** — breaks the two Aurora
  rules above. Flat cyan is the accent everywhere else.
- **Generating from `template-classic.html`** — that is the retired skin.
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
