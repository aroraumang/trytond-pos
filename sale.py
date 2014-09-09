# -*- coding: utf-8 -*-
"""
    sale.py

    :copyright: (c) 2014 by Openlabs Technologies & Consulting (P) Limited
    :license: BSD, see LICENSE for more details.
"""
from datetime import datetime, timedelta
from trytond.model import fields
from trytond.pool import Pool, PoolMeta
from trytond.transaction import Transaction
from trytond.rpc import RPC
from trytond.pyson import Eval, Bool

__metaclass__ = PoolMeta
__all__ = ["Sale", "SaleShop", "SaleLine"]


class SaleShop:
    __name__ = 'sale.shop'

    anonymous_customer = fields.Many2One(
        'party.party', "Anonymous Customer", required=True
    )

    # The warehouse from which order lines with ship will be shipped
    ship_from_warehouse = fields.Many2One(
        'stock.location', "Warehouse (Shipped Lines)",
        required=True, domain=[('type', '=', 'warehouse')],
    )

    delivery_mode = fields.Selection([
        ('pick_up', 'Pick Up'),
        ('ship', 'Ship'),
    ], 'Delivery Mode', required=True)

    sale_shipment_cost_method = fields.Property(fields.Selection([
        ('order', 'On Order'),
        ('shipment', 'On Shipment'),
    ], 'Sale Shipment Cost Method', states={
        'required': Bool(Eval('context', {}).get('company')),
    }))

    @staticmethod
    def default_delivery_mode():
        return 'ship'

    @staticmethod
    def default_sale_shipment_cost_method():
        return 'shipment'


