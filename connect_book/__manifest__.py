# -*- encoding: utf-8 -*-
{
    "name": "Connect Book",
    "version": "1.0.0",
    "author": "Oduist",
    "maintainer": "Oduist",
    "support": "support@oduist.com",
    "license": "Other proprietary",
    "category": "Phone",
    "summary": "Live documentation assembled from the doc/ folders of Connect modules",
    "description": """
Connect Book
============

Crawls every installed ``connect*`` module, collects the Markdown files from
their ``doc`` folders and assembles them into interactive books inside the
Odoo UI: the User Guide, the administrator-only Admin Guide, and a day-by-day
Changes archive.

The documentation lives next to the module code -- no separate wiki.
""",
    "depends": ["connect", "web"],
    "data": [
        "views/connect_book_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "/connect_book/static/src/book/book.scss",
            "/connect_book/static/src/book/book.js",
            "/connect_book/static/src/book/book.xml",
            "/connect_book/static/src/admin/adminbook.js",
            "/connect_book/static/src/changes/changes.js",
            "/connect_book/static/src/changes/changes.xml",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
