/** @odoo-module **/

import {useService} from "@web/core/utils/hooks"
import {Component, useState, onWillStart, onWillDestroy} from "@odoo/owl"
import {user} from "@web/core/user"
import {contactInitial, contactTone} from "@connect/js/utils"

const uid = user.userId

// Call statuses that mean the two ends never spoke. Everything else is
// treated as a connected call and shows its duration.
const UNCONNECTED = ['noanswer', 'busy', 'rejected', 'canceled', 'failed']


/**
 * Recent calls for the softphone, grouped by day.
 *
 * This is the Twilio module's own list rather than the shared
 * `connect.calls` component: the redesigned panel groups by day and folds
 * direction, outcome and duration into a single line, and the shared
 * component is rendered by every other provider's phone, which still uses
 * the older chrome. Keeping a copy here is the same trade ADR-031 makes
 * elsewhere -- a duplicated view in exchange for providers that can move
 * independently.
 */
export class Recents extends Component {
    static template = 'connect.recents'
    static props = {
        bus: Object,
    }

    constructor() {
        super(...arguments)
        this.bus = this.props.bus
    }

    setup() {
        super.setup()
        this.orm = useService('orm')
        this.action = useService('action')
        this.notification = useService('notification')
        this.user = uid
        this.favorites = []
        this.state = useState({
            calls: [],
            query: '',
        })

        // Bound once so they can be taken off again. This component is mounted
        // by t-if, so leaving the Recent tab destroys it -- and a listener left
        // behind on the bus fires into the dead instance the next time the tab
        // is opened, which surfaces as "Component is destroyed" from its orm
        // call. Registered here rather than in onWillStart so that a component
        // which never finishes starting still has something to remove.
        this._onBusGetCalls = () => this._getCalls()
        this._onBusGetFavorites = () => this._getFavorites()
        this.bus.addEventListener('busCallsGetCalls', this._onBusGetCalls)
        this.bus.addEventListener('busCallsGetFavorites', this._onBusGetFavorites)

        onWillDestroy(() => {
            this.bus.removeEventListener('busCallsGetCalls', this._onBusGetCalls)
            this.bus.removeEventListener('busCallsGetFavorites', this._onBusGetFavorites)
        })

        onWillStart(async () => {
            await this._getFavorites()
            await this._getCalls()
        })
    }

    // ------------------------------------------------------------------ data

    async _getCalls() {
        const domain = ["|", ["caller_user", "=", this.user], ["called_users", "=", this.user]]
        // Ordered by when the call happened, not by id: the list is cut into
        // day groups from create_date, so that has to be the sort key too.
        const records = await this.orm.call(
            "connect.call", "get_widget_calls",
            [domain, 50, 0, 'create_date desc, id desc', ['status', 'duration_human']],
        )
        this.state.calls = records.map((call) => this._present(call))
    }

    async _getFavorites() {
        const favorites = await this.orm.searchRead('connect.favorite', [], ['phone_number'])
        this.favorites = favorites.map((el) => el.phone_number)
        this.state.calls.forEach((call) => {
            call.favorite = this.favorites.includes(call.number)
        })
    }

    /**
     * Fold one ledger row into the single line the list shows: who the call
     * was with, which way it went, whether it connected, and when.
     */
    _present(call) {
        const isIncoming = call.called_users[0] === this.user
        const number = isIncoming ? call.caller : call.called
        const peer = isIncoming
            ? (call.partner || call.caller_user)
            : (call.partner || (call.called_users.length ? call.called_users : false))

        let name = Array.isArray(peer) ? peer[1] : peer
        if (call.partner && name) {
            // Partner display names arrive as "Company, Contact"; the contact
            // is the part that identifies who was actually on the phone.
            const parts = name.split(',')
            name = parts[parts.length - 1].trim()
        }

        // false, not a placeholder image: the template falls back to a
        // coloured initial, because there is no default avatar file to point at.
        let avatar = false
        if (call.partner) {
            avatar = `/web/image?model=res.partner&field=avatar_128&id=${call.partner[0]}`
        } else if (isIncoming && call.caller_user) {
            avatar = `/web/image?model=res.users&field=avatar_128&id=${call.caller_user[0]}`
        } else if (!isIncoming && call.called_users.length) {
            avatar = `/web/image?model=res.users&field=avatar_128&id=${call.called_users[0]}`
        }

        // get_widget_calls returns naive UTC; the list is read in local time.
        const when = new Date(`${call.create_date} UTC`)
        const connected = !UNCONNECTED.includes(call.status)

        // A call can reach the ledger with neither a peer nor a number (a
        // misdialled empty call used to be able to do exactly that). Leave the
        // row readable rather than blank.
        const label = name || number || 'Unknown'
        return {
            id: call.id,
            name: label,
            number,
            avatar,
            initial: contactInitial(label),
            tone: contactTone(label),
            isIncoming,
            connected,
            duration: connected ? call.duration_human : '',
            partnerId: call.partner ? call.partner[0] : false,
            favorite: this.favorites.includes(number),
            dayKey: this._dayKey(when),
            dayLabel: this._dayLabel(when),
            time: when.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}),
        }
    }

    _dayKey(date) {
        return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`
    }

    _dayLabel(date) {
        const today = new Date()
        const yesterday = new Date()
        yesterday.setDate(today.getDate() - 1)
        if (this._dayKey(date) === this._dayKey(today)) return 'Today'
        if (this._dayKey(date) === this._dayKey(yesterday)) return 'Yesterday'
        return date.toLocaleDateString([], {day: 'numeric', month: 'long'})
    }

    /**
     * The visible list, filtered by the search box and cut into day groups.
     * Calls arrive newest first, so the groups come out in that order too.
     */
    get days() {
        const query = this.state.query.trim().toLowerCase()
        const calls = query
            ? this.state.calls.filter((call) =>
                `${call.name} ${call.number}`.toLowerCase().includes(query))
            : this.state.calls

        const days = []
        let current = null
        for (const call of calls) {
            if (!current || current.key !== call.dayKey) {
                current = {key: call.dayKey, label: call.dayLabel, calls: []}
                days.push(current)
            }
            current.calls.push(call)
        }
        return days
    }

    // --------------------------------------------------------------- actions

    _onSearch(ev) {
        this.state.query = ev.target.value
    }

    _onClickCall(call) {
        if (!call.number) return
        this.bus.trigger('busPhoneMakeCall', {phone: call.number})
    }

    _onClickDetail(ev, call) {
        ev.stopPropagation()
        this.action.doAction({
            res_id: call.id,
            res_model: 'connect.call',
            target: 'new',
            type: 'ir.actions.act_window',
            views: [[false, 'form']],
        })
    }

    async _onClickFavorite(ev, call) {
        ev.stopPropagation()
        const existing = await this.orm.search(
            'connect.favorite', [["phone_number", "=", call.number]])
        if (existing.length) {
            await this.orm.unlink('connect.favorite', existing, {})
            this.notification.add('Removed from Favourites', {title: 'Phone', type: 'info'})
        } else {
            const values = {phone_number: call.number}
            if (call.partnerId) {
                values.partner = call.partnerId
            } else {
                values.name = call.number
            }
            await this.orm.create('connect.favorite', [values])
            this.notification.add('Added to Favourites', {title: 'Phone', type: 'info'})
        }
        await this._getFavorites()
        this.bus.trigger('busCallsGetFavorites')
    }
}
