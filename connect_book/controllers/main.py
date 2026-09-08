# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request


class ConnectBookController(http.Controller):
    """Thin JSON wrapper over the ``connect.book`` model for the client actions."""

    @http.route("/connect_book/book", type="jsonrpc", auth="user")
    def book(self):
        return request.env["connect.book"].get_book()

    @http.route("/connect_book/admin", type="jsonrpc", auth="user")
    def admin_book(self):
        # get_admin_book enforces the system-admin group itself.
        return request.env["connect.book"].get_admin_book()

    @http.route("/connect_book/changes", type="jsonrpc", auth="user")
    def changes(self):
        return request.env["connect.book"].get_changes()
