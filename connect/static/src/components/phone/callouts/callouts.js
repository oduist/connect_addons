/** @odoo-module **/

import {useService} from "@web/core/utils/hooks"
import {Component, useState, useRef, onWillStart} from "@odoo/owl"
import {Dropdown} from "@web/core/dropdown/dropdown"
import {DropdownItem} from "@web/core/dropdown/dropdown_item"

export class Callouts extends Component {
    static template = 'connect.callouts'
    static props = {
        bus: Object,
    }
    static components = {Dropdown, DropdownItem}

    constructor() {
        super(...arguments)
        this.bus = this.props.bus
    }

    setup(props) {
        super.setup()
        this.orm = useService('orm')
        this.action = useService('action')
        this.contactInput = useRef('contact-input')
        this.state = useState({
            selectedCallout: null,
            callouts: [],
            isCalloutList: true,
            calloutContacts: [],
            filter: 'queued',
        })

        onWillStart(async () => {
            this.bus.addEventListener('busCalloutsGet', () => this.getCallouts())
        })
    }

    // Callouts
    async getCallouts() {
        this.state.callouts = await this.orm.searchRead('connect.callout', [], ['name', 'status'])
    }

    _onClickCallOut(callout) {
        this.state.selectedCallout = callout
        this.state.isCalloutList = false
        this.getCalloutContacts().then()
    }


    // Callout Contacts
    async getCalloutContacts() {
        const fields = [
            'id',
            'partner',
            'phone_number',
            'status'
        ]
        const domain = [["callout", "=", this.state.selectedCallout.id]]
        if (this.state.filter !== 'all') {
            domain.push(['status', '=', this.state.filter])
        }
        this.state.calloutContacts = await this.orm.searchRead('connect.callout_contact', domain, fields)
    }

    _setFilter(filter) {
        this.state.filter = filter
        this.getCalloutContacts().then()
    }

    _clickCloseCalloutContact() {
        this.state.filter = 'queued'
        this.state.isCalloutList = true
        this.state.selectedCallout = null
        this.state.callout_contacts = []
        this.getCallouts().then()
    }

    _clickCalloutContactsAction() {
        const args = [this.state.selectedCallout.id]
        if (this.state.selectedCallout.status === 'running') {
            this.orm.call("connect.callout", "pause", args, {})
            this.state.selectedCallout.status = "paused"
        } else {
            this.orm.call("connect.callout", "run", args, {})
            this.state.selectedCallout.status = "running"
        }
    }

}