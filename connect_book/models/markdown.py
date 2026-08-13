# -*- coding: utf-8 -*-
"""Minimal, dependency-free Markdown -> HTML renderer.

Covers the subset of GitHub Flavored Markdown that is enough for the user
documentation: headings, paragraphs, lists (including nested ones), code
blocks, blockquotes, tables, horizontal rules and inline formatting (bold,
italic, code, links, images).

Implemented "from scratch" so that the Book works in any Odoo image without
installing extra packages. All text is escaped, so no raw markup from the
source files ends up in the HTML.
"""
import re

from markupsafe import escape

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_HR_RE = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")
_UL_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_OL_RE = re.compile(r"^(\s*)\d+[.)]\s+(.*)$")
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})\s*([\w+#.-]*)\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)+\|?\s*$")

#: Only these URL schemes may appear in rendered links/images. A URL that
#: carries any other explicit scheme (``javascript:``, ``data:``, ``vbscript:``…)
#: is neutralised to ``#`` so untrusted documentation cannot smuggle script.
#: Scheme-relative and relative URLs (no scheme) are allowed.
_URL_SCHEME_RE = re.compile(r"^\s*([a-z][a-z0-9+.\-]*):", re.I)
_SAFE_URL_SCHEMES = frozenset({"http", "https", "mailto"})

#: Cap on nested-list recursion, a backstop against pathological/deep input
#: overflowing the Python stack. Real documentation never nests this deep.
_MAX_LIST_DEPTH = 12


def _safe_url(url):
    """Return ``url`` if its scheme is safe (or it has none), else ``"#"``."""
    match = _URL_SCHEME_RE.match(url)
    if match and match.group(1).lower() not in _SAFE_URL_SCHEMES:
        return "#"
    return url


def md_to_html(text):
    """Convert a Markdown string into an HTML string."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    out = []
    para = []
    i, n = 0, len(lines)

    def flush_para():
        if para:
            joined = " ".join(line.strip() for line in para)
            out.append("<p>%s</p>" % _inline(joined))
            para.clear()

    while i < n:
        line = lines[i]

        fence = _FENCE_RE.match(line)
        if fence:
            flush_para()
            block, i = _consume_fence(lines, i, n, fence)
            out.append(block)
            continue

        if not line.strip():
            flush_para()
            i += 1
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            flush_para()
            level = len(heading.group(1))
            raw = heading.group(2)
            out.append('<h%d id="%s">%s</h%d>' % (level, _slug(raw), _inline(raw), level))
            i += 1
            continue

        if _HR_RE.match(line):
            flush_para()
            out.append("<hr/>")
            i += 1
            continue

        if "|" in line and i + 1 < n and _TABLE_SEP_RE.match(lines[i + 1]):
            flush_para()
            block, i = _consume_table(lines, i, n)
            out.append(block)
            continue

        if line.lstrip().startswith(">"):
            flush_para()
            block, i = _consume_quote(lines, i, n)
            out.append(block)
            continue

        if _UL_RE.match(line) or _OL_RE.match(line):
            flush_para()
            block, i = _consume_list(lines, i, n)
            out.append(block)
            continue

        para.append(line)
        i += 1

    flush_para()
    return "\n".join(out)


def _consume_fence(lines, i, n, fence):
    marker = fence.group(1)[0]
    lang = fence.group(2)
    closing = re.compile(r"^\s*%s{3,}\s*$" % re.escape(marker))
    body = []
    i += 1
    while i < n and not closing.match(lines[i]):
        body.append(lines[i])
        i += 1
    i += 1  # skip the closing fence
    cls = ' class="language-%s"' % lang if lang else ""
    code = _render_diff(body) if lang == "diff" else str(escape("\n".join(body)))
    return "<pre><code%s>%s</code></pre>" % (cls, code), i


def _render_diff(body):
    """Render a ``diff`` fenced block: colour added/removed lines.

    Added lines (``+``) and removed lines (``-``) are wrapped in spans so the
    documentation-change archive shows green/red diffs. Everything is escaped.
    """
    rendered = []
    for line in body:
        cell = str(escape(line))
        if line[:1] == "+":
            rendered.append('<span class="o_diff_add">%s</span>' % cell)
        elif line[:1] == "-":
            rendered.append('<span class="o_diff_del">%s</span>' % cell)
        else:
            rendered.append(cell)
    return "\n".join(rendered)


def _consume_quote(lines, i, n):
    quoted = []
    while i < n and lines[i].lstrip().startswith(">"):
        quoted.append(re.sub(r"^\s*>\s?", "", lines[i]))
        i += 1
    return "<blockquote>%s</blockquote>" % md_to_html("\n".join(quoted)), i


def _consume_table(lines, i, n):
    header = _split_row(lines[i])
    i += 2  # header row + separator row
    rows = []
    while i < n and lines[i].strip() and "|" in lines[i]:
        rows.append(_split_row(lines[i]))
        i += 1
    html = ["<table><thead><tr>"]
    html += ["<th>%s</th>" % _inline(cell) for cell in header]
    html.append("</tr></thead><tbody>")
    for row in rows:
        html.append("<tr>")
        html += ["<td>%s</td>" % _inline(cell) for cell in row]
        html.append("</tr>")
    html.append("</tbody></table>")
    return "".join(html), i


def _split_row(row):
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [cell.strip() for cell in row.split("|")]


def _consume_list(lines, i, n):
    items = []
    while i < n:
        m_ul = _UL_RE.match(lines[i])
        m_ol = _OL_RE.match(lines[i])
        if m_ul:
            indent = len(m_ul.group(1).replace("\t", "    "))
            items.append((indent, False, m_ul.group(2)))
            i += 1
        elif m_ol:
            indent = len(m_ol.group(1).replace("\t", "    "))
            items.append((indent, True, m_ol.group(2)))
            i += 1
        elif items and lines[i][:1] in (" ", "\t") and lines[i].strip():
            # "Lazy continuation": an indented line without a marker is a
            # wrapped continuation of the previous item's text (nested lists
            # are already caught by the branches above, since their line
            # contains a marker).
            indent, ordered, content = items[-1]
            items[-1] = (indent, ordered, "%s %s" % (content, lines[i].strip()))
            i += 1
        else:
            break
    if not items:
        return "", i
    html, _ = _render_list(items, 0, items[0][0])
    return html, i


def _render_list(items, pos, base_indent, depth=0):
    ordered = items[pos][1]
    tag = "ol" if ordered else "ul"
    html = ["<%s>" % tag]
    while pos < len(items):
        indent, is_ordered, content = items[pos]
        if indent < base_indent:
            break
        if indent > base_indent:
            if depth >= _MAX_LIST_DEPTH:
                # Too deep: render as a flat item instead of recursing further.
                html.append("<li>%s</li>" % _inline(content))
                pos += 1
                continue
            sub_html, pos = _render_list(items, pos, indent, depth + 1)
            if len(html) > 1 and html[-1].endswith("</li>"):
                html[-1] = html[-1][:-len("</li>")] + sub_html + "</li>"
            else:
                html.append("<li>%s</li>" % sub_html)
            continue
        if is_ordered != ordered:
            break
        html.append("<li>%s</li>" % _inline(content))
        pos += 1
    html.append("</%s>" % tag)
    return "".join(html), pos


def _inline(text):
    """Inline formatting. Escapes the text and inserts safe HTML."""
    codes = []

    def _stash(match):
        codes.append(str(escape(match.group(1))))
        return "\x00%d\x00" % (len(codes) - 1)

    # First stash the inline code so its contents are not formatted.
    text = re.sub(r"`([^`]+)`", _stash, text)
    text = str(escape(text))
    # URLs are already HTML-escaped here; still validate their scheme so a
    # javascript:/data: link cannot execute when the HTML is injected via markup().
    text = re.sub(
        r"!\[([^\]]*)\]\(([^)\s]+)\)",
        lambda m: '<img src="%s" alt="%s"/>' % (_safe_url(m.group(2)), m.group(1)),
        text,
    )
    text = re.sub(
        r"\[([^\]]+)\]\(([^)\s]+)\)",
        lambda m: '<a href="%s" target="_blank" rel="noreferrer noopener">%s</a>'
        % (_safe_url(m.group(2)), m.group(1)),
        text,
    )
    # Handle bold before italic; leave underscores alone so we don't break
    # technical identifiers like res_partner or connect_book.
    text = re.sub(r"\*\*([^*]+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*([^*]+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: "<code>%s</code>" % codes[int(m.group(1))], text)
    return text


def _slug(text):
    s = re.sub(r"<[^>]+>", "", text)
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE).strip().lower()
    return re.sub(r"[\s_]+", "-", s)
