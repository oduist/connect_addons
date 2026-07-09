# -*- coding: utf-8 -*

import json
import logging

from werkzeug.exceptions import Unauthorized

from odoo import http
from odoo.addons.connect_elevenlabs.controllers.main import ConnectElevenlabsController

logger = logging.getLogger(__name__)


class ConnectElevenlabsSaleController(ConnectElevenlabsController):

    @http.route('/connect_elevenlabs_sale/get_products', methods=['POST'], type='http',
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
            'items_in_stock': 10,
            'product_description': k.description_sale,
        } for k in products if k.is_published]
        logger.info('Available products: %s', json.dumps(res, indent=2))
        return http.request.make_json_response(res)

    @http.route('/connect_elevenlabs_sale/create_order', methods=['POST'], type='http',
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
            return http.request.make_json_response(
                {'error': 'Product not found! Please contact technical support!'})
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
        return http.request.make_json_response({'order_name': order.name})

    @http.route('/connect_elevenlabs_sale/get_order', methods=['POST'], type='http',
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
            return http.request.make_json_response(
                {'error': 'You must provide your partner ID to get your orders!'})
        if not data.get('order_name'):
            return http.request.make_json_response(
                {'error': 'You must provide order name to search for your order!'})
        search_domain = [
            ('partner_id', '=', data.get('partner_id')),
            ('name', '=', data.get('order_name')),
        ]
        sale_orders = http.request.env['sale.order'].sudo().search(search_domain)
        if not sale_orders:
            return http.request.make_json_response({'error': 'Sale Order is not found!'})
        orders = []
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
        return http.request.make_json_response({'orders': orders})

    @http.route('/connect_elevenlabs_sale/get_orders', methods=['POST'], type='http',
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
            return http.request.make_json_response(
                {'error': 'You must provide your partner ID to get your orders!'})
        search_domain = [
            ('partner_id', '=', data.get('partner_id'))
        ]
        sale_orders = http.request.env['sale.order'].sudo().search(search_domain)
        if not sale_orders:
            return http.request.make_json_response({'error': 'Sale Orders not found!'})
        order_names = sale_orders.mapped('name')
        logger.info('Sale Orders for partner %s: %s', data['partner_id'], order_names)
        return http.request.make_json_response({'orders': order_names})
