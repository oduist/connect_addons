/** @odoo-module **/

import {useService} from "@web/core/utils/hooks"
import {setFocus} from "@connect/js/utils"
import {Component, useState, useRef, useEffect, onWillStart} from "@odoo/owl"

const searching = {
    all: 'all',
    extensions: 'extensions',
    partners: 'partners',
}

export class Contacts extends Component {
    static template = 'connect.contacts'
    static props = {
        bus: Object,
        isContact: {type: Boolean, optional: true},
        isForward: {type: Boolean, optional: true},
        contactSearch: {type: String, optional: true},
    }

    constructor() {
        super(...arguments)
        const {bus, isForward = false, isContact = false, contactSearch = 'all'} = this.props
        this.bus = bus
        this.isForward = isForward
        this.isContact = isContact
        this.contactSearch = contactSearch
        this.users = []
    }

    setup(props) {
        super.setup()
        this.orm = useService('orm')
        this.action = useService('action')
        this.contactInput = useRef('contact-input')
        this.state = useState({
            isContactMode: false,
            partners: [],
            users: this.users,
            // Kept in state, not on the instance: the results header and the
            // empty text are rendered from it.
            searchQuery: '',
        })

        // Focus the search box as soon as it exists, not when the mode is
        // set. The input is behind a t-if, so at the moment _onClickForward
        // announces the mode over the bus there is nothing in the DOM to
        // focus yet; this runs after the patch that puts it there.
        useEffect(
            (isContactMode) => {
                if (isContactMode && this.contactInput.el) {
                    this.contactInput.el.focus()
                }
            },
            () => [this.state.isContactMode],
        )

        onWillStart(async () => {
            this.bus.addEventListener('busContactSetState', ({detail}) => this._busContactSetState(detail))
            this.bus.addEventListener('busContactSearchQuery', ({detail}) => this._busContactSearchQuery(detail))
        })
    }

    get searchQuery() {
        return this.state.searchQuery
    }

    /** What clicking a result does, in the words of the mode we are in. */
    get actionLabel() {
        return this.isForward ? 'Forward to' : 'Call'
    }

    /**
     * The number to dial for a partner. phone_sanitized is empty whenever a
     * number could not be normalised (no country to resolve it against), and
     * a contact you can see but cannot call is worse than an unformatted one.
     */
    partnerNumber(partner) {
        return partner.phone_sanitized || partner.phone || partner.mobile || ''
    }

    /**
     * Split `text` around the current query so the template can wrap the
     * matching run in <mark> without ever injecting raw HTML.
     */
    highlight(text) {
        const query = this.state.searchQuery.trim()
        if (!query || !text) return [{text: text || '', match: false}]
        const at = text.toLowerCase().indexOf(query.toLowerCase())
        if (at === -1) return [{text, match: false}]
        return [
            {text: text.slice(0, at), match: false},
            {text: text.slice(at, at + query.length), match: true},
            {text: text.slice(at + query.length), match: false},
        ].filter((part) => part.text)
    }

    _busContactSetState({isForward = false, isContact = false, isContactMode = false}) {
        this.state.isContactMode = isContactMode
        this.isContact = isContact
        this.isForward = isForward
        this.state.partners = []
        this.state.users = []
        this.state.searchQuery = ''
        if (this.contactInput.el) {
            this.contactInput.el.value = ''
        }
    }

    _busContactSearchQuery({searchQuery = ''}) {
        this._contactSearchQuery({searchQuery})
    }

    _onSearchContact(ev) {
        if (ev.key === "Enter") {
            this._contactCall()
        } else {
            this._contactSearchQuery({searchQuery: ev.target.value})
        }
    }

    _onClickClearSearchContact(ev) {
        this._contactSearchQuery({searchQuery: ''})
        if (this.contactInput.el) {
            this.contactInput.el.value = ''
            setFocus(this.contactInput.el)
        }
    }

    _contactSearchQuery({searchQuery = ''}) {
        this.state.searchQuery = searchQuery
        this.searchUser()
        this.searchPartner()
    }

    _contactCall() {
        let phoneNumber
        if (this.state.partners.length + this.state.users.length === 1) {
            if (this.state.partners.length) {
                phoneNumber = this.partnerNumber(this.state.partners[0])
            } else {
                // search_directory returns exten_number; `exten` never
                // existed on this payload, so Enter on a single colleague
                // match used to dial nothing at all.
                phoneNumber = this.state.users[0].exten_number
            }
        } else {
            phoneNumber = this.state.searchQuery
        }
        this._onClickContact(phoneNumber)
    }

    /** One entry point for a picked result; the mode decides what it means. */
    _onClickContact(phoneNumber) {
        if (!phoneNumber) return
        if (this.isForward) {
            this._onClickMakeForward(phoneNumber)
        } else {
            this._onClickMakeCall(phoneNumber)
        }
    }

    searchPartner() {
        if (this.contactSearch !== searching.all && this.contactSearch !== searching.partners) return
        const self = this
        const query = self.state.searchQuery
        if (query) {
            self.orm.searchRead(
                "res.partner",
                [
                    // OR: a query is either part of a number or part of a name,
                    // never both at once.
                    '|', ['phone_mobile_search', '=ilike', `%${query}%`],
                    ['name', '=ilike', `%${query}%`],
                ],
                ['id', 'name', 'email', 'phone_sanitized', 'phone', 'mobile'],
                {order: 'name asc', limit: 10}
            ).then((records) => {
                self.state.partners = records
            })
        } else {
            self.state.partners = []
        }
    }

    searchUser() {
        if (this.contactSearch !== searching.all && this.contactSearch !== searching.extensions) return
        const self = this
        const query = self.state.searchQuery
        if (query) {
            // Not a searchRead: the connect.user record rule limits a Connect
            // user to their own record, so a direct search only ever finds
            // themselves. search_directory hands back name + extension for
            // everyone, and nothing else off the model.
            self.orm.call("connect.user", "search_directory", [query, 10]).then((records) => {
                self.state.users = records
            })
        } else {
            self.state.users = []
        }
    }

    _onClickMakeCall(phoneNumber) {
        this.bus.trigger('busPhoneMakeCall', {phone: phoneNumber})
    }

    _onClickMakeForward(phoneNumber) {
        // Sent whole: forwarding is a REST redirect now, not a DTMF sequence
        // that could not carry a '+', and an external destination has to stay
        // in E.164 to be recognised as one.
        this.bus.trigger('busPhoneMakeForward', phoneNumber)
    }

    _onClickOpenPartner(ev, id) {
        ev.stopPropagation()
        this._openPartner(id)
    }

    _openPartner(id) {
        this.action.doAction({
            res_id: id,
            res_model: "res.partner",
            target: 'new',
            type: 'ir.actions.act_window',
            views: [[false, 'form']],
        })
    }
}