class Sale:
    __name__ = "sale.sale"

    @staticmethod
    def default_party():
        User = Pool().get('res.user')
        user = User(Transaction().user)
        if (
            'use_anonymous_customer' not in Transaction().context
        ):  # pragma: no cover
            return
        if user.shop and user.shop.anonymous_customer:
            return user.shop.anonymous_customer.id

    @classmethod
    def __setup__(cls):
        super(Sale, cls).__setup__()
        cls.__rpc__.update({
            'pos_add_product': RPC(instantiate=0, readonly=False),
            'pos_serialize': RPC(instantiate=0, readonly=True),
            'get_recent_sales': RPC(readonly=True),
        })

    @classmethod
    def get_recent_sales(cls):
        """
        Return sales of current shop, which were made within last 5 days
        and are in draft state. Sort by write_date or create_date of Sale and
        sale lines.
        """
        context = Transaction().context
        date = (
            datetime.now() - timedelta(days=5)
        ).strftime('%Y-%m-%d %H:%M:%S')
        current_shop = context['shop']

        cursor = Transaction().cursor
        cursor.execute(
            "SELECT sale_sale.id \
            FROM sale_sale INNER JOIN sale_line \
            ON (sale_sale.id = sale_line.sale) \
            WHERE shop=%d AND state='draft' AND \
            (sale_sale.write_date >= '%s' OR sale_sale.create_date >= '%s') \
            ORDER BY sale_line.write_date DESC, sale_line.create_date DESC, \
            sale_sale.write_date DESC, sale_sale.create_date DESC"
            % (current_shop, date, date)
        )
        ids = [x[0] for x in cursor.fetchall()]
        return [cls(id).serialize('recent_sales') for id in ids]

    def pos_find_sale_line_domain(self):
        """
        Return domain to find existing sale line for given product.
        """
        domain = [
            ('sale', '=', self.id),
        ]

        context = Transaction().context

        if 'product' in context:
            domain.append(('product', '=', context['product']))

        if 'delivery_mode' in context:
            domain.append(('delivery_mode', '=', context['delivery_mode']))

        return domain

    def pos_add_product(self, product_id, quantity):
        """
        Add product to sale from POS
        """
        AccountTax = Pool().get('account.tax')
        SaleLine = Pool().get('sale.line')
        Transaction().set_context(product=product_id)

        try:
            if 'sale_line' in Transaction().context:
                sale_line = SaleLine(Transaction().context.get('sale_line'))
            else:
                sale_line, = SaleLine.search(self.pos_find_sale_line_domain())
        except ValueError:
            sale_line = None

        delivery_mode = Transaction().context.get('delivery_mode', 'pick_up')

        if sale_line:
            values = {
                'product': sale_line.product.id,
                '_parent_sale.currency': self.currency.id,
                '_parent_sale.party': self.party.id,
                '_parent_sale.price_list': (
                    self.price_list.id if self.price_list else None
                ),
                'unit': sale_line.unit.id,
                'quantity': quantity,
                'type': 'line',
            }
            if delivery_mode:
                values['delivery_mode'] = delivery_mode

            # Update the values by triggering an onchange which should
            # fill missing vals
            values.update(SaleLine(**values).on_change_quantity())

            new_values = {}
            for key, value in values.iteritems():
                if '.' in key:
                    continue
                if key == 'taxes':
                    # Difficult to reach here unless taxes change when
                    # quantities change.
                    continue    # pragma: no cover
                new_values[key] = value
            SaleLine.write([sale_line], new_values)
        else:
            values = {
                'product': product_id,
                '_parent_sale.currency': self.currency.id,
                '_parent_sale.party': self.party.id,
                '_parent_sale.price_list': (
                    self.price_list.id if self.price_list else None
                ),
                'sale': self.id,
                'type': 'line',
                'quantity': quantity,
                'unit': None,
                'description': None,
            }
            if delivery_mode:
                values['delivery_mode'] = delivery_mode
            values.update(SaleLine(**values).on_change_product())
            values.update(SaleLine(**values).on_change_quantity())
            new_values = {}
            for key, value in values.iteritems():
                if '.' in key:
                    continue
                if key == 'taxes':
                    continue
                new_values[key] = value
            sale_line = SaleLine.create([new_values])[0]

        if 'taxes' in values:
            sale_line.taxes = AccountTax.browse(values['taxes'])
            sale_line.save()

        # Now that the sale line is built, return a serializable response
        # which ensures that the client does not have to call again.
        res = {
            'sale': self.serialize('pos'),
            'updated_line_id': sale_line.id,
        }
        return res

    def pos_serialize(self):
        """
        Serialize sale for pos
        """
        return self.serialize('pos')

    def serialize(self, purpose=None):
        """
        Serialize with information needed for POS
        """
        if purpose == 'pos':
            return {
                'party': self.party.id,
                'total_amount': self.total_amount,
                'untaxed_amount': self.untaxed_amount,
                'tax_amount': self.tax_amount,
                'state': self.state,
                'invoice_address': self.invoice_address and
                    self.invoice_address.serialize('pos'),
                'shipment_address': self.shipment_address and
                    self.shipment_address.serialize('pos'),
                'lines': [line.serialize(purpose) for line in self.lines],
            }
        elif purpose == 'recent_sales':
            return {
                'id': self.id,
                'party': {
                    'id': self.party.id,
                    'name': self.party.name,
                },
                'total_amount': self.total_amount,
                'create_date': self.create_date,
            }
        elif hasattr(super(Sale, self), 'serialize'):
            return super(SaleLine, self).serialize(purpose)  # pragma: no cover

    def _group_shipment_key(self, moves, move):
        """
        This method returns a key based on which Tryton creates shipments
        for a given sale order. By default Tryton uses the planned_date for the
        delivery and warehouse to separate shipments.

        We use the same functionality to split the shipments for items being
        picked up and delivered. This is later used to auto proceed and finish
        the shipping of the picked up products.

        :param moves: A list of all moves
        :param move: move is a tuple of line id and a move
        """
        SaleLine = Pool().get('sale.line')

        line = SaleLine(move[0])
        rv = super(Sale, self)._group_shipment_key(moves, move)
        return rv + (('delivery_mode', line.delivery_mode),)

    def create_shipment(self, shipment_type):
        """
        This method creates the shipments for the given sale order.

        This implementation inspects the order lines to look for lines which
        are expected to be picked up instantly and the shipment created for
        pick_up is automatically processed all the way through.
        """
        pool = Pool()

        shipments = super(Sale, self).create_shipment(shipment_type)

        if self.shipment_method == 'manual':
            # shipments will be None but for future return the value
            # returned by the super function
            return shipments

        if not shipments:
            return shipments

        picked_up_shipments = filter(
            lambda s: s.delivery_mode == 'pick_up', shipments
        )

        if shipment_type == 'out':
            Shipment = pool.get('stock.shipment.out')

            with Transaction().set_user(0, set_context=True):
                # Force assign and complete the shipments
                Shipment.assign_force(picked_up_shipments)
                Shipment.pack(picked_up_shipments)
                Shipment.done(picked_up_shipments)
        elif shipment_type == 'return':
            Shipment = pool.get('stock.shipment.out.return')
            with Transaction().set_user(0, set_context=True):
                Shipment.receive(picked_up_shipments)
                Shipment.done(picked_up_shipments)

        # Finally return the value the super function returned, but after
        # reloading the active records.
        return Shipment.browse(map(int, shipments))

    def create_invoice(self, invoice_type):
        """
        Sale creates draft invoices. But if the invoices are created from
        shipments, then they should be automatically opened
        """
        Invoice = Pool().get('account.invoice')

        invoice = super(Sale, self).create_invoice(invoice_type)

        if not invoice:
            return invoice

        if self.invoice_method == 'shipment' and invoice_type == 'out_invoice':
            # Invoices created from shipment can be automatically opened
            # for payment.
            Invoice.post([invoice])

        return invoice

    @staticmethod
    def default_shipment_cost_method():
        User = Pool().get('res.user')
        user = User(Transaction().user)
        if not user.shop:
            Config = Pool().get('sale.configuration')
            config = Config(1)
            return config.sale_shipment_cost_method
        return user.shop.sale_shipment_method

    @fields.depends(
        'shop', 'company', 'invoice_method', 'shipment_method',
        'warehouse', 'price_list', 'payment_term', 'shipment_cost_method'
    )
    def on_change_shop(self):
        """
        Change shipment cost method on change of shop
        """
        res = super(Sale, self).on_change_shop()

        if res:
            res.update({
                'shipment_cost_method': self.shop.sale_shipment_cost_method,
            })
        return res


