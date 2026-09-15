/** @odoo-module **/

import {useService} from "@web/core/utils/hooks"
import {initialsOf, avatarTone, shortName} from "@connect/js/utils"
import {Component, useState, onWillStart} from "@odoo/owl"
import {user} from "@web/core/user"

const uid = user.userId

// A call that did not connect. Outgoing ones read as "failed", incoming ones as
// "missed": same statuses, different story.
const UNANSWERED = ['no-answer', 'busy', 'failed', 'canceled']

const CALL_FIELDS = [
    "id",
    "duration_human",
    "called",
    "caller",
    "caller_user",
    "called_users",
    "partner",
    "direction",
    "status",
    "create_date",
]

// Everything the row needs to draw itself, worked out once here rather than in
// the template.
function prepareCall(call, me) {
    const isIncoming = call.called_users[0] === me
    const number = isIncoming ? call.caller : call.called
    const peerUser = isIncoming
        ? call.caller_user
        : (call.called_users.length ? call.called_users : false)

    let title = number
    let avatar = false
    if (call.partner) {
        title = shortName(call.partner[1])
        avatar = `/web/image?model=res.partner&field=avatar_128&id=${call.partner[0]}`
    } else if (peerUser) {
        title = peerUser[1]
        avatar = `/web/image?model=res.users&field=avatar_128&id=${peerUser[0]}`
    }

    const answered = !UNANSWERED.includes(call.status)
    // Naive datetimes come back in UTC.
    const when = new Date(`${call.create_date}Z`)

    return {
        id: call.id,
        number,
        title: title || number,
        avatar,
        tone: avatarTone(title || number),
        initials: initialsOf(title || number),
        kind: answered ? (isIncoming ? 'in' : 'out') : (isIncoming ? 'miss' : 'fail'),
        label: answered ? (isIncoming ? 'Incoming' : 'Outgoing') : (isIncoming ? 'Missed' : 'Failed'),
        duration: answered ? call.duration_human : '',
        time: when.toLocaleTimeString(undefined, {hour: '2-digit', minute: '2-digit'}),
        when,
        favorite: false,
        raw: call,
    }
}

// Today, Yesterday, then the date itself.
function dayLabel(date) {
    const midnight = new Date()
    midnight.setHours(0, 0, 0, 0)
    const day = 24 * 60 * 60 * 1000
    if (date >= midnight) return 'Today'
    if (date >= new Date(midnight.getTime() - day)) return 'Yesterday'
    return date.toLocaleDateString(undefined, {day: 'numeric', month: 'short'})
}

class CallDetail extends Component {
    static template = 'connect.call_detail'
    static props = {
        call: Object
    }

    constructor() {
        super(...arguments)
        this.user = uid
        this.state = useState({
            call: this.props.call,
        })
    }

    setup() {
        super.setup()
        this.orm = useService('orm')
        this.action = useService('action')

        onWillStart(async () => {
            this.getCall(this.state.call.id)
        })
    }

    async getCall(id) {
        const [call] = await this.orm.searchRead("connect.call", [["id", "=", id]], CALL_FIELDS)
        if (call) {
            this.record = call
            this.state.call = prepareCall(call, this.user)
        }
    }

    get isColleague() {
        const call = this.record
        return call && call.called_users.length > 0 && call.caller_user
    }

    async _createPartner() {
        const phone = this.state.call.number
        let context = {
            connect_call_id: this.state.call.id,
            default_phone: phone,
            default_name: `Partner ${phone}`
        }
        this.action.doAction({
            context,
            res_model: 'res.partner',
            target: 'new',
            type: 'ir.actions.act_window',
            views: [[false, 'form']],
        })
    }

    async _openPartner() {
        await this.getCall(this.state.call.id)
        if (this.record && this.record.partner) {
            this.action.doAction({
                res_id: this.record.partner[0],
                res_model: "res.partner",
                target: 'new',
                type: 'ir.actions.act_window',
                views: [[false, 'form']],
            })
        }
    }

    _OpenInCallHistory() {
        this.action.doAction({
            res_id: this.state.call.id,
            res_model: 'connect.call',
            target: 'new',
            type: 'ir.actions.act_window',
            views: [[false, 'form']],
        })
    }
}

export class Calls extends Component {
    static template = 'connect.calls'
    static props = {
        bus: Object,
    }
    static components = {CallDetail}

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
        this.calls = []
        this.state = useState({
            groups: [],
            call: null,
        })

        onWillStart(async () => {
            this.bus.addEventListener('busCallsGetCalls', (ev) => this._getCalls(ev))
            this.bus.addEventListener('busCallsGetFavorites', (ev) => this._getFavorites(ev))
            this._getFavorites()
        })
    }

    async _getCalls() {
        const domain = ["|", ["caller_user", "=", this.user], ["called_users", "=", this.user]]
        const records = await this.orm.call(
            "connect.call", "get_widget_calls", [domain, 20], {fields: ["duration_human"]})
        this.calls = records
            .map((record) => prepareCall(record, this.user))
            .sort((a, b) => b.when - a.when)
        this._markFavorites()
    }

    // The history reads as a diary: one heading per day, calls under it.
    _group() {
        const groups = []
        for (const call of this.calls) {
            const label = dayLabel(call.when)
            const last = groups[groups.length - 1]
            if (last && last.label === label) {
                last.calls.push(call)
            } else {
                groups.push({label, calls: [call]})
            }
        }
        this.state.groups = groups
    }

    // Regroups as well: the rows live behind the reactive state, so they are
    // rebuilt rather than poked at in place.
    _markFavorites() {
        this.calls.forEach((call) => call.favorite = this.favorites.includes(call.number))
        this._group()
    }

    async _getFavorites() {
        this.favorites = []
        const favorites = await this.orm.searchRead('connect.favorite', [], ['phone_number'])
        favorites.forEach((el) => this.favorites.push(el.phone_number))
        this._markFavorites()
    }

    _onClickContactCall(phoneNumber) {
        this.bus.trigger('busPhoneMakeCall', {phone: phoneNumber})
    }

    async _onClickFavorite(ev, call) {
        ev.stopPropagation()
        const record = call.raw
        const kwargs = {phone_number: call.number}
        const isCalled = record.called_users[0] === this.user
        if (record.partner) {
            kwargs.partner = record.partner[0]
        } else if (record.caller_user && isCalled) {
            kwargs.user = record.caller_user[0]
        } else if (record.called_users.length > 0 && !isCalled) {
            kwargs.user = record.called_users[0]
        } else {
            kwargs.name = kwargs.phone_number
        }

        const domain = [["phone_number", "=", kwargs.phone_number]]
        const getFavorite = await this.orm.search('connect.favorite', domain)

        if (getFavorite.length === 0) {
            await this.orm.create('connect.favorite', [kwargs])
            await this._getFavorites()
            this.notification.add('Added to Favorite!', {title: 'Phone', type: 'info'})
        } else {
            await this.orm.unlink("connect.favorite", getFavorite, {})
            await this._getFavorites()
            this.notification.add('Removed from Favorite!', {title: 'Phone', type: 'info'})
        }
    }

    _open_detail(ev, call) {
        ev.stopPropagation()
        this.state.call = call
    }

    _close_call_detail() {
        this.state.call = null
        this._getCalls()
    }
}
