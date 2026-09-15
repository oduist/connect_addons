/** @odoo-module **/

import {useService} from "@web/core/utils/hooks"
import {initialsOf, avatarTone, shortName} from "@connect/js/utils"
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
            this.state.favorites = records.map((favorite) => this._prepare(favorite))
        })
    }

    // Speed dial cells: a face, a name, and the number underneath.
    _prepare(favorite) {
        let title = favorite.name || favorite.phone_number
        let avatar = false
        if (favorite.partner) {
            title = shortName(favorite.partner[1])
            avatar = `/web/image?model=res.partner&field=avatar_128&id=${favorite.partner[0]}`
        } else if (favorite.user) {
            title = favorite.user[1]
            avatar = `/web/image?model=res.users&field=avatar_128&id=${favorite.user[0]}`
        }
        return {
            id: favorite.id,
            title,
            avatar,
            tone: avatarTone(title),
            initials: initialsOf(title),
            phone_number: favorite.phone_number,
        }
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
