from datetime import datetime

from bson import ObjectId
from flask import Blueprint, render_template, request, redirect, url_for, session, flash

import extensions as ext
from helpers.plan_rules import PLANS


plan_bp = Blueprint("plans", __name__)


def db():
    return ext.db


def login_required():
    return session.get("user_id") and session.get("company_id")


def company_id():
    return session.get("company_id")


def is_admin_empresa():
    return session.get("role") == "admin_empresa"


def get_company_oid():
    try:
        return ObjectId(company_id())
    except Exception:
        return None


def get_company():
    cid = get_company_oid()

    if not cid:
        return None

    return db()["companies"].find_one({
        "_id": cid
    })


def get_current_plan():
    company = get_company()

    if company:
        return company.get("plan", "basic")

    return session.get("company_plan", "basic")


def count_company_users():
    return db()["users"].count_documents({
        "company_id": company_id()
    })


@plan_bp.route("/empresa/planes")
def company_plans():
    if not login_required():
        return redirect(url_for("login"))

    current_plan = get_current_plan()

    return render_template(
        "company_plans.html",
        plans=PLANS,
        current_plan=current_plan
    )


@plan_bp.route("/empresa/planes/select", methods=["POST"])
def select_company_plan():
    if not login_required():
        return redirect(url_for("login"))

    if not is_admin_empresa():
        flash("Solo el administrador de la empresa puede cambiar el plan.", "warning")
        return redirect(url_for("plans.company_plans"))

    selected_plan = request.form.get("plan", "basic").strip()

    if selected_plan not in PLANS:
        flash("Plan inválido.", "danger")
        return redirect(url_for("plans.company_plans"))

    selected_plan_data = PLANS[selected_plan]
    selected_max_users = selected_plan_data.get("max_users")

    current_users = count_company_users()

    if selected_max_users is not None and current_users > selected_max_users:
        flash(
            f"No puedes cambiar al plan {selected_plan_data['name']} porque actualmente tienes "
            f"{current_users} usuarios registrados y este plan permite máximo {selected_max_users}. "
            "Elimina usuarios o selecciona un plan superior.",
            "warning"
        )
        return redirect(url_for("plans.company_plans"))

    cid = get_company_oid()

    if not cid:
        flash("No se pudo identificar la empresa actual.", "danger")
        return redirect(url_for("plans.company_plans"))

    db()["companies"].update_one(
        {
            "_id": cid
        },
        {
            "$set": {
                "plan": selected_plan,
                "plan_name": selected_plan_data["name"],
                "plan_price": selected_plan_data.get("price", 0),
                "plan_updated_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
        }
    )

    session["company_plan"] = selected_plan
    session["company_plan_name"] = selected_plan_data["name"]

    flash(f"Plan actualizado a {selected_plan_data['name']} ✅", "success")
    return redirect(url_for("plans.company_plans"))