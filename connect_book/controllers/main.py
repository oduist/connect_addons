# -*- coding: utf-8 -*-
from odoo import http, release
from odoo.http import request

route_type = "json" if release.version_info[0] < 19.0 else 'jsonrpc'


class ConnectBookController(http.Controller):
    """Thin JSON wrapper over the ``connect.book`` model for the client actions."""

    @http.route("/connect_book/book", type=route_type, auth="user")
    def book(self):
        return request.env["connect.book"].get_book()

    @http.route("/connect_book/admin", type=route_type, auth="user")
    def admin_book(self):
        # get_admin_book enforces the system-admin group itself.
        return request.env["connect.book"].get_admin_book()

    @http.route("/connect_book/changes", type=route_type, auth="user")
    def changes(self):
        return request.env["connect.book"].get_changes()
