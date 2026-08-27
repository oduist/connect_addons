/** @odoo-module **/

import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { Component, useState, onWillStart, markup } from "@odoo/owl";

const MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
];
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/**
 * The "Changes" client action: a day-by-day documentation-change archive.
 * On the left -- the timeline of days grouped by month (like a blog archive),
 * on the right -- every module's documented change for the selected day.
 */
export class ChangesApp extends Component {
    static template = "connect_book.ChangesApp";
    static props = { "*": true };

    setup() {
        this.state = useState({
            days: [],
            activeDate: null,
            loaded: false,
        });

        onWillStart(async () => {
            const data = await rpc("/connect_book/changes");
            this.state.days = data.days || [];
            this.state.loaded = true;
            if (this.state.days.length) {
                this.state.activeDate = this.state.days[0].date;
            }
        });
    }

    /** Group the (already date-descending) days under "Month Year" headers. */
    get archive() {
        const groups = [];
        let current = null;
        for (const day of this.state.days) {
            const key = day.date.slice(0, 7);
            if (!current || current.key !== key) {
                current = { key, label: this.formatMonth(key), days: [] };
                groups.push(current);
            }
            current.days.push({ ...day, label: this.formatDayShort(day.date) });
        }
        return groups;
    }

    get activeDay() {
        const day = this.state.days.find((d) => d.date === this.state.activeDate);
        if (!day) {
            return null;
        }
        return {
            ...day,
            label: this.formatDayFull(day.date),
            entries: day.entries.map((e) => ({ ...e, body: markup(e.html) })),
        };
    }

    selectDay(date) {
        this.state.activeDate = date;
    }

    formatMonth(key) {
        const [year, month] = key.split("-").map(Number);
        return `${MONTHS[month - 1]} ${year}`;
    }

    formatDayShort(date) {
        const [year, month, day] = date.split("-").map(Number);
        const weekday = WEEKDAYS[new Date(year, month - 1, day).getDay()];
        return `${weekday}, ${day}`;
    }

    formatDayFull(date) {
        const [year, month, day] = date.split("-").map(Number);
        return `${day} ${MONTHS[month - 1]} ${year}`;
    }
}

registry.category("actions").add("connect_book.changes", ChangesApp);
