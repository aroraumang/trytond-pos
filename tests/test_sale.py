# -*- coding: utf-8 -*-
"""
    tests/test_sale.py

    :copyright: (C) 2014 by Openlabs Technologies & Consulting (P) Limited
    :license: BSD, see LICENSE for more details.
"""
import sys
import os
DIR = os.path.abspath(os.path.normpath(os.path.join(
    __file__, '..', '..', '..', '..', '..', 'trytond'
)))
if os.path.isdir(DIR):
    sys.path.insert(0, os.path.dirname(DIR))
import unittest
import datetime
from decimal import Decimal
from dateutil.relativedelta import relativedelta

import trytond.tests.test_tryton
from trytond.tests.test_tryton import POOL, USER, DB_NAME, CONTEXT
from trytond.transaction import Transaction


class TestSale(unittest.TestCase):
    '''
    Sale Test Case for lie-nielsen module.
    '''

    def setUp(self):
        """
        Set up data used in the tests.
        this method is called before each test function execution.
        """
        trytond.tests.test_tryton.install_module('pos')
        self.Company = POOL.get('company.company')
        self.Party = POOL.get('party.party')
        self.Address = POOL.get('party.address')
        self.Currency = POOL.get('currency.currency')
        self.User = POOL.get('res.user')
        self.Location = POOL.get('stock.location')
        self.PriceList = POOL.get('product.price_list')
        self.PaymentTerm = POOL.get('account.invoice.payment_term')
        self.Sequence = POOL.get('ir.sequence')
        self.Sale = POOL.get('sale.sale')
        self.SaleLine = POOL.get('sale.line')
        self.Shop = POOL.get('sale.shop')

    def _create_product_category(self, name):
        """
        Creates a product category

        Name is mandatory while other value may be provided as keyword
        arguments

        :param name: Name of the product category
        """
        Category = POOL.get('product.category')

        return Category.create([{
            'name': name,
            'uri': 'test_uri',
        }])

    def _create_product_template(self, name, vlist, uom=u'Unit'):
        """
        Create a product template with products and return its ID

        :param name: Name of the product
        :param vlist: List of dictionaries of values to create
        :param uom: Note it is the name of UOM (not symbol or code)
        """
        ProductTemplate = POOL.get('product.template')
        Uom = POOL.get('product.uom')

        for values in vlist:
            values['name'] = name
            values['default_uom'], = Uom.search([('name', '=', uom)], limit=1)
            values['sale_uom'], = Uom.search([('name', '=', uom)], limit=1)
            values['products'] = [
                ('create', [{}])
            ]
        return ProductTemplate.create(vlist)

    def _create_fiscal_year(self, date=None, company=None):
        """
        Creates a fiscal year and requried sequences
        """
        FiscalYear = POOL.get('account.fiscalyear')
        Sequence = POOL.get('ir.sequence')
        SequenceStrict = POOL.get('ir.sequence.strict')
        Company = POOL.get('company.company')

        if date is None:
            date = datetime.date.today()

        if company is None:
            company, = Company.search([], limit=1)

        invoice_sequence, = SequenceStrict.create([{
            'name': '%s' % date.year,
            'code': 'account.invoice',
            'company': company,
        }])
        fiscal_year, = FiscalYear.create([{
            'name': '%s' % date.year,
            'start_date': date + relativedelta(month=1, day=1),
            'end_date': date + relativedelta(month=12, day=31),
            'company': company,
            'post_move_sequence': Sequence.create([{
                'name': '%s' % date.year,
                'code': 'account.move',
                'company': company,
            }])[0],
            'out_invoice_sequence': invoice_sequence,
            'in_invoice_sequence': invoice_sequence,
            'out_credit_note_sequence': invoice_sequence,
            'in_credit_note_sequence': invoice_sequence,
        }])
        FiscalYear.create_period([fiscal_year])
        return fiscal_year

    def _create_coa_minimal(self, company):
        """Create a minimal chart of accounts
        """
        AccountTemplate = POOL.get('account.account.template')
        Account = POOL.get('account.account')

        account_create_chart = POOL.get(
            'account.create_chart', type="wizard")

        account_template, = AccountTemplate.search(
            [('parent', '=', None)]
        )

        session_id, _, _ = account_create_chart.create()
        create_chart = account_create_chart(session_id)
        create_chart.account.account_template = account_template
        create_chart.account.company = company
        create_chart.transition_create_account()

        receivable, = Account.search([
            ('kind', '=', 'receivable'),
            ('company', '=', company),
        ])
        payable, = Account.search([
            ('kind', '=', 'payable'),
            ('company', '=', company),
        ])
        create_chart.properties.company = company
        create_chart.properties.account_receivable = receivable
        create_chart.properties.account_payable = payable
        create_chart.transition_create_properties()

    def _get_account_by_kind(self, kind, company=None, silent=True):
        """Returns an account with given spec

        :param kind: receivable/payable/expense/revenue
        :param silent: dont raise error if account is not found
        """
        Account = POOL.get('account.account')
        Company = POOL.get('company.company')

        if company is None:
            company, = Company.search([], limit=1)

        accounts = Account.search([
            ('kind', '=', kind),
            ('company', '=', company)
        ], limit=1)
        if not accounts and not silent:
            raise Exception("Account not found")
        return accounts[0] if accounts else None

    def _create_payment_term(self):
        """Create a simple payment term with all advance
        """
        PaymentTerm = POOL.get('account.invoice.payment_term')

        return PaymentTerm.create([{
            'name': 'Direct',
            'lines': [('create', [{'type': 'remainder'}])]
        }])

    def _create_pricelists(self):
        """
        Create the pricelists
        """
        # Setup the pricelists
        self.party_pl_margin = Decimal('1.10')
        self.guest_pl_margin = Decimal('1.20')
        user_price_list, = self.PriceList.create([{
            'name': 'PL 1',
            'company': self.company.id,
            'lines': [
                ('create', [{
                    'formula': 'unit_price * %s' % self.party_pl_margin
                }])
            ],
        }])
        guest_price_list, = self.PriceList.create([{
            'name': 'PL 2',
            'company': self.company.id,
            'lines': [
                ('create', [{
                    'formula': 'unit_price * %s' % self.guest_pl_margin
                }])
            ],
        }])
        return guest_price_list.id, user_price_list.id

    def setup_defaults(self):
        """
        Setup Defaults
        """
        Uom = POOL.get('product.uom')
        AccountTax = POOL.get('account.tax')
        Account = POOL.get('account.account')

        self.usd, = self.Currency.create([{
            'name': 'US Dollar',
            'code': 'USD',
            'symbol': '$',
        }])

        Country = POOL.get('country.country')
        self.country, = Country.create([{
            'name': 'United States of America',
            'code': 'US',
        }])

        Subdivision = POOL.get('country.subdivision')
        self.subdivision, = Subdivision.create([{
            'country': self.country.id,
            'name': 'California',
            'code': 'CA',
            'type': 'state',
        }])

        self.uom, = Uom.search([('symbol', '=', 'u')], limit=1)

        with Transaction().set_user(0):
            self.party, = self.Party.create([{
                'name': 'Openlabs',
                'addresses': [('create', [{
                    'name': 'Lie Nielsen',
                    'city': 'Los Angeles',
                    'country': self.country.id,
                    'subdivision': self.subdivision.id,
                }])],
            }])
            self.anonymous_customer, = self.Party.create([{
                'name': 'Anonymous Customer Party'
            }])
            self.address, = self.Address.create([{
                'party': self.anonymous_customer,
                'name': 'Jon Doe\'s Address'
            }])
            self.company, = self.Company.create([{
                'party': self.party.id,
                'currency': self.usd
            }])
            user = self.User(USER)
            self.User.write([user], {
                'main_company': self.company.id,
                'company': self.company.id,
            })

        with Transaction().set_context(company=self.company.id):
            # Create Fiscal Year
            self._create_fiscal_year(company=self.company.id)
            # Create Chart of Accounts
            self._create_coa_minimal(company=self.company.id)
            # Create a payment term
            self._create_payment_term()

            sequence, = self.Sequence.search([
                ('code', '=', 'sale.sale'),
            ], limit=1)
            warehouse, = self.Location.search([
                ('code', '=', 'WH'),
            ])
            self.payment_term, = self.PaymentTerm.create([{
                'name': 'Payment term',
                'lines': [
                    ('create', [{
                        'sequence': 0,
                        'type': 'remainder',
                        'days': 0,
                        'months': 0,
                        'weeks': 0,
                    }])]
            }])
            price_list, = self.PriceList.create([{
                'name': 'PL 1',
                'company': self.company.id,
                'lines': [
                    ('create', [{
                        'formula': 'unit_price'
                    }])
                ],
            }])

            self.shop, = self.Shop.create([{
                'name': 'Shop',
                'anonymous_customer': self.anonymous_customer.id,
                'warehouse': warehouse.id,
                'ship_from_warehouse': warehouse.id,
                'price_list': price_list.id,
                'payment_term': self.payment_term.id,
                'sale_sequence': sequence.id,
                'sale_invoice_method': 'order',
                'sale_invoice_method': 'order',
                'sale_shipment_cost_method': 'shipment',
            }])
            self.shop1, = self.Shop.create([{
                'name': 'Shop',
                'anonymous_customer': self.anonymous_customer.id,
                'warehouse': warehouse.id,
                'ship_from_warehouse': warehouse.id,
                'price_list': price_list.id,
                'payment_term': self.payment_term.id,
                'sale_sequence': sequence.id,
                'sale_invoice_method': 'order',
                'sale_invoice_method': 'order',
                'sale_shipment_cost_method': 'shipment',
            }])
            user = self.User(USER)
            self.User.write([user], {
                'shops': [('add', [self.shop, self.shop1])],
                'shop': self.shop.id,
            })
            account = Account.search([('name', '=', 'Main Tax')])[0]
            tax, = AccountTax.create([{
                'name': 'Test Tax',
                'description': 'Test Tax',
                'rate': Decimal('0.10'),
                'invoice_account': account,
                'credit_note_account': account,
            }])

        self.category, = self._create_product_category(
            'Category'
        )

        # Create product templates with products
        self.template1, = self._create_product_template(
            'product-1',
            [{
                'category': self.category.id,
                'type': 'goods',
                'salable': True,
                'list_price': Decimal('10'),
                'cost_price': Decimal('5'),
                'account_expense': self._get_account_by_kind('expense').id,
                'account_revenue': self._get_account_by_kind('revenue').id,
            }]
        )
        self.template2, = self._create_product_template(
            'product-2',
            [{
                'category': self.category.id,
                'type': 'goods',
                'salable': True,
                'list_price': Decimal('15'),
                'cost_price': Decimal('5'),
                'account_expense': self._get_account_by_kind('expense').id,
                'account_revenue': self._get_account_by_kind('revenue').id,
            }]
        )
        self.template3, = self._create_product_template(
            'product-3',
            [{
                'category': self.category.id,
                'type': 'goods',
                'salable': True,
                'list_price': Decimal('15'),
                'cost_price': Decimal('5'),
                'account_expense': self._get_account_by_kind('expense').id,
                'account_revenue': self._get_account_by_kind('revenue').id,
                'customer_taxes': [('add', [tax])]
            }]
        )
        self.product1 = self.template1.products[0]
        self.product2 = self.template2.products[0]
        self.product3 = self.template3.products[0]

    def test_0010_test_sale(self):
        """
        Sale model is not broken
        """
        with Transaction().start(DB_NAME, USER, CONTEXT):
            self.setup_defaults()

            with Transaction().set_context(use_anonymous_customer=True):
                sale, = self.Sale.create([{
                    'currency': self.usd.id,
                }])

            with Transaction().set_context(
                    company=self.company.id, shop=self.shop.id
            ):
                sale.pos_add_product(self.product1.id, 1)
                self.assertEqual(len(sale.lines), 1)
                sale.pos_add_product(self.product1.id, 2)
                self.assertEqual(len(sale.lines), 1)
                self.assertEqual(sale.lines[0].quantity, 2)

                rv = sale.pos_add_product(self.product2.id, 2)
                self.assertEqual(len(sale.lines), 2)

            self.assertEqual(len(rv['sale']['lines']), 2)

    def test_0020_test_delivery_mode_on_adding(self):
        """
        Ensure that delivery mode is respected when added to cart
        """
        with Transaction().start(DB_NAME, USER, context=CONTEXT):
            self.setup_defaults()
            with Transaction().set_context(use_anonymous_customer=True):
                sale, = self.Sale.create([{
                    'currency': self.usd.id,
                }])

            with Transaction().set_context(
                    company=self.company.id, shop=self.shop.id
            ):
                rv = sale.pos_add_product(self.product1.id, 1)

                # By default the lines are picked
                self.assertEqual(len(rv['sale']['lines']), 1)
                self.assertEqual(
                    rv['sale']['lines'][0]['delivery_mode'], 'pick_up'
                )
                self.assertEqual(rv['sale']['lines'][0]['quantity'], 1)

                # Add another line, but with explicit delivery_mode
                with Transaction().set_context(delivery_mode='pick_up'):
                    rv = sale.pos_add_product(self.product1.id, 2)
                self.assertEqual(len(rv['sale']['lines']), 1)
                self.assertEqual(
                    rv['sale']['lines'][0]['delivery_mode'], 'pick_up'
                )
                self.assertEqual(rv['sale']['lines'][0]['quantity'], 2)

                # Add a ship line of same product
                with Transaction().set_context(delivery_mode='ship'):
                    rv = sale.pos_add_product(self.product1.id, 1)
                    self.assertEqual(len(rv['sale']['lines']), 2)

                    for pick_line in filter(
                            lambda l: l['delivery_mode'] == 'pick_up',
                            rv['sale']['lines']):
                        # From the previous addition
                        self.assertEqual(pick_line['delivery_mode'], 'pick_up')
                        self.assertEqual(pick_line['quantity'], 2)
                        break
                    else:
                        self.fail('Expected to find pick up line, but did not')

                    for ship_line in filter(
                            lambda l: l['delivery_mode'] == 'ship',
                            rv['sale']['lines']):
                        self.assertEqual(ship_line['delivery_mode'], 'ship')
                        self.assertEqual(ship_line['quantity'], 1)
                        break
                    else:
                        self.fail('Expected to find line, but did not')

    def test_0022_test_update_delivery_mode(self):
        """
        Update delivery mode of saleLine
        """
        with Transaction().start(DB_NAME, USER, context=CONTEXT):
            self.setup_defaults()
            with Transaction().set_context(use_anonymous_customer=True):
                sale, = self.Sale.create([{
                    'currency': self.usd.id,
                }])

            with Transaction().set_context(
                    company=self.company.id, shop=self.shop.id
            ):
                rv = sale.pos_add_product(self.product1.id, 1)

                # By default the lines are picked
                self.assertEqual(len(rv['sale']['lines']), 1)
                self.assertEqual(
                    rv['sale']['lines'][0]['delivery_mode'], 'pick_up'
                )
                self.assertEqual(rv['sale']['lines'][0]['quantity'], 1)

            # Update delivery_mode in sale line
            with Transaction().set_context(
                    delivery_mode='ship',
                    sale_line=rv['updated_line_id']
            ):
                rv = sale.pos_add_product(self.product1.id, 2)

            self.assertEqual(len(rv['sale']['lines']), 1)
            self.assertEqual(rv['sale']['lines'][0]['delivery_mode'], 'ship')
            self.assertEqual(rv['sale']['lines'][0]['quantity'], 2)

            # Change product and provide saleLine
            with Transaction().set_context(
                    delivery_mode='ship',
                    sale_line=rv['updated_line_id']
            ):
                rv = sale.pos_add_product(self.product2.id, 2)

            self.assertEqual(len(rv['sale']['lines']), 1)
            # Product should not change
            self.assertEqual(
                rv['sale']['lines'][0]['product']['id'], self.product1.id
            )
            self.assertEqual(rv['sale']['lines'][0]['delivery_mode'], 'ship')
            self.assertEqual(rv['sale']['lines'][0]['quantity'], 2)

    def test_0025_add_taxes_on_line(self):
        """
        Add a line that woudl add taxes and check that it works
        """
        with Transaction().start(DB_NAME, USER, context=CONTEXT):
            self.setup_defaults()
            with Transaction().set_context(use_anonymous_customer=True):
                sale, = self.Sale.create([{
                    'currency': self.usd.id,
                }])

            with Transaction().set_context(
                    company=self.company.id, shop=self.shop.id
            ):
                rv = sale.pos_add_product(self.product1.id, 1)

                # add a product which does not have taxes
                self.assertEqual(len(rv['sale']['lines']), 1)
                sale_line = self.SaleLine(rv['updated_line_id'])
                self.assertFalse(sale_line.taxes)
                self.assertEqual(rv['sale']['tax_amount'], 0)

                rv = sale.pos_add_product(self.product3.id, 1)

                # add a product which does not have taxes
                self.assertEqual(len(rv['sale']['lines']), 2)
                sale_line = self.SaleLine(rv['updated_line_id'])
                self.assertEqual(rv['sale']['tax_amount'], Decimal('1.5'))

                # Please make that two ;)
                rv = sale.pos_add_product(self.product3.id, 2)

                # add a product which does not have taxes
                self.assertEqual(len(rv['sale']['lines']), 2)
                sale_line = self.SaleLine(rv['updated_line_id'])
                self.assertEqual(rv['sale']['tax_amount'], Decimal('3'))

    def test_0030_serialization_fallback(self):
        """
        Ensure that serialization for other purposes still work
        """
        with Transaction().start(DB_NAME, USER, context=CONTEXT):
            self.setup_defaults()
            with Transaction().set_context(use_anonymous_customer=True):
                sale, = self.Sale.create([{
                    'currency': self.usd.id,
                }])

            with Transaction().set_context(
                    company=self.company.id, shop=self.shop.id):
                rv = sale.pos_add_product(self.product1.id, 1)
                sale_line = self.SaleLine(rv['updated_line_id'])

            # Serialize sale
            sale.serialize()
            sale_line.serialize()

    def test_0035_sale_pos_serialization(self):
        """
        Serialize sale for pos
        """
        with Transaction().start(DB_NAME, USER, context=CONTEXT):
            self.setup_defaults()
            with Transaction().set_context(use_anonymous_customer=True):
                sale, = self.Sale.create([{
                    'currency': self.usd.id,
                    'invoice_address': self.address,
                    'shipment_address': self.address,
                }])

            with Transaction().set_context(
                    company=self.company.id, shop=self.shop.id):
                sale.pos_add_product(self.product1.id, 1)

            # Serialize sale for pos
            rv = sale.pos_serialize()
            self.assertEqual(rv['total_amount'], sale.total_amount)
            self.assertEqual(rv['tax_amount'], sale.tax_amount)
            self.assertEqual(len(rv['lines']), 1)

    def test_0040_default_delivery_mode(self):
        """
        Test default delivery_mode for saleLine
        """
        with Transaction().start(DB_NAME, USER, context=CONTEXT):
            self.setup_defaults()
            with Transaction().set_context(use_anonymous_customer=True):
                sale, = self.Sale.create([{
                    'currency': self.usd.id,
                }])

            self.assertEqual(self.shop.delivery_mode, 'ship')
            with Transaction().set_context(
                    company=self.company.id, shop=self.shop.id):
                sale_line, = self.SaleLine.create([{
                    'sale': sale.id,
                    'product': self.product1.id,
                    'description': 'test product',
                    'quantity': 1,
                    'unit': self.product1.default_uom.id,
                    'unit_price': Decimal('10'),
                }])
                self.assertEqual(
                    sale_line.delivery_mode, self.shop.delivery_mode
                )

    def test_0120_ship_pick_diff_warehouse(self):
        """
        Ensure that ship_from_warehouse is used for back orders while orders
        are picked from the shop's warehouse
        """
        Location = POOL.get('stock.location')
        Shop = POOL.get('sale.shop')
        Date = POOL.get('ir.date')

        with Transaction().start(DB_NAME, USER, context=CONTEXT):
            self.setup_defaults()

            ship_from_wh, = Location.copy([self.shop.warehouse])

            # Set that as the new ship_from warehouse
            Shop.write([self.shop], {'ship_from_warehouse': ship_from_wh.id})

            with Transaction().set_context({
                    'company': self.company.id,
                    'shop': self.shop.id,
                    'shops': [self.shop.id], }):
                # Now create an order
                sale, = self.Sale.create([{
                    'reference': 'Test Sale',
                    'payment_term': self.payment_term,
                    'currency': self.company.currency.id,
                    'party': self.party.id,
                    'invoice_address': self.party.addresses[0].id,
                    'shipment_address': self.party.addresses[0].id,
                    'sale_date': Date.today(),
                    'company': self.company.id,

                    # keep invoicing out of the way for this test's sake
                    'invoice_method': 'manual',
                    'shipment_method': 'order',

                    # Explicitly specify the shop
                    'shop': Shop(self.shop).id,
                }])
                self.SaleLine.create([{
                    'sale': sale,
                    'type': 'line',
                    'quantity': 2,
                    'delivery_mode': 'pick_up',
                    'unit': self.uom,
                    'unit_price': 20000,
                    'description': 'Picked Item',
                    'product': self.product1.id
                }, {
                    'sale': sale,
                    'type': 'line',
                    'quantity': 2,
                    'delivery_mode': 'ship',
                    'unit': self.uom,
                    'unit_price': 20000,
                    'description': 'Shipped Item',
                    'product': self.product1.id
                }])

                # Quote, Confirm and Process the order
                self.Sale.quote([sale])
                self.Sale.confirm([sale])
                self.Sale.process([sale])

                self.assertEqual(len(sale.shipments), 2)
                for shipment in sale.shipments:
                    if shipment.delivery_mode == 'pick_up':
                        self.assertEqual(shipment.state, 'done')
                        self.assertEqual(
                            shipment.warehouse, self.shop.warehouse
                        )
                    elif shipment.delivery_mode == 'ship':
                        self.assertEqual(shipment.state, 'waiting')
                        self.assertEqual(
                            shipment.warehouse, self.shop.ship_from_warehouse
                        )
                    else:
                        self.fail('Invalid delivery mode')

    def test_1010_delivery_method_2shipping_case_1(self):
        """
        Ensure shipment method is respected by sale order processing

        Case 1: Ship only order
        """
        Date = POOL.get('ir.date')

        with Transaction().start(DB_NAME, USER, context=CONTEXT):
            self.setup_defaults()

            sale, = self.Sale.create([{
                'reference': 'Test Sale',
                'payment_term': self.payment_term,
                'currency': self.company.currency.id,
                'party': self.party.id,
                'invoice_address': self.party.addresses[0].id,
                'shipment_address': self.party.addresses[0].id,
                'sale_date': Date.today(),
                'company': self.company.id,

                # keep invoicing out of the way for this test's sake
                'invoice_method': 'manual',
                'shipment_method': 'order',
            }])
            sale_line, = self.SaleLine.create([{
                'sale': sale,
                'type': 'line',
                'quantity': 2,
                'delivery_mode': 'ship',
                'unit': self.uom,
                'unit_price': 20000,
                'description': 'Test description',
                'product': self.product1.id
            }])

            # Quote, Confirm and Process the order
            self.Sale.quote([sale])
            self.Sale.confirm([sale])
            self.Sale.process([sale])

            self.assertEqual(len(sale.shipments), 1)
            self.assertEqual(sale.shipments[0].delivery_mode, 'ship')
            self.assertEqual(sale.shipments[0].state, 'waiting')

    def test_1020_delivery_method_2shipping_case_2(self):
        """
        Ensure shipment method is respected by sale order processing

        Case 2: Pick up only order
        """
        Date = POOL.get('ir.date')

        with Transaction().start(DB_NAME, USER, context=CONTEXT):
            self.setup_defaults()

            sale, = self.Sale.create([{
                'reference': 'Test Sale',
                'payment_term': self.payment_term,
                'currency': self.company.currency.id,
                'party': self.party.id,
                'invoice_address': self.party.addresses[0].id,
                'shipment_address': self.party.addresses[0].id,
                'sale_date': Date.today(),
                'company': self.company.id,

                # keep invoicing out of the way for this test's sake
                'invoice_method': 'manual',
                'shipment_method': 'order',
            }])
            sale_line, = self.SaleLine.create([{
                'sale': sale,
                'type': 'line',
                'quantity': 2,
                'delivery_mode': 'pick_up',
                'unit': self.uom,
                'unit_price': 20000,
                'description': 'Test description',
                'product': self.product1.id
            }])

            # Quote, Confirm and Process the order
            self.Sale.quote([sale])
            self.Sale.confirm([sale])
            self.Sale.process([sale])

            self.assertEqual(len(sale.shipments), 1)
            self.assertEqual(sale.shipments[0].delivery_mode, 'pick_up')
            self.assertEqual(sale.shipments[0].state, 'done')

    def test_1030_delivery_method_2shipping_case_3(self):
        """
        Ensure shipment method is respected by sale order processing

        Case 2: Pick up + Ship order for same item
        """
        Date = POOL.get('ir.date')

        with Transaction().start(DB_NAME, USER, context=CONTEXT):
            self.setup_defaults()

            sale, = self.Sale.create([{
                'reference': 'Test Sale',
                'payment_term': self.payment_term,
                'currency': self.company.currency.id,
                'party': self.party.id,
                'invoice_address': self.party.addresses[0].id,
                'shipment_address': self.party.addresses[0].id,
                'sale_date': Date.today(),
                'company': self.company.id,

                # keep invoicing out of the way for this test's sake
                'invoice_method': 'manual',
                'shipment_method': 'order',
            }])
            self.SaleLine.create([{
                'sale': sale,
                'type': 'line',
                'quantity': 2,
                'delivery_mode': 'pick_up',
                'unit': self.uom,
                'unit_price': 20000,
                'description': 'Picked Item',
                'product': self.product1.id
            }, {
                'sale': sale,
                'type': 'line',
                'quantity': 2,
                'delivery_mode': 'ship',
                'unit': self.uom,
                'unit_price': 20000,
                'description': 'Shipped Item',
                'product': self.product1.id
            }])

            # Quote, Confirm and Process the order
            self.Sale.quote([sale])
            self.Sale.confirm([sale])
            self.Sale.process([sale])

            self.assertEqual(len(sale.shipments), 2)
            for shipment in sale.shipments:
                if shipment.delivery_mode == 'pick_up':
                    self.assertEqual(shipment.state, 'done')
                elif shipment.delivery_mode == 'ship':
                    self.assertEqual(shipment.state, 'waiting')
                else:
                    self.fail('Invalid delivery mode')

    def test_1040_delivery_method_2shipping_case_4(self):
        """
        Manual shipping should just go ahead without messing with new
        workflow
        """
        Date = POOL.get('ir.date')

        with Transaction().start(DB_NAME, USER, context=CONTEXT):
            self.setup_defaults()

            sale, = self.Sale.create([{
                'reference': 'Test Sale',
                'payment_term': self.payment_term,
                'currency': self.company.currency.id,
                'party': self.party.id,
                'invoice_address': self.party.addresses[0].id,
                'shipment_address': self.party.addresses[0].id,
                'sale_date': Date.today(),
                'company': self.company.id,

                # keep invoicing out of the way for this test's sake
                'invoice_method': 'manual',
                'shipment_method': 'manual',
            }])
            self.SaleLine.create([{
                'sale': sale,
                'type': 'line',
                'quantity': 2,
                'delivery_mode': 'pick_up',
                'unit': self.uom,
                'unit_price': 20000,
                'description': 'Picked Item',
                'product': self.product1.id
            }, {
                'sale': sale,
                'type': 'line',
                'quantity': 2,
                'delivery_mode': 'ship',
                'unit': self.uom,
                'unit_price': 20000,
                'description': 'Shipped Item',
                'product': self.product1.id
            }])

            # Quote, Confirm and Process the order
            self.Sale.quote([sale])
            self.Sale.confirm([sale])
            self.Sale.process([sale])
            self.assertEqual(len(sale.shipments), 0)

    def test_1050_delivery_method_2shipping_case_5(self):
        """
        Return Shipment
        """
        Date = POOL.get('ir.date')

        with Transaction().start(DB_NAME, USER, context=CONTEXT):
            self.setup_defaults()

            sale, = self.Sale.create([{
                'reference': 'Test Sale',
                'payment_term': self.payment_term,
                'currency': self.company.currency.id,
                'party': self.party.id,
                'invoice_address': self.party.addresses[0].id,
                'shipment_address': self.party.addresses[0].id,
                'sale_date': Date.today(),
                'company': self.company.id,

                # keep invoicing out of the way for this test's sake
                'invoice_method': 'manual',
                'shipment_method': 'order',
            }])
            self.SaleLine.create([{
                'sale': sale,
                'type': 'line',
                'quantity': -2,
                'delivery_mode': 'pick_up',
                'unit': self.uom,
                'unit_price': 20000,
                'description': 'Picked Item',
                'product': self.product1.id
            }])

            # Quote, Confirm and Process the order
            self.Sale.quote([sale])
            self.Sale.confirm([sale])
            self.Sale.process([sale])
            self.assertEqual(len(sale.shipments), 0)
            self.assertEqual(len(sale.shipment_returns), 1)

    def test_1090_default_delivery_methods(self):
        """
        Defaults should be to ship products
        """
        with Transaction().start(DB_NAME, USER, context=CONTEXT):
            self.setup_defaults()

            ShipmentOut = POOL.get('stock.shipment.out')
            ShipmentOutReturn = POOL.get('stock.shipment.out.return')

            with Transaction().set_context({'company': self.company.id}):
                shipment, = ShipmentOut.create([{
                    'customer': self.party.id,
                    'delivery_address': self.party.addresses[0].id,
                }])
                self.assertEqual(shipment.delivery_mode, 'ship')

                shipment_return, = ShipmentOutReturn.create([{
                    'customer': self.party.id,
                    'delivery_address': self.party.addresses[0].id,
                }])
                self.assertEqual(shipment_return.delivery_mode, 'ship')

    def test_1110_shipment_invoice_case_1(self):
        """
        Ensure that a posted invoice is created when a picked up order is
        processed.

        For the ship order, since nothing has been shipped, there should be
        no invoices
        """
        Date = POOL.get('ir.date')

        with Transaction().start(DB_NAME, USER, context=CONTEXT):
            self.setup_defaults()

            sale, = self.Sale.create([{
                'reference': 'Test Sale',
                'payment_term': self.payment_term,
                'currency': self.company.currency.id,
                'party': self.party.id,
                'invoice_address': self.party.addresses[0].id,
                'shipment_address': self.party.addresses[0].id,
                'sale_date': Date.today(),
                'company': self.company.id,

                # keep invoicing out of the way for this test's sake
                'invoice_method': 'shipment',
                'shipment_method': 'order',
            }])
            sale_line, = self.SaleLine.create([{
                'sale': sale,
                'type': 'line',
                'quantity': 2,
                'delivery_mode': 'ship',
                'unit': self.uom,
                'unit_price': 20000,
                'description': 'Test description',
                'product': self.product1.id
            }])

            # Quote, Confirm and Process the order
            self.Sale.quote([sale])
            self.Sale.confirm([sale])
            self.Sale.process([sale])

            self.assertEqual(len(sale.shipments), 1)
            self.assertEqual(sale.shipments[0].delivery_mode, 'ship')
            self.assertEqual(sale.shipments[0].state, 'waiting')

            self.assertEqual(len(sale.invoices), 0)

    def test_1120_shipment_invoice_case_2(self):
        """
        Ensure that a posted invoice is created when a picked up order is
        processed
        """
        Date = POOL.get('ir.date')

        with Transaction().start(DB_NAME, USER, context=CONTEXT):
            self.setup_defaults()

            sale, = self.Sale.create([{
                'reference': 'Test Sale',
                'payment_term': self.payment_term,
                'currency': self.company.currency.id,
                'party': self.party.id,
                'invoice_address': self.party.addresses[0].id,
                'shipment_address': self.party.addresses[0].id,
                'sale_date': Date.today(),
                'company': self.company.id,

                # keep invoicing out of the way for this test's sake
                'invoice_method': 'shipment',
                'shipment_method': 'order',
            }])
            sale_line, = self.SaleLine.create([{
                'sale': sale,
                'type': 'line',
                'quantity': 2,
                'delivery_mode': 'pick_up',
                'unit': self.uom,
                'unit_price': 20000,
                'description': 'Test description',
                'product': self.product1.id
            }])

            with Transaction().set_context({'company': self.company.id}):
                # Quote, Confirm and Process the order
                self.Sale.quote([sale])
                self.Sale.confirm([sale])
                self.Sale.process([sale])

                self.assertEqual(len(sale.shipments), 1)
                self.assertEqual(sale.shipments[0].delivery_mode, 'pick_up')
                self.assertEqual(sale.shipments[0].state, 'done')

                self.assertEqual(len(sale.invoices), 1)
                self.assertEqual(sale.invoices[0].state, 'posted')

    def test_1130_delivery_method_2shipping_case_3(self):
        """
        Ensure shipment method is respected by sale order processing.
        Ensures that there is only one invoice created and that it is posted.

        Case 3: Pick up + Ship order for same item
        """
        Date = POOL.get('ir.date')
        Shipment = POOL.get('stock.shipment.out')

        with Transaction().start(DB_NAME, USER, context=CONTEXT):
            self.setup_defaults()

            sale, = self.Sale.create([{
                'reference': 'Test Sale',
                'payment_term': self.payment_term,
                'currency': self.company.currency.id,
                'party': self.party.id,
                'invoice_address': self.party.addresses[0].id,
                'shipment_address': self.party.addresses[0].id,
                'sale_date': Date.today(),
                'company': self.company.id,

                # keep invoicing out of the way for this test's sake
                'invoice_method': 'shipment',
                'shipment_method': 'order',
            }])
            self.SaleLine.create([{
                'sale': sale,
                'type': 'line',
                'quantity': 2,
                'delivery_mode': 'pick_up',
                'unit': self.uom,
                'unit_price': 20000,
                'description': 'Picked Item',
                'product': self.product1.id
            }, {
                'sale': sale,
                'type': 'line',
                'quantity': 2,
                'delivery_mode': 'ship',
                'unit': self.uom,
                'unit_price': 20000,
                'description': 'Shipped Item',
                'product': self.product1.id
            }])

            with Transaction().set_context({'company': self.company.id}):
                # Quote, Confirm and Process the order
                self.Sale.quote([sale])
                self.Sale.confirm([sale])
                self.Sale.process([sale])

            self.assertEqual(len(sale.shipments), 2)
            for shipment in sale.shipments:
                if shipment.delivery_mode == 'pick_up':
                    self.assertEqual(shipment.state, 'done')
                elif shipment.delivery_mode == 'ship':
                    self.assertEqual(shipment.state, 'waiting')
                    delivery_shipment = shipment        # used later in test
                else:
                    self.fail('Invalid delivery mode')

            self.assertEqual(len(sale.invoices), 1)
            self.assertEqual(sale.invoices[0].state, 'posted')

            with Transaction().set_context({'company': self.company.id}):
                # Now process the delivered shipment as if its been shipped
                Shipment.assign_force([delivery_shipment])
                Shipment.pack([delivery_shipment])
                Shipment.done([delivery_shipment])

                self.assertEqual(len(sale.invoices), 2)
                self.assertEqual(sale.invoices[0].state, 'posted')
                self.assertEqual(sale.invoices[1].state, 'posted')

    def test_1140_serialize_recent_sales(self):
        """
        Test that sale order which are recently updated or create are on top.
        """
        Date = POOL.get('ir.date')

        with Transaction().start(DB_NAME, USER, context=CONTEXT):
            self.setup_defaults()

            with Transaction().set_context(shop=self.shop.id):
                sale1, = self.Sale.create([{
                    'reference': 'Test Sale 1',
                    'payment_term': self.payment_term,
                    'currency': self.company.currency.id,
                    'party': self.party.id,
                    'invoice_address': self.party.addresses[0].id,
                    'shipment_address': self.party.addresses[0].id,
                    'sale_date': Date.today(),
                    'company': self.company.id,
                }])
                sale2, = self.Sale.create([{
                    'reference': 'Test Sale 2',
                    'payment_term': self.payment_term,
                    'currency': self.company.currency.id,
                    'party': self.party.id,
                    'invoice_address': self.party.addresses[0].id,
                    'shipment_address': self.party.addresses[0].id,
                    'sale_date': Date.today(),
                    'company': self.company.id,
                }])

                sale3, = self.Sale.create([{
                    'reference': 'Test Sale 3',
                    'payment_term': self.payment_term,
                    'currency': self.company.currency.id,
                    'party': self.party.id,
                    'invoice_address': self.party.addresses[0].id,
                    'shipment_address': self.party.addresses[0].id,
                    'sale_date': Date.today(),
                    'company': self.company.id,
                }])
                sale4, = self.Sale.create([{
                    'reference': 'Test Sale 4',
                    'payment_term': self.payment_term,
                    'currency': self.company.currency.id,
                    'party': self.party.id,
                    'invoice_address': self.party.addresses[0].id,
                    'shipment_address': self.party.addresses[0].id,
                    'sale_date': Date.today(),
                    'company': self.company.id,
                }])

                saleLine1, = self.SaleLine.create([{
                    'sale': sale1,
                    'type': 'line',
                    'quantity': 2,
                    'delivery_mode': 'pick_up',
                    'unit': self.uom,
                    'unit_price': 20000,
                    'description': 'Picked Item',
                    'product': self.product1.id
                }])
                saleLine2, = self.SaleLine.create([{
                    'sale': sale2,
                    'type': 'line',
                    'quantity': 2,
                    'delivery_mode': 'pick_up',
                    'unit': self.uom,
                    'unit_price': 20000,
                    'description': 'Picked Item',
                    'product': self.product1.id
                }])
                saleLine3, = self.SaleLine.create([{
                    'sale': sale3,
                    'type': 'line',
                    'quantity': 2,
                    'delivery_mode': 'pick_up',
                    'unit': self.uom,
                    'unit_price': 20000,
                    'description': 'Picked Item',
                    'product': self.product1.id
                }])
                saleLine4, = self.SaleLine.create([{
                    'sale': sale4,
                    'type': 'line',
                    'quantity': 2,
                    'delivery_mode': 'pick_up',
                    'unit': self.uom,
                    'unit_price': 20000,
                    'description': 'Picked Item',
                    'product': self.product1.id
                }])

                rv = self.Sale.get_recent_sales()
                self.assertEqual(len(rv), 4)

                # Test serialized data
                self.assertIn('id', rv[0])
                self.assertIn('party', rv[0])
                self.assertIn('total_amount', rv[0])
                self.assertIn('create_date', rv[0])


def suite():
    """
    Define suite
    """
    test_suite = trytond.tests.test_tryton.suite()
    test_suite.addTests(
        unittest.TestLoader().loadTestsFromTestCase(TestSale)
    )
    return test_suite

if __name__ == '__main__':
    unittest.TextTestRunner(verbosity=2).run(suite())
