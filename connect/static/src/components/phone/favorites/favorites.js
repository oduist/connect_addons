/** @odoo-module **/

import {useService} from "@web/core/utils/hooks"
import {Component, useState, onWillStart} from "@odoo/owl"
import {user} from "@web/core/user"

const uid = user.userId

export class Favorites extends Component {
    static template = 'connect.favorites'
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
        this.user = uid
        this.state = useState({
            favorites: [],
        })

        onWillStart(async () => {
            this.getFavorites()
        })
    }

    getFavorites() {
        const fields = [
            "id",
            "name",
            "partner",
            "user",
            "phone_number",
        ]

        this.orm.searchRead("connect.favorite", [], fields, {limit: 30}).then((records) => {
            this.state.favorites = records
        })
    }

    _onClickContactCall(phone_number) {
        this.bus.trigger('busPhoneMakeCall', {phone: phone_number})
    }

    _onClickRemoveFavorite(ev, id) {
        ev.stopPropagation()
        this.orm.unlink("connect.favorite", [id], {}).then(() => {
            this.getFavorites()
            this.bus.trigger('busCallsGetFavorites')
        })

    }
}
