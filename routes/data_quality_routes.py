from flask import Blueprint, render_template, redirect, url_for, session
from bson import ObjectId

import extensions as ext
from helpers.plan_rules import has_feature


data_quality_bp = Blueprint(
    "data_quality",
    __name__,
    url_prefix="/admin/data-quality"
)


def db():
    return ext.db


def admin_required():
    return "user_id" in session and session.get("role") == "admin_empresa"


def current_company_plan():
    company_id = session.get("company_id")

    if company_id:
        try:
            company = db()["companies"].find_one({
                "_id": ObjectId(company_id)
            })
        except Exception:
            company = None

        if company:
            return company.get("plan", "basic")

    return session.get("company_plan", "basic")


def deny_upgrade(message):
    session["upgrade_message"] = message
    return redirect(url_for("plans.company_plans"))


def require_plan_feature(feature, message):
    plan = current_company_plan()

    if not has_feature(plan, feature):
        return deny_upgrade(message)

    return None


def empty_text_filter(field):
    return {
        "$or": [
            {field: {"$exists": False}},
            {field: None},
            {field: ""},
            {field: {"$regex": r"^\s*$"}}
        ]
    }


def zero_or_empty_filter(field):
    return {
        "$or": [
            {field: {"$exists": False}},
            {field: None},
            {field: ""},
            {field: {"$regex": r"^\s*$"}},
            {field: 0},
            {field: 0.0}
        ]
    }


def company_filter(cid, condition):
    return {
        "$and": [
            {"company_id": cid},
            condition
        ]
    }


def get_samples(collection_name, cid, condition, limit=5):
    records = list(
        db()[collection_name]
        .find(company_filter(cid, condition))
        .limit(limit)
    )

    for r in records:
        r["_id"] = str(r["_id"])

    return records


@data_quality_bp.route("/")
def index():
    if not admin_required():
        return redirect(url_for("login"))

    blocked = require_plan_feature(
        "data_quality",
        "Tu plan actual no incluye Calidad de Datos. Mejora tu plan para usar esta sección."
    )

    if blocked:
        return blocked

    cid = session["company_id"]

    checks_config = [
        {
            "key": "productos_sin_precio",
            "title": "Productos sin precio",
            "description": "Productos sin precio, precio vacío o precio en cero.",
            "collection": "products",
            "condition": zero_or_empty_filter("price"),
            "icon": "bi-currency-dollar",
            "color": "bg-orange"
        },
        {
            "key": "productos_sin_stock",
            "title": "Productos sin stock",
            "description": "Productos sin stock registrado, vacío o en cero.",
            "collection": "products",
            "condition": zero_or_empty_filter("stock"),
            "icon": "bi-boxes",
            "color": "bg-green"
        },
        {
            "key": "productos_sin_proveedor",
            "title": "Productos sin proveedor",
            "description": "Productos sin proveedor registrado.",
            "collection": "products",
            "condition": empty_text_filter("provider"),
            "icon": "bi-truck",
            "color": "bg-red"
        },
        {
            "key": "ventas_sin_total",
            "title": "Ventas sin total",
            "description": "Ventas sin total registrado o con total en cero.",
            "collection": "sales",
            "condition": zero_or_empty_filter("total"),
            "icon": "bi-receipt",
            "color": "bg-orange"
        },
        {
            "key": "clientes_sin_correo",
            "title": "Clientes sin correo",
            "description": "Clientes sin correo electrónico registrado.",
            "collection": "clients",
            "condition": empty_text_filter("email"),
            "icon": "bi-person-lines-fill",
            "color": "bg-blue"
        }
    ]

    checks = []

    for item in checks_config:
        collection = item["collection"]
        condition = item["condition"]

        count = db()[collection].count_documents(
            company_filter(cid, condition)
        )

        samples = get_samples(
            collection,
            cid,
            condition,
            limit=5
        )

        checks.append({
            **item,
            "count": count,
            "samples": samples
        })

    total_issues = sum(item["count"] for item in checks)

    totals = {
        "products": db()["products"].count_documents({"company_id": cid}),
        "sales": db()["sales"].count_documents({"company_id": cid}),
        "clients": db()["clients"].count_documents({"company_id": cid}),
    }

    return render_template(
        "data_quality/index.html",
        checks=checks,
        total_issues=total_issues,
        totals=totals
    )