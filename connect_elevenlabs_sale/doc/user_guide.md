# Connect ElevenLabs Sale — User Guide

This module lets the voice AI agent work with sales: a caller can ask what you
sell, check their orders, and place a new one — all in conversation, without
anyone from your team on the line.

What you notice is sales orders that appeared from phone calls, and callers who
already know their order status when they reach a person.

## What the agent can do

| The customer says | The agent does |
| --- | --- |
| "What do you sell?" | Lists products and categories from your catalogue. |
| "I'd like to order two of those" | Creates a sales order for that product and quantity. |
| "What have I ordered?" | Lists the sales orders belonging to that caller. |
| "What's in order S00042?" | Reads back the details of that order. |
| "I'm a new customer" | Creates a contact for them, once per conversation. |

Which of these a given agent can do depends on the tools your administrator
attached to it.

## Orders created by the agent

An order created this way is an ordinary sales order — it appears in the
pipeline, and the call that produced it carries the transcript and summary of
what was agreed.

Two habits are worth adopting:

- **Check the order against the transcript** before confirming it, especially
  quantity and product. The agent transcribes speech, and "fifteen" and "fifty"
  sound closer than either of you would like.
- **Verify the contact** on orders where the agent also created the customer.
  Names taken by ear are frequently misspelled.

## What the agent tells customers about stock

The agent reports a **fixed placeholder availability** for every product rather
than your real stock level. It does not read inventory.

This matters in practice: a customer can be told an item is available when it is
not. Until this is changed, do not treat anything the agent said about
availability as a commitment, and confirm stock before promising delivery.

## Products the agent knows about

Only **published** products are visible to the agent — the same published flag
that controls whether a product appears on the website. A product missing from
the agent's answers is almost always unpublished rather than broken.

Prices come from the product's sales price.

## What is administrator territory

Which agent answers, what it may do, and how the catalogue is exposed are all
configured by an administrator. See the Admin Guide.
