# -*- coding: utf-8 -*

import json
import logging

from werkzeug.exceptions import Unauthorized

from odoo import http, release
from odoo.addons.connect_elevenlabs.controllers.main import ConnectElevenlabsController

logger = logging.getLogger(__name__)
route_type = "json" if release.version_info[0] < 19.0 else 'jsonrpc'

class ConnectElevenlabsSaleController(ConnectElevenlabsController):

    def dispatch(self, method_name, args, kwargs):
        http.request.env['oduist.license'].check_license('connect_elevenlabs_sale', silent=False)
        return super().dispatch(method_name, args, kwargs)

    @http.route('/connect_elevenlabs_sale/create_partner', methods=['POST'], type=route_type,
                auth='public', csrf=False)
    def create_partner(self):
        if not self.check_tool_token():
            raise Unauthorized()
        data = json.loads(http.request.httprequest.get_data(as_text=True))
        logger.info('Agent data: %s', data)
        call = http.request.env['connect.call'].sudo().browse(int(data['call_id']))
        if call.direction == 'outgoing':
            data['partner_phone'] = call.called
        else:
            data['partner_phone'] = call.caller
        partner = http.request.env['res.partner'].sudo().with_context(
            connect_call_id=int(data['call_id'])).create({
                'name': data['name'],
                'phone': data.get('partner_phone')
            })
        logger.info('Partner %s (%s) has been created: ', partner.name, partner.id)
        # Now assign partner to the call.
        http.request.env['connect.call'].sudo().partner = partner.id
        return {
            'partner_id': partner.id,
            'message': 'Partner created'
        }


    @staticmethod
    def _items_in_stock(product):
        """On-hand quantity of a product, or None when it does not apply.

        Returns ``None`` -- never a made-up number -- when stock is not
        installed or the product is not storable (a service has no stock).
        The agent must be able to tell "I don't track this" apart from
        "there are none left".
        """
        if 'qty_available' not in product._fields:
            # The stock module is not installed: nothing tracks quantities.
            return None
        if not product.is_storable:
            return None
        return product.qty_available

    @http.route('/connect_elevenlabs_sale/get_products', methods=['POST'], type=route_type,
                auth='public', csrf=False)
    def get_products(self):
        if not self.check_tool_token():
            raise Unauthorized()
        data = json.loads(http.request.httprequest.get_data(as_text=True))
        logger.info('Agent data: %s', data)
        products = http.request.env['product.template'].sudo().search([])
        res = [{
            'product_id': k.id,
            'product_name': k.name,
            'product_categories': [
                {'cetegory_name': c.name, 'category_id': c.id} for c in k.public_categ_ids],
            'product_price': k.list_price,
            'items_in_stock': self._items_in_stock(k),
            'product_description': k.description_sale,
        } for k in products if k.is_published]
        logger.info('Available products: %s', json.dumps(res, indent=2))
        return res

    @http.route('/connect_elevenlabs_sale/create_order', methods=['POST'], type=route_type,
                auth='public', csrf=False)
    def create_order(self):
        if not self.check_tool_token():
            raise Unauthorized()
        data = json.loads(http.request.httprequest.get_data(as_text=True))
        logger.info('Agent data: %s', data)
        # Create the sale order
        product = http.request.env['product.template'].sudo().search(
            [('id', '=', data.get('product_id'))])
        if not product:
            return 'Product not found! Please contact technical support!'
        order_data = {
            'partner_id': data.get('partner_id'),
            'order_line': [
                (0, 0, {
                    'product_id': data.get('product_id'),
                    'product_uom_qty': data.get('product_quantity'),
                    'price_unit': product.list_price,
                }),
            ]
        }
        # Check for installed sale modules
        if 'partner_invoice_id' in http.request.env['sale.order']._fields.keys():
            order_data.update({
                'partner_invoice_id': order_data['partner_id'],
                'partner_shipping_id': order_data['partner_id']
            })
        order = http.request.env['sale.order'].sudo().create(order_data)
        logger.info('Sale order created: %s (%s)', order.name, order.id)
        return {'order_name': order.name}


    @http.route('/connect_elevenlabs_sale/get_order', methods=['POST'], type=route_type,
                auth='public', csrf=False)
    def get_order(self):
        if not self.check_tool_token():
            raise Unauthorized()
        data = json.loads(http.request.httprequest.get_data(as_text=True))
        logger.info('Agent data: %s', data)
        call = http.request.env['connect.call'].sudo().browse(int(data['call_id']))
        if call.direction == 'outgoing':
            data['partner_phone'] = call.called
        else:
            data['partner_phone'] = call.caller
        if not data.get('partner_id'):
            return 'You must provide your partner ID to get your orders!'
        if not data.get('order_name'):
            return 'You must provide order name to search for your order!'
        search_domain = [
            ('partner_id', '=', data.get('partner_id')),
            ('name', '=', data.get('order_name')),
        ]
        sale_orders = http.request.env['sale.order'].sudo().search(search_domain)
        orders = []
        if not sale_orders:
            return 'Sale Order is not found!'
        for order in sale_orders:
            items = []
            for item in order.order_line:
                items.append({
                    'product_name': item.product_id.name,
                    'quantity': item.product_uom_qty,
                })
            orders.append({
                'order_id': order.id,
                'order_number': order.name,
                'delivery_date': str(order.commitment_date),
                'shipping_weight': order.shipping_weight,
                'manager_name': order.user_id.name or 'Manager not set',
                'manager_extension': order.user_id.connect_user.exten.number or 'No extension',
                'items': items,
            })
        logger.info('Sale Order data for partner %s: %s', data.get('partner_id'), json.dumps(orders))
        return json.dumps(orders)

    @http.route('/connect_elevenlabs_sale/get_orders', methods=['POST'], type=route_type,
                auth='public', csrf=False)
    def get_orders(self):
        if not self.check_tool_token():
            raise Unauthorized()
        data = json.loads(http.request.httprequest.get_data(as_text=True))
        logger.info('Agent data: %s', data)
        call = http.request.env['connect.call'].sudo().browse(int(data['call_id']))
        if call.direction == 'outgoing':
            data['partner_phone'] = call.called
        else:
            data['partner_phone'] = call.caller
        if not data.get('partner_id'):
            return 'You must provide your partner ID to get your orders!'
        search_domain = [
            ('partner_id', '=', data.get('partner_id'))
        ]
        sale_orders = http.request.env['sale.order'].sudo().search(search_domain)
        orders = []
        if not sale_orders:
            return 'Sale Orders not found!'
        order_names = sale_orders.mapped('name')
        logger.info('Sale Orders for partner %s: %s', data['partner_id'], order_names)
        return ','.join(order_names)
