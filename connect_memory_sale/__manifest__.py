{
    "name": "Connect Memory — Sale & Payment Behavior",
    "version": "1.0.0",
    "category": "Phone",
    "summary": "Memory events for sale orders, invoices, payments and payment-behavior digest.",
    "author": "Oduist",
    "website": "https://oduist.com",
    "depends": ["connect_memory", "sale", "account"],
    "data": ["data/memory_sale_data.xml"],
    "license": "Other proprietary",
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
}
