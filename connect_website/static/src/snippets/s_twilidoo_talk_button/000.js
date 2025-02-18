/** @odoo-module **/

import publicWidget from "web.public.widget"
import {loadJS} from "@web/core/assets"
import {session} from "@web/session"


const ConnectTalkButtonWidget = publicWidget.Widget.extend({
    selector: '.s_connect_talk',
    disabledInEditableMode: true,

    events: Object.assign({}, publicWidget.Widget.prototype.events, {
        'click .s_talk_button': '_clickTalkButton',
        'click .answer-call': '_clickAnswerCall',
        'click .reject-call': '_clickRejectCall',
    }),

    init() {
        this._super(...arguments)
    },

    /**
     * @override
     */
    async start() {
        await this._super(...arguments)
        this._$talkButton = this.$('.s_talk_button')
        this._$talkButtonText = this.$('.s_talk_button').html()
        this._$incomingCall = this.$('.s_incoming_call')
        this.enabled = false
        this.inCall = false
        this.userAgent = null
        this.identity = null
        this.number = null
        this.session = null
        const {enabled, number} = await this.getConfig()
        if (enabled && number) {
            this.enabled = true
            this.number = number
        }
        if (this.checkIdentity()) {
            await this.initUserAgent()
        }

    },

    initUserAgent: async function () {
        await loadJS('/connect_website/static/src/snippets/s_connect_talk_button/twilio.min.js')

        this.identity = this.getIdentity()
        const token = await this.getToken()

        // User Agent
        this.userAgent = new Twilio.Device(token, {
            logLevel: 5,
            codecPreferences: ["opus", "pcmu"]
        })

        const self = this
        this.userAgent.on('error', async (error) => {
            if (error.name === 'AccessTokenExpired') {
                await self.updateToken()
            }
        })

        this.userAgent.on('tokenWillExpire', () => {
            self.updateToken().then()
        })

        // HANDLE RTCSession
        this.userAgent.on("incoming", async function (session) {
            if (self.session === null) {
                self.session = session
            } else {
                session.reject()
                return
            }

            self._$incomingCall.removeClass('hide')
            self._$talkButton.text('')

            // incoming call here
            session.on("accept", async function (data) {
                self.startCall()
            })
            session.on("disconnect", async function (data) {
                self.endCall()
                self.session = null
            })
            session.on("cancel", async function (data) {
                self.session = null
                self.endCall()
            })
            session.on("reject", async function (data) {
                self.session = null
                self.endCall()
            })
        })
        this.userAgent.register()
    },

    updateToken: async function () {
        const token = await this.getToken()
        this.userAgent.updateToken(token)
    },

    makeCall: async function () {
        if (!this.enabled) {
            const message = "Configure the button in the Connect Settings!"
            this.displayNotification({message: message, type: 'info', sticky: false})
            return
        }

        if (!this.checkIdentity()) {
            await this.initUserAgent()
        }

        const self = this
        self.inCall = true
        const params = {
            To: self.number,
            Called: self.number,
            Source: 'website',
            UserId: session.user_id
        }
        self.session = await self.userAgent.connect({params})

        self.startCall()

        self.session.on("disconnect", async function () {
            self.endCall()
            self.session = null
        })

        self.session.on("cancel", async function () {
            self.endCall()
            self.session = null
        })
    },

    startCall: function () {
        this.inCall = true
        this._$incomingCall.addClass('hide')
        this.$el.addClass('red')
        this._$talkButton.html('<i class="fa fa-phone"/>')
    },

    endCall: function () {
        this.inCall = false
        this._$incomingCall.addClass('hide')
        this.$el.removeClass('red')
        this._$talkButton.html(this._$talkButtonText)
    },

    getConfig: async function () {
        return await this._rpc({'route': '/get_connect_website_config'})
    },

    getToken: async function () {
        return await this._rpc({'route': "/get_connect_website_button_token", params: {identity: this.identity}})
    },

    generateIdentity: function () {
        return `${Math.floor(Math.random() * (99999999 - 10000000) + 10000000)}`
    },

    checkIdentity: function () {
        return localStorage.getItem('connect_website_button_identity') || false
    },

    getIdentity: function () {
        let identity = this.checkIdentity()
        if (!identity) {
            identity = this.generateIdentity()
            this.setIdentity(identity)
        }
        return identity
    },

    setIdentity: function setIdentity(param) {
        localStorage.setItem('connect_website_button_identity', param)
    },

    _clickTalkButton: function (ev) {
        if (this.inCall) {
            if (this.session) {
                this.session.disconnect()
            }
        } else {
            this.makeCall().then()
        }
    },

    _clickAnswerCall: function (ev) {
        this.startCall()
        if (this.session) {
            this.session.accept()
        }
    },

    _clickRejectCall: function (ev) {
        this.endCall()
        if (this.session) {
            this.session.reject()
        }
    },

})

publicWidget.registry.connectTalkButton = ConnectTalkButtonWidget

export default ConnectTalkButtonWidget
