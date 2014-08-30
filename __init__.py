# -*- coding: utf-8 -*-
"""
    __init__.py

    :copyright: (c) 2014 by Openlabs Technologies & Consulting (P) Limited
    :license: BSD, see LICENSE for more details.
"""
from trytond.pool import Pool

from sale import Sale, SaleShop, SaleLine
from address import Address
from shipment import ShipmentOut, ShipmentOutReturn


def register():
    Pool.register(
        Sale,
        SaleLine,
        SaleShop,
        ShipmentOut,
        ShipmentOutReturn,
        Address,
        module='pos', type_='model'
    )