class SaleLine:
    __name__ = 'sale.line'

    delivery_mode = fields.Selection([
        ('pick_up', 'Pick Up'),
        ('ship', 'Ship'),
    ], 'Delivery Mode', states={
        'invisible': Eval('type') != 'line',
    }, depends=['type'], required=True)

    @staticmethod
    def default_delivery_mode():
        Sale = Pool().get('sale.sale')
        if 'active_id' not in Transaction().context:
            User = Pool().get('res.user')
            user = User(Transaction().user)
            return user.shop.delivery_mode if user.shop else 'ship'
        sale = Sale(Transaction().context.get('active_id'))
        return sale.shop.delivery_mode if sale.shop else 'ship'

    def get_warehouse(self, name):
        """
        Return the warehouse from the shop for orders being picked up and the
        backorder warehouse for orders with ship.
        """
        if self.delivery_mode == 'ship':
            return self.sale.shop.ship_from_warehouse.id
        return super(SaleLine, self).get_warehouse(name)

    def serialize(self, purpose=None):
        """
        Serialize for the purpose of POS
        """
        if purpose == 'pos':
            return {
                'id': self.id,
                'description': self.description,
                'product': {
                    'id': self.product.id,
                    'code': self.product.code,
                    'rec_name': self.product.rec_name,
                    'default_image': self.product.default_image and
                                    self.product.default_image.id,
                },
                'unit': {
                    'id': self.unit.id,
                    'rec_name': self.unit.rec_name,
                },
                'unit_price': self.unit_price,
                'quantity': self.quantity,
                'amount': self.amount,
                'delivery_mode': self.delivery_mode
            }
        elif hasattr(super(SaleLine, self), 'serialize'):
            return super(SaleLine, self).serialize(purpose)  # pragma: no cover
