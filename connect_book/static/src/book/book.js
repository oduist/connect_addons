/** @odoo-module **/

import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { Component, useState, onWillStart, markup } from "@odoo/owl";

/**
 * The "Book" client action: a two-pane documentation viewer.
 * On the left -- a searchable list of modules (one guide per module),
 * on the right -- the text of the selected guide.
 */
export class BookApp extends Component {
    static template = "connect_book.BookApp";
    static props = { "*": true };
    //: JSON endpoint the book pulls its pages from. Subclasses override it
    //  (e.g. the Adminbook reads /connect_book/admin) -- everything else is shared.
    static endpoint = "/connect_book/book";

    setup() {
        this.state = useState({
            pages: [],
            activeId: null,
            search: "",
            loaded: false,
        });

        onWillStart(async () => {
            const data = await rpc(this.constructor.endpoint);
            this.state.pages = data.pages || [];
            this.state.loaded = true;
            if (this.state.pages.length) {
                this.state.activeId = this.state.pages[0].id;
            }
        });
    }

    get filteredPages() {
        const query = this.state.search.trim().toLowerCase();
        if (!query) {
            return this.state.pages;
        }
        return this.state.pages.filter((page) =>
            page.title.toLowerCase().includes(query)
        );
    }

    get activePage() {
        const page = this.state.pages.find((p) => p.id === this.state.activeId);
        return page ? { ...page, body: markup(page.html) } : null;
    }

    selectPage(id) {
        this.state.activeId = id;
    }

    onSearch(ev) {
        this.state.search = ev.target.value;
    }
}

registry.category("actions").add("connect_book.book", BookApp);
