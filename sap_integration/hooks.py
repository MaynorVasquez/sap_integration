app_name = "sap_integration"
app_title = "Sap Integration"
app_publisher = "maynor"
app_description = "conexion a sap"
app_email = "informatica@yaesta.com.gt"
app_license = "mit"


scheduler_events = {
    "cron": {
        "0 2 * * *": [
            "sap_integration.job.job_master.job_secuenciales"
        ],
        # Job que corre de lunes a sábado de 07:00 a 19:00, cada hora exacta
        "0 7-19 * * 1-6": [
            "sap_integration.job.sap_procesar_facturas_pendientes.procesar_facturas_pendientes"
        ],
        #job que se ejecuta todos los días para sincronizar los clientes y proveedores todo los días
        "*/30 * * * *": [
            "sap_integration.api.sap_clientes.sincronizar_clientes_desde_sap"
        ],
        #job que sincroniza todos los articulos todos los días
        "*/30 * * * *": [
            "sap_integration.api.sap_articulos.sincronizar_lista_articulos"
        ],
        #Job que se actualiza a cada 5 minutos, para buscar las nuevas ordenes de venta en sap
        "*/5 * * * *": [
            "sap_integration.api.sap_orden_venta_erpnext.sincronizar_orden_venta_erpnext"
        ],
        #Job que se actualiza a cada 5 minutos, para buscar las nuevas notas de entrega en sap
        "*/5 * * * *": [
            "sap_integration.api.sap_notas_entregas_erpnext.sincronizar_notas_entregas_erpnext"
        ],
        #Job que se actualiza a cada 5 minutos, para buscar las nuevas facturas en sap
        "*/5 * * * *": [
            "sap_integration.api.sap_facturas_erpnext.sincronizar_facturas_erpnext"
        ]

    }
}


# scheduler_events = {
#     "all": [
#         "sap_integration.api.scheduler.run_sap_schedulers"
#     ]
# }

doc_events = {
    "Sales Order": {
        "on_submit": "sap_integration.api.sap_orden_de_venta.enviar_ov"
    }
}

fixtures = [
    "Property Setter",
    {
        "dt": "Custom Field",
        "filters": [
            ["name", "in", [
                "Customer-custom_cardcode",
                "Customer-custom_company",
                "Supplier-custom_cardcode",
                "Supplier-custom_company",
                "Address-custom_cardcode",
                "Address-custom_rownum",
                "Address-custom_company",
                "Sales Order-custom_docnum",
                "Sales Order-custom_docentry",
                "Sales Order-custom_comentarios",
                "Sales Order Item-custom_linenum",
                "Sales Order-custom_docduedate",
                "Item-custom_ean",
                "Item-custom_itemcode",
                "Warehouse-custom_warehousecode",
                "Item Group-custom_number",
                "UOM Category-custom_absentry",
                "UOM Category-custom_company",
                "UOM-custom_absentry",
                "UOM-custom_company",
                "Customer Group-custom_code",
                "Price List-custom_pricelistno",
                "Sales Person-custom_salesemployeecode",
                "Sales Person-custom_company",
                "POS Profile-custom_establecimiento_fel",
                "POS Profile-custom_serie_sap",
                "Sales Invoice-custom_docnum",
                "Sales Invoice-custom_docentry",
                "Sales Invoice Item-custom_linenum",
                "Batch-custom_batchnum",
                "Price List-custom_company",
                "Sales Taxes and Charges Template-custom_taxcode",
                "Delivery Note Item-custom_linenum",
                "Delivery Note-custom_docnum",
                "Delivery Note-custom_docnum",
                "Delivery Note-custom_docentry",
                "Delivery Note Item-custom_linenum"
                

            ]]
        ]
    },
    {
        "dt": "Mapeo Almacenes SAP"
    },
    {
        "dt": "Mapeo Articulo SAP"
    },
    {
        "dt": "Mapeo Articulos Grupo SAP"
    },
    {
        "dt": "Mapeo Categoria UOM"
    },
    {
        "dt": "Mapeo Cliente"
    },
    {
        "dt": "Mapeo Cliente Direcciones"
    },
    {
        "dt": "Mapeo Clientes Grupo SAP"
    },
    {
        "dt": "Mapeo Factura SAP"
    },
    {
        "dt": "Mapeo Inventario SAP"
    },
    {
        "dt": "Mapeo Lista De Precios SAP"
    },
    {
        "dt": "Mapeo UOM"
    },
    {
        "dt": "Mapeo UOM factores conversion SAP"
    },
    {
        "dt": "Mapeo Vendedores SAP"
    },
    {
        "dt": "Mapeo Orden De Venta SAP"
    },
    {
        "dt": "Mapeo Precios Especiales SN SAP"
    },
    {
        "dt": "Mapeo Numero de Catalogo Interno"
    },
    {
        "dt": "Clientes validad SAP"
    },
    {
        "dt": "Workspace",
        "filters": [
            ["name", "in", ["SAP Integration"]]
        ]
    }
]


# doc_events = {
#     "Sales Invoice": {
#         "validate": "sap_integration.hooks.pos.validate_stock_before_pos_submit"
#     }
# }

#app_include_js = "/assets/sap_integration/js/pos_event.js"


# app_include_js = [
#     "sap_integration/public/js/sap_credentials.js"
# ]

# fixtures = ["Module Def"]  # ¡Exactamente "Module Def"!

# # hooks.py
# scheduled_events = {
#     "daily": [
#         ("sap_integration.tu_modulo.sincronizar_clientes_desde_sap", "40 13 * * *")  # 05:00 AM
#     ]
# }

# doctypes = ["Configuracion SAP", "Mapeo Clientes SAP"]

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "sap_integration",
# 		"logo": "/assets/sap_integration/logo.png",
# 		"title": "Sap Integration",
# 		"route": "/sap_integration",
# 		"has_permission": "sap_integration.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/sap_integration/css/sap_integration.css"
# app_include_js = "/assets/sap_integration/js/sap_integration.js"

# include js, css files in header of web template
# web_include_css = "/assets/sap_integration/css/sap_integration.css"
# web_include_js = "/assets/sap_integration/js/sap_integration.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "sap_integration/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "sap_integration/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "sap_integration.utils.jinja_methods",
# 	"filters": "sap_integration.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "sap_integration.install.before_install"
# after_install = "sap_integration.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "sap_integration.uninstall.before_uninstall"
# after_uninstall = "sap_integration.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "sap_integration.utils.before_app_install"
# after_app_install = "sap_integration.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "sap_integration.utils.before_app_uninstall"
# after_app_uninstall = "sap_integration.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "sap_integration.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"sap_integration.tasks.all"
# 	],
# 	"daily": [
# 		"sap_integration.tasks.daily"
# 	],
# 	"hourly": [
# 		"sap_integration.tasks.hourly"
# 	],
# 	"weekly": [
# 		"sap_integration.tasks.weekly"
# 	],
# 	"monthly": [
# 		"sap_integration.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "sap_integration.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "sap_integration.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "sap_integration.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["sap_integration.utils.before_request"]
# after_request = ["sap_integration.utils.after_request"]

# Job Events
# ----------
# before_job = ["sap_integration.utils.before_job"]
# after_job = ["sap_integration.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"sap_integration.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

