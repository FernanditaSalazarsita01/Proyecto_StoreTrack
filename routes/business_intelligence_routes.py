from __future__ import annotations

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

import extensions as ext
from helpers.business_intelligence.chat import answer_business_question
from helpers.business_intelligence.dashboard import build_dashboard

business_intelligence_bp = Blueprint(
    "business_intelligence",
    __name__,
    url_prefix="/inteligencia-negocio",
)


def logged_company_required() -> bool:
    return bool(session.get("user_id") and session.get("company_id"))


@business_intelligence_bp.route("/", methods=["GET"])
def index():
    if not logged_company_required():
        return redirect(url_for("login"))

    dashboard = build_dashboard(ext.db, session["company_id"])
    return render_template(
        "business_intelligence/index.html",
        dashboard=dashboard,
        company_name=session.get("company_name", "Mi empresa"),
    )


@business_intelligence_bp.route("/chat", methods=["POST"])
def chat():
    if not logged_company_required():
        return jsonify({"ok": False, "answer": "La sesión ha expirado."}), 401

    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question", "")).strip()

    if not question:
        return jsonify({"ok": False, "answer": "Escribe una pregunta para continuar."}), 400

    if len(question) > 300:
        return jsonify({"ok": False, "answer": "La pregunta es demasiado larga."}), 400

    result = answer_business_question(ext.db, session["company_id"], question)
    return jsonify({"ok": True, **result})
