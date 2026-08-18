# Connect ElevenLabs Sale — Admin Guide

Giving a voice AI agent access to the sales catalogue and the ability to create
partners and sales orders during a call.

Requires the Connect **Admin** group. The module depends on `connect_elevenlabs`
and `sale_management`, and adds no settings and no menus — what it ships is
**tools** and the endpoints behind them.

## What the module ships

Five agent tools:

| Tool | Endpoint | What it does |
| --- | --- | --- |
| `create_partner` | `/connect_elevenlabs_sale/create_partner` | Creates a contact from a name and phone, returning the partner id. Its description restricts the agent to one call per conversation, and forbids it when a partner is already known. |
| `get_products` | `/connect_elevenlabs_sale/get_products` | Returns the catalogue: product id, name, categories, price, description. |
| `get_sale_orders` | `/connect_elevenlabs_sale/get_orders` | The order names belonging to a partner. |
| `get_sale_order_info` | `/connect_elevenlabs_sale/get_order` | Detail of one order, by its reference (e.g. `S00001`). |
| `create_sale_order` | `/connect_elevenlabs_sale/create_order` | Creates an order for a partner, product and quantity. |

The endpoints are public routes protected by a **tool token**; an unauthenticated
request is rejected. They are called by ElevenLabs, not by browsers.

## Two behaviours to know before going live

**Stock is the real on-hand quantity.** `get_products` returns
`items_in_stock` read from inventory: a number is the quantity on hand, `0`
means none are left, and `null` means the quantity is not tracked — the product
is not storable, or the `stock` module is not installed. The tool description
instructs the agent to state an availability only when it has a number, and to
promise a call-back otherwise.

Two properties to understand before an agent quotes these figures to customers:

- It is **on-hand**, not free-to-promise: units reserved for other orders are
  still included. If your business commits stock at order time, treat a low
  number as "check first" rather than "yes".
- The module does not depend on `stock`. On a database without inventory
  management every product reports `null`, which is correct — but it means an
  agent there can never confirm availability.

**Only published products are exposed.** `get_products` filters on the same
published flag that governs website visibility. This is the lever for controlling
what the agent may sell: unpublish a product and it disappears from the agent's
answers. It also means a catalogue never published for the web is, from the
agent's point of view, empty.

## Setting it up

1. **Create or pick the agent** under **Connect ▸ Voice ▸ Agents**.
2. **Attach the tools** it needs, on the **Conversation** tab. Read-only
   deployments (`get_products`, `get_sale_orders`, `get_sale_order_info`) are a
   sound first step and carry almost no risk.
3. **Sync** with **SYNC TOOLS** on the ElevenLabs settings page — until then
   ElevenLabs has no definition for the tools and the agent never calls them.
4. **Write the prompt** around your commercial rules: what the agent may quote,
   what it must never promise, when it must hand over to a person.
5. **Point a number or extension at the agent.**
6. **Check the `connect_elevenlabs_sale` license** — the module's call-data
   extension is license-checked.

## Deciding whether the agent may create orders

`create_sale_order` and `create_partner` write to your commercial records, and
the failure modes are not symmetrical:

- A **wrong quantity** on an order created by voice is easy to make and easy to
  miss — speech recognition is where this goes wrong, not the model's reasoning.
- A **duplicate partner** is created whenever the agent fails to recognise an
  existing customer. The tool description tries to prevent this, but it is a
  soft constraint expressed in words, not an enforced rule.

If your sales process cannot absorb these, attach the read-only tools and let
the agent gather intent while a person confirms the order. If you do attach
them, keep orders in a draft stage that a human confirms, and check the first
weeks of agent-created orders against their transcripts.

## After changing a tool

Any change to a tool — parameters, description, timeout — needs **SYNC TOOLS**
to reach ElevenLabs. The **description** is what the model reads to decide when
to use the tool, so editing it changes behaviour as surely as editing the prompt.

## Health check

1. Publish a test product with a known quantity on hand.
2. Call the agent and ask what is available — the product is named, with its
   price, and the quantity the agent states matches Odoo. Change the quantity in
   Inventory and ask again: the new figure must be the one the agent reports.
3. Ask for your orders as a known customer — the agent lists them.
4. Ask about one order by reference — the details match Odoo.
5. If order creation is attached: place a small order, then check quantity,
   product and partner against the call's transcript.
