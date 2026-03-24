/** @odoo-module **/
import basic_fields from 'web.basic_fields'

const Phone = basic_fields.FieldPhone

Phone.include({

    init() {
        this._super.apply(this, arguments)
        this.enableCall = 'enable_call' in this.attrs.options ? this.attrs.options.enable_call : true
        this.attrs.options.enable_call = this.enableCall
    },

    getFocusableElement() {
        if (this.enableCall && this.mode === 'readonly') {
            return this.$el.filter('.' + this.className).find('a')
        }
        return this._super.apply(this, arguments)
    },

    _onClickPhone: function (ev) {
        ev.preventDefault()
        ev.stopPropagation()

        return this._rpc({
            model: 'connect.settings',
            method: 'originate_call',
            args: [this.value, this.model, parseInt(this.res_id)],
        })
    },

    _onClickWhatsappCallButton: function (ev) {
        ev.preventDefault()
        ev.stopPropagation()

        return this._rpc({
            model: 'connect.settings',
            method: 'originate_call',
            args: [this.value, this.model, parseInt(this.res_id)],
            kwargs: {whatsapp_call: true},
        })
    },

    _onClickWhatsappMessageButton: function (ev) {
        ev.preventDefault()
        ev.stopPropagation()

        var context = _.extend({}, context, {
            default_res_model: this.model,
            default_res_id: parseInt(this.res_id),
            default_number_field_name: this.name,
            default_composition_mode: 'comment',
            default_phone: this.value,
        })

        console.log(context)
        var self = this
        return this.do_action({
            title: 'WhatsApp',
            type: 'ir.actions.act_window',
            res_model: 'connect.whatsapp_composer',
            target: 'new',
            views: [[false, 'form']],
            context: context,
        }, {
        on_close: function () {
            self.trigger_up('reload');
        }})
    },

    _renderReadonly: function () {
        const def = this._super.apply(this, arguments)
        if (this.enableCall && this.value) {
            const $callButton = $('<a>', {
                title: 'Click to Call',
                href: '',
                class: 'ml-3 d-inline-flex align-items-center o_field_phone',
                html: $('<small>', {class: 'font-weight-bold ml-1', html: 'Call'}),
            })
            $callButton.prepend($('<i>', {class: 'fa fa-phone'}))
            $callButton.on('click', this._onClickPhone.bind(this))

            const $whatsappCallButton = $('<a>', {
                title: 'WhatsApp Call',
                href: '',
                class: 'ml-3 d-inline-flex align-items-center o_field_phone',
                html: $('<small>', {class: 'font-weight-bold ml-1', html: 'Call'}),
            })
            $whatsappCallButton.prepend($('<i>', {class: 'fa fa-whatsapp'}))
            $whatsappCallButton.on('click', this._onClickWhatsappCallButton.bind(this))

            const $whatsappMessageButton = $('<a>', {
                title: 'Send WhatsApp Message',
                href: '',
                class: 'ml-3 d-inline-flex align-items-center o_field_phone',
                html: $('<small>', {class: 'font-weight-bold ml-1', html: 'Message'}),
            })
            $whatsappMessageButton.prepend($('<i>', {class: 'fa fa-whatsapp'}))
            $whatsappMessageButton.on('click', this._onClickWhatsappMessageButton.bind(this))

            this.$el = this.$el.add($whatsappMessageButton) // .add($callButton).add($whatsappCallButton)
        }
        return def
    }
})
