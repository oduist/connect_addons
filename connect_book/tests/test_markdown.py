# -*- coding: utf-8 -*-
from odoo.tests.common import BaseCase
from odoo.tests import tagged

from odoo.addons.connect_book.models.markdown import md_to_html


@tagged("post_install", "-at_install", "connect_book")
class TestMarkdown(BaseCase):
    def test_heading_and_paragraph(self):
        html = md_to_html("# Title\n\nHello world\n")
        self.assertIn('<h1 id="title">Title</h1>', html)
        self.assertIn("<p>Hello world</p>", html)

    def test_unordered_list(self):
        html = md_to_html("- one\n- two\n")
        self.assertIn("<ul>", html)
        self.assertEqual(html.count("<li>"), 2)

    def test_fenced_code_block_is_not_interpreted(self):
        html = md_to_html("```python\n# not a heading\n```\n")
        self.assertIn("<pre>", html)
        self.assertNotIn("<h1>", html)

    def test_table(self):
        html = md_to_html("| a | b |\n| --- | --- |\n| 1 | 2 |\n")
        self.assertIn("<table>", html)
        self.assertIn("<th>", html)

    def test_html_is_escaped(self):
        html = md_to_html("<script>alert(1)</script>\n")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_javascript_url_is_neutralised(self):
        html = md_to_html("[click](javascript:alert(1))\n")
        self.assertNotIn("javascript:", html)
        self.assertIn('href="#"', html)

    def test_https_url_is_kept(self):
        html = md_to_html("[docs](https://oduist.com/docs)\n")
        self.assertIn('href="https://oduist.com/docs"', html)
