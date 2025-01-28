/** @odoo-module **/

import {useService} from "@web/core/utils/hooks"
import {Component, useState, onWillStart} from "@odoo/owl"
import {user} from "@web/core/user"

const uid = user.userId

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
        const fields = [
            "id",
            "duration_human",
            "called",
            "caller",
            "caller_user",
            "called_users",
            "partner",
            "direction",
            "create_date"
        ]
        const [call] = await this.orm.searchRead("connect.call", [["id", "=", id]], fields)
        this.state.call = call
    }

    async _createOpenPartner() {
        await this.getCall(this.state.call.id)
        if (this.state.call.partner) {
            this.action.doAction({
                res_id: this.state.call.partner[0],
                res_model: "res.partner",
                target: 'new',
                type: 'ir.actions.act_window',
                views: [[false, 'form']],
            })
        } else {
            const phone = this.state.call.called_users[0] === this.user ?
                this.state.call.caller : this.state.call.called
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
        this.state = useState({
            calls: [],
            call: null,
        })

        onWillStart(async () => {
            this.bus.addEventListener('busCallsGetCalls', (ev) => this._getCalls(ev))
            this.bus.addEventListener('busCallsGetFavorites', (ev) => this._getFavorites(ev))
            this._getFavorites()
        })
    }

    async _getCalls() {
        this.state.calls = []
        const domain = ["|", ["caller_user", "=", this.user], ["called_users", "=", this.user]]
        const records = await this.orm.call("connect.call", "get_widget_calls", [domain, 20])
        for (const item of records) {
            const call_number = item.called_users[0] === this.user ? item.caller : item.called
            item.favorite = this.favorites.includes(call_number)
            const local_time = new Date(`${item.create_date} UTC`).toLocaleTimeString("en-GB")
            item.create_date = `${item.create_date.split(' ')[0]} ${local_time}`
        }
        this.state.calls = records

    }

    async _getFavorites() {
        this.favorites = []
        const favorites = await this.orm.searchRead('connect.favorite', [], ['phone_number'])
        favorites.forEach((el) => this.favorites.push(el.phone_number))
        this.state.calls.forEach(item => {
            const call_number = item.called_users[0] === this.user ? item.caller : item.called
            item.favorite = this.favorites.includes(call_number)
        })
    }

    _onClickContactCall(phoneNumber) {
        this.bus.trigger('busPhoneMakeCall', {phone: phoneNumber})
    }

    async _onClickFavorite(call) {
        const kwargs = {}
        const isCalled = call.called_users[0] === this.user
        kwargs.phone_number = isCalled ? call.caller : call.called
        if (call.partner) {
            kwargs.partner = call.partner[0]
        } else {
            if (call.caller_user && isCalled) {
                kwargs.user = call.caller_user[0]
            } else if (call.called_users.length > 0 && !isCalled) {
                kwargs.user = call.called_users[0]
            } else {
                kwargs.name = kwargs.phone_number
            }
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

    _open_detail(call) {
        this.state.call = call
    }

    _close_call_detail() {
        this.state.call = null
        this._getCalls()
    }
}
