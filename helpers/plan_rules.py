PLANS = {
    "basic": {
        "name": "Básico",
        "price": 199,
        "max_users": 2,
        "features": {
            "products": True,
            "admin_panel": True,
            "sales": True,
            "credit_sales": False,
            "reports": False,
            "executive_reports": False,
            "data_quality": False,
            "manual_backups": True,
            "custom_backups": False,
            "auto_backups": False,
            "pdf_notes": False,
            "pdf_branding": False,
            "pdf_logo": False,
            "multi_company": False,
            "support_basic": True,
            "support_priority": False,
            "support_premium": False,
        }
    },

    "professional": {
        "name": "Profesional",
        "price": 499,
        "max_users": 5,
        "features": {
            "products": True,
            "admin_panel": True,
            "sales": True,
            "credit_sales": True,
            "reports": True,
            "executive_reports": False,
            "data_quality": True,
            "manual_backups": True,
            "custom_backups": True,
            "auto_backups": False,
            "pdf_notes": True,
            "pdf_branding": False,
            "pdf_logo": False,
            "multi_company": False,
            "support_basic": True,
            "support_priority": True,
            "support_premium": False,
        }
    },

    "enterprise": {
        "name": "Empresarial",
        "price": 999,
        "max_users": None,  # None = usuarios ilimitados
        "features": {
            "products": True,
            "admin_panel": True,
            "sales": True,
            "credit_sales": True,
            "reports": True,
            "executive_reports": True,
            "data_quality": True,
            "manual_backups": True,
            "custom_backups": True,
            "auto_backups": True,
            "pdf_notes": True,
            "pdf_branding": True,
            "pdf_logo": True,
            "multi_company": True,
            "support_basic": True,
            "support_priority": True,
            "support_premium": True,
        }
    }
}


def get_plan(plan_key):
    return PLANS.get(plan_key or "basic", PLANS["basic"])


def has_feature(plan_key, feature):
    plan = get_plan(plan_key)
    return plan["features"].get(feature, False)


def plan_name(plan_key):
    return get_plan(plan_key)["name"]


def plan_price(plan_key):
    return get_plan(plan_key)["price"]


def max_users(plan_key):
    return get_plan(plan_key)["max_users"]


def get_plan_limit(plan_key, limit_name):
    plan = get_plan(plan_key)

    if limit_name == "users":
        return plan.get("max_users")

    return None