# -*- coding: utf-8 -*-
# Copyright 2025 HungryDev
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
{
    "name": "Invoice UBL & Bank Statement Export",
    "version": "18.0.1.1.0",
    "category": "Accounting/Accounting",
    "summary": "Bulk export invoices to UBL XML and bank statements to PDF with quarterly auto-send",
    "author": "HungryDev",
    "website": "https://github.com/HungryDevMC/odoo-kwartaalaangifte-automation",
    "license": "LGPL-3",
    "depends": [
        "account",
        "account_edi_ubl_cii",
        "mail",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron_data.xml",
        "views/res_config_settings_views.xml",
        "wizard/account_invoice_ubl_export_wizard_views.xml",
        "views/menu_views.xml",
    ],
    "images": [
        "static/description/screenshot1.png",
        "static/description/screenshot2.png",
        "static/description/screenshot3.png",
        "static/description/screenshot4.png",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
    "support": "info@gesp.be",
    "price": 25,
    "currency": "EUR",
}
