# Connect Website — User Guide

This module puts a call button on your public website. A visitor clicks it and
talks to your team straight from the browser — no phone number to dial, no app
to install on their side.

Two audiences see this module from different ends: the website visitor, who
clicks the button, and your staff, who answer the call in Odoo.

## For the visitor

The button appears as a card with a **Let's Talk** label wherever it was placed
on the site. Clicking it starts a call from the browser: the visitor's browser
asks for microphone permission, and once granted, the call rings in your
company.

While a call is coming in the button turns into two controls — accept and
reject — so the visitor stays in charge of the conversation.

There is nothing for the visitor to install or log into. It works in a normal
browser over the web.

## For your team

A call from the website arrives like any other Connect call: it rings the
destination your administrator configured, shows up in the phone panel, and is
logged in **Connect ▸ Voice ▸ Calls** with its recording, if recording is on.

What is different is what you know about the caller. Website calls have no
phone number behind them in the usual sense, so treat the call as an anonymous
enquiry until the person identifies themselves. If they turn out to be an
existing customer, link the call to their record the way you would any other.

## Adding the button to a page

The button is a website building block. Edit a page in the website editor and
drop the **Connect Button** snippet where you want it, the same way you add any
other block. Styling follows your site's theme.

Whether the button works at all depends on the module being enabled and pointed
at a destination — that part is administrator work.

## When it does not work

- **The button does nothing when clicked.** Usually the feature is switched off
  in the Connect settings, or the extension it should call is not set.
- **The browser never asks for the microphone.** The site must be served over
  HTTPS; browsers refuse microphone access on plain HTTP.
- **The call rings nowhere.** The destination extension exists but nothing is
  behind it — one for your administrator.
