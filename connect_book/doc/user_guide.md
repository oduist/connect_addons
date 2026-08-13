# Connect Book

**Connect Book** is the documentation of your Connect installation, built right
into Odoo. Every Connect module keeps its guide in a file next to its own code,
and the Book collects those guides into one window -- no separate wiki, nothing
to keep in sync by hand. The Book shows only the modules that are actually
installed on this database, so what you read always matches what you run.

## Opening the books

Everything sits under the **Connect** top menu, in the **Documentation**
section. The whole **Connect** menu is reserved for users who have a Connect
role, so if you do not see it at all, ask your administrator to give you one --
the Book lives inside it and is not reachable otherwise.

- **Connect ▸ Documentation ▸ User Guide** -- the everyday guides, for everyone
  who can open Connect. This page you are reading now is one of them.
- **Connect ▸ Documentation ▸ Admin Guide** -- settings and tasks that need
  administrator rights.
- **Connect ▸ Documentation ▸ Changes** -- a day-by-day archive of what changed
  in the documentation.

## Reading a guide

The **User Guide** window has two panes:

- On the left -- the list of modules that ship a guide, one line per module.
  The line shows the module's display name, and the first one is opened for you
  when the window loads.
- On the right -- the text of the guide you selected. Click another line on the
  left to switch to it.

The box at the top of the left pane filters that list. Type a few letters and
only the modules whose **name** contains them stay in the list; the match is
case-insensitive and can be anywhere in the name. The search looks at the list
of module names only -- it does not search inside the text of the guides, so use
your browser's own find (`Ctrl+F` / `⌘F`) to look for a word inside the page on
the right. Clear the box to get the whole list back.

## The Changes archive

The **User Guide** answers "what is true now"; the **Changes** menu answers
"what changed, and when". Each time a module's documentation is updated, a short
note is recorded for that day, and the archive collects every such note:

- On the left -- the days on which something changed, grouped under a
  *Month Year* header, newest day on top. The small badge next to a day counts
  the modules that changed that day.
- On the right -- for the selected day, what each module added, changed or
  removed in its documentation. Where the note shows a structural before/after,
  removed lines are red and added lines are green.

## Why a module has no page

The list on the left is not the list of installed modules -- it is the list of
modules that ship a guide. A module appears in the **User Guide** only if it
carries a `doc/user_guide.md` file; the same holds for the **Admin Guide** and
its `doc/admin_guide.md`. If a module you use is missing from the list, its
documentation has simply not been written yet. Ask your administrator, or
whoever maintains that module, to add it.

## Why you may not see the Admin Guide

The **Admin Guide** menu is reserved for system administrators. If your user is
not one, the menu is not shown to you at all, and the two remaining entries --
**User Guide** and **Changes** -- are the ones you work with. That is expected,
not a problem with your installation: the Admin Guide describes settings and
privileged operations, and it is protected on the server as well as in the menu.
