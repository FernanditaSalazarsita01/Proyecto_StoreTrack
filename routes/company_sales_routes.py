import json
from datetime import datetime
from io import BytesIO
import os
from reportlab.lib.utils import ImageReader
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, send_file, current_app
from bson import ObjectId
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

import extensions as ext
from helpers.plan_rules import has_feature



company_sales_bp = Blueprint("company_sales", __name__)


def db():
    return ext.db


def login_required():
    return session.get("user_id") and session.get("company_id")


def company_id():
    return session.get("company_id")


def current_company_plan():
    cid = company_id()

    if cid:
        try:
            company = db()["companies"].find_one({"_id": ObjectId(cid)})
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


def company_pdf_branding():
    plan = current_company_plan()

    if not has_feature(plan, "pdf_branding"):
        return {}

    try:
        company = db()["companies"].find_one({"_id": ObjectId(company_id())})
    except Exception:
        company = None

    if not company:
        return {}

    return company.get("pdf_branding", {}) or {}


@company_sales_bp.route("/nueva-venta", methods=["GET"])
def new_sale():
    if not login_required():
        return redirect(url_for("login"))

    cid = company_id()

    products = list(db()["products"].find({
        "company_id": cid,
        "stock": {"$gt": 0}
    }).sort("name", 1))

    for p in products:
        p["_id"] = str(p["_id"])
        p["price"] = float(p.get("price", 0) or 0)
        p["stock"] = int(p.get("stock", 0) or 0)

    clients = list(db()["clients"].find({
        "company_id": cid
    }).sort("name", 1))

    clean_clients = []
    for c in clients:
        clean_clients.append({
            "_id": str(c.get("_id")),
            "name": c.get("name", ""),
            "phone": c.get("phone", ""),
            "address": c.get("address", ""),
            "email": c.get("email", "")
        })

    return render_template(
        "sales/new.html",
        products=products,
        clients=clean_clients,
        now_str=datetime.now().strftime("%d/%m/%Y %H:%M")
    )


@company_sales_bp.route("/sales/create", methods=["POST"])
def create_sale():
    if not login_required():
        return redirect(url_for("login"))

    cid = company_id()

    sale_type = request.form.get("sale_type", "cash").strip()
    client_mode = request.form.get("client_mode", "quick").strip()
    client_id = request.form.get("client_id", "").strip()

    customer_name = request.form.get("customer_name", "").strip()
    customer_email = request.form.get("customer_email", "").strip()
    customer_phone = request.form.get("customer_phone", "").strip()
    customer_address = request.form.get("customer_address", "").strip()

    new_client_name = request.form.get("new_client_name", "").strip()
    new_client_email = request.form.get("new_client_email", "").strip()
    new_client_phone = request.form.get("new_client_phone", "").strip()
    new_client_address = request.form.get("new_client_address", "").strip()

    items_json = request.form.get("items_json", "[]")

    if sale_type not in ["cash", "credit"]:
        sale_type = "cash"

    if client_mode not in ["quick", "existing", "new"]:
        client_mode = "quick"

    # =========================
    # VALIDACIÓN CRÉDITO
    # =========================
    if sale_type == "credit":
        blocked = require_plan_feature(
            "credit_sales",
            "Tu plan actual no incluye ventas a crédito. Mejora tu plan para registrar ventas a crédito."
        )

        if blocked:
            return blocked

        if client_mode == "quick":
            flash("Para una venta a crédito debes seleccionar o registrar un cliente.", "warning")
            return redirect(url_for("company_sales.new_sale"))

    # =========================
    # CLIENTE EXISTENTE
    # =========================
    if client_mode == "existing":
        if not client_id:
            flash("Selecciona un cliente.", "warning")
            return redirect(url_for("company_sales.new_sale"))

        try:
            selected_client = db()["clients"].find_one({
                "_id": ObjectId(client_id),
                "company_id": cid
            })
        except Exception:
            selected_client = None

        if not selected_client:
            flash("El cliente seleccionado no existe o no pertenece a esta empresa.", "danger")
            return redirect(url_for("company_sales.new_sale"))

        customer_name = selected_client.get("name", "")
        customer_email = selected_client.get("email", "")
        customer_phone = selected_client.get("phone", "")
        customer_address = selected_client.get("address", "")

    # =========================
    # CLIENTE NUEVO
    # =========================
    elif client_mode == "new":
        if not new_client_name:
            flash("Ingresa el nombre del nuevo cliente.", "warning")
            return redirect(url_for("company_sales.new_sale"))

        new_client_doc = {
            "company_id": cid,
            "company_name": session.get("company_name", ""),
            "name": new_client_name,
            "email": new_client_email,
            "phone": new_client_phone,
            "address": new_client_address,
            "notes": "",
            "is_active": True,
            "created_by": session.get("user_id"),
            "created_by_name": session.get("user_name", ""),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }

        inserted_client = db()["clients"].insert_one(new_client_doc)

        client_id = str(inserted_client.inserted_id)
        customer_name = new_client_name
        customer_email = new_client_email
        customer_phone = new_client_phone
        customer_address = new_client_address

    # =========================
    # VENTA RÁPIDA
    # =========================
    elif client_mode == "quick":
        client_id = ""

        if not customer_name:
            customer_name = "Venta rápida"

    if sale_type == "credit" and not customer_name:
        flash("Para una venta a crédito el cliente es obligatorio.", "warning")
        return redirect(url_for("company_sales.new_sale"))

    # =========================
    # VALIDAR PRODUCTOS
    # =========================
    try:
        items = json.loads(items_json)
    except Exception:
        flash("Detalle de venta inválido.", "danger")
        return redirect(url_for("company_sales.new_sale"))

    if not items:
        flash("Agrega al menos un producto.", "warning")
        return redirect(url_for("company_sales.new_sale"))

    sale_items = []
    subtotal = 0

    for item in items:
        product_id = item.get("product_id")

        try:
            qty = int(item.get("qty", 0) or 0)
        except Exception:
            qty = 0

        if qty <= 0:
            flash("Cantidad inválida en uno de los productos.", "warning")
            return redirect(url_for("company_sales.new_sale"))

        try:
            product_oid = ObjectId(product_id)
        except Exception:
            flash("Uno de los productos seleccionados es inválido.", "danger")
            return redirect(url_for("company_sales.new_sale"))

        product = db()["products"].find_one({
            "_id": product_oid,
            "company_id": cid
        })

        if not product:
            flash("Uno de los productos no existe o no pertenece a esta empresa.", "danger")
            return redirect(url_for("company_sales.new_sale"))

        current_stock = int(product.get("stock", 0) or 0)

        if qty > current_stock:
            flash(
                f"Stock insuficiente para {product.get('name', '')}. Disponible: {current_stock}",
                "warning"
            )
            return redirect(url_for("company_sales.new_sale"))

        price = float(product.get("price", 0) or 0)
        line_total = price * qty
        subtotal += line_total

        sale_items.append({
            "product_id": str(product["_id"]),
            "name": product.get("name", ""),
            "sku": product.get("sku", ""),
            "unit": product.get("unit", ""),
            "price": price,
            "qty": qty,
            "line_total": line_total
        })

    total = round(subtotal, 2)

    # =========================
    # ESTADO DE PAGO
    # =========================
    if sale_type == "credit":
        payment_status = "pending"
        is_paid = False
        paid_at = None
        amount_paid = 0
        balance = total
        payments = []
    else:
        payment_status = "paid"
        is_paid = True
        paid_at = datetime.utcnow()
        amount_paid = total
        balance = 0
        payments = [
            {
                "amount": total,
                "note": "Pago total al registrar venta",
                "created_by": session.get("user_id"),
                "created_by_name": session.get("user_name", ""),
                "created_at": datetime.utcnow()
            }
        ]

    # =========================
    # DOCUMENTO DE VENTA
    # =========================
    sale_doc = {
        "company_id": cid,
        "company_name": session.get("company_name", ""),

        "sale_type": sale_type,
        "payment_status": payment_status,
        "is_paid": is_paid,
        "paid_at": paid_at,

        "amount_paid": round(amount_paid, 2),
        "balance": round(balance, 2),
        "payments": payments,

        "customer": {
            "client_id": client_id if client_id else None,
            "name": customer_name,
            "email": customer_email,
            "phone": customer_phone,
            "address": customer_address
        },

        "items": sale_items,
        "subtotal": total,
        "total": total,

        "created_by": session.get("user_id"),
        "created_by_name": session.get("user_name", ""),
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }

    db()["sales"].insert_one(sale_doc)

    # =========================
    # DESCONTAR STOCK
    # =========================
    for item in sale_items:
        db()["products"].update_one(
            {
                "_id": ObjectId(item["product_id"]),
                "company_id": cid
            },
            {
                "$inc": {
                    "stock": -int(item["qty"])
                },
                "$set": {
                    "updated_at": datetime.utcnow()
                }
            }
        )

    if sale_type == "credit":
        flash("Venta a crédito registrada como pendiente ✅", "success")
        return redirect(url_for("company_sales.credit_sales_list"))

    flash("Venta pagada registrada correctamente ✅", "success")
    return redirect(url_for("company_sales.sales_list"))


@company_sales_bp.route("/ventas")
def sales_list():
    if not login_required():
        return redirect(url_for("login"))

    sales = list(
        db()["sales"]
        .find({
            "company_id": company_id(),
            "payment_status": "paid"
        })
        .sort("created_at", -1)
    )

    for s in sales:
        s["_id"] = str(s["_id"])

    return render_template("sales/ventas.html", sales=sales)


@company_sales_bp.route("/credito")
def credit_sales_list():
    if not login_required():
        return redirect(url_for("login"))

    blocked = require_plan_feature(
        "credit_sales",
        "Tu plan actual no incluye ventas a crédito. Mejora tu plan para usar esta sección."
    )

    if blocked:
        return blocked

    q = request.args.get("q", "").strip()

    query = {
        "company_id": company_id(),
        "payment_status": "pending"
    }

    if q:
        query["$or"] = [
            {"customer.name": {"$regex": q, "$options": "i"}},
            {"customer.email": {"$regex": q, "$options": "i"}},
            {"customer.phone": {"$regex": q, "$options": "i"}},
        ]

    sales = list(
        db()["sales"]
        .find(query)
        .sort("created_at", -1)
    )

    for s in sales:
        s["_id"] = str(s["_id"])

        total = float(s.get("total", 0) or 0)
        amount_paid = float(s.get("amount_paid", 0) or 0)

        if "balance" not in s:
            s["balance"] = total - amount_paid

    return render_template(
        "sales/credito.html",
        sales=sales,
        q=q
    )


@company_sales_bp.route("/credito/<sale_id>", methods=["GET"])
def credit_sale_detail(sale_id):
    if not login_required():
        return redirect(url_for("login"))

    blocked = require_plan_feature(
        "credit_sales",
        "Tu plan actual no incluye ventas a crédito. Mejora tu plan para consultar el detalle."
    )

    if blocked:
        return blocked

    try:
        sale_oid = ObjectId(sale_id)
    except Exception:
        flash("Venta inválida.", "danger")
        return redirect(url_for("company_sales.credit_sales_list"))

    sale = db()["sales"].find_one({
        "_id": sale_oid,
        "company_id": company_id(),
        "sale_type": "credit"
    })

    if not sale:
        flash("Venta a crédito no encontrada.", "danger")
        return redirect(url_for("company_sales.credit_sales_list"))

    sale["_id"] = str(sale["_id"])

    total = float(sale.get("total", 0) or 0)
    amount_paid = float(sale.get("amount_paid", 0) or 0)
    balance = float(sale.get("balance", total - amount_paid) or 0)

    if balance < 0:
        balance = 0

    sale["amount_paid"] = amount_paid
    sale["balance"] = balance

    return render_template("sales/credito_detalle.html", sale=sale)


@company_sales_bp.route("/sales/<sale_id>/pay", methods=["POST"])
def pay_credit_sale(sale_id):
    if not login_required():
        return redirect(url_for("login"))

    blocked = require_plan_feature(
        "credit_sales",
        "Tu plan actual no incluye ventas a crédito. Mejora tu plan para marcar ventas a crédito como pagadas."
    )

    if blocked:
        return blocked

    try:
        sale_oid = ObjectId(sale_id)
    except Exception:
        flash("Venta inválida.", "danger")
        return redirect(url_for("company_sales.credit_sales_list"))

    sale = db()["sales"].find_one({
        "_id": sale_oid,
        "company_id": company_id(),
        "sale_type": "credit",
        "payment_status": "pending"
    })

    if not sale:
        flash("Venta a crédito no encontrada o ya fue liquidada.", "danger")
        return redirect(url_for("company_sales.credit_sales_list"))

    total = float(sale.get("total", 0) or 0)
    current_paid = float(sale.get("amount_paid", 0) or 0)
    remaining = total - current_paid

    if remaining < 0:
        remaining = 0

    payment_doc = {
        "amount": round(remaining, 2),
        "note": "Liquidación total de la venta a crédito",
        "created_by": session.get("user_id"),
        "created_by_name": session.get("user_name", ""),
        "created_at": datetime.utcnow()
    }

    db()["sales"].update_one(
        {
            "_id": sale_oid,
            "company_id": company_id()
        },
        {
            "$set": {
                "amount_paid": total,
                "balance": 0,
                "payment_status": "paid",
                "is_paid": True,
                "paid_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            },
            "$push": {
                "payments": payment_doc
            }
        }
    )

    flash("Venta marcada como pagada correctamente ✅", "success")
    return redirect(url_for("company_sales.sales_list"))


@company_sales_bp.route("/credito/<sale_id>/abonar", methods=["POST"])
def add_credit_payment(sale_id):
    if not login_required():
        return redirect(url_for("login"))

    blocked = require_plan_feature(
        "credit_sales",
        "Tu plan actual no incluye ventas a crédito. Mejora tu plan para registrar abonos."
    )

    if blocked:
        return blocked

    try:
        sale_oid = ObjectId(sale_id)
    except Exception:
        flash("Venta inválida.", "danger")
        return redirect(url_for("company_sales.credit_sales_list"))

    try:
        amount = float(request.form.get("amount", 0) or 0)
    except Exception:
        amount = 0

    note = request.form.get("note", "").strip()

    if amount <= 0:
        flash("Ingresa un monto válido para abonar.", "warning")
        return redirect(url_for("company_sales.credit_sale_detail", sale_id=sale_id))

    sale = db()["sales"].find_one({
        "_id": sale_oid,
        "company_id": company_id(),
        "sale_type": "credit",
        "payment_status": "pending"
    })

    if not sale:
        flash("Venta a crédito no encontrada o ya fue liquidada.", "danger")
        return redirect(url_for("company_sales.credit_sales_list"))

    total = float(sale.get("total", 0) or 0)
    current_paid = float(sale.get("amount_paid", 0) or 0)
    new_paid = current_paid + amount

    if new_paid >= total:
        new_paid = total
        new_balance = 0
        payment_status = "paid"
        is_paid = True
        paid_at = datetime.utcnow()
    else:
        new_balance = total - new_paid
        payment_status = "pending"
        is_paid = False
        paid_at = None

    payment_doc = {
        "amount": round(amount, 2),
        "note": note,
        "created_by": session.get("user_id"),
        "created_by_name": session.get("user_name", ""),
        "created_at": datetime.utcnow()
    }

    update_set = {
        "amount_paid": round(new_paid, 2),
        "balance": round(new_balance, 2),
        "payment_status": payment_status,
        "is_paid": is_paid,
        "updated_at": datetime.utcnow()
    }

    if paid_at:
        update_set["paid_at"] = paid_at

    db()["sales"].update_one(
        {
            "_id": sale_oid,
            "company_id": company_id()
        },
        {
            "$set": update_set,
            "$push": {
                "payments": payment_doc
            }
        }
    )

    if payment_status == "paid":
        flash("Venta liquidada correctamente ✅", "success")
        return redirect(url_for("company_sales.sales_list"))

    flash("Abono registrado correctamente ✅", "success")
    return redirect(url_for("company_sales.credit_sale_detail", sale_id=sale_id))


@company_sales_bp.route("/credito/<sale_id>/liquidar", methods=["POST"])
def liquidate_credit_sale(sale_id):
    if not login_required():
        return redirect(url_for("login"))

    blocked = require_plan_feature(
        "credit_sales",
        "Tu plan actual no incluye ventas a crédito. Mejora tu plan para liquidar ventas a crédito."
    )

    if blocked:
        return blocked

    try:
        sale_oid = ObjectId(sale_id)
    except Exception:
        flash("Venta inválida.", "danger")
        return redirect(url_for("company_sales.credit_sales_list"))

    sale = db()["sales"].find_one({
        "_id": sale_oid,
        "company_id": company_id(),
        "sale_type": "credit",
        "payment_status": "pending"
    })

    if not sale:
        flash("Venta a crédito no encontrada o ya fue liquidada.", "danger")
        return redirect(url_for("company_sales.credit_sales_list"))

    total = float(sale.get("total", 0) or 0)
    current_paid = float(sale.get("amount_paid", 0) or 0)
    remaining = total - current_paid

    if remaining < 0:
        remaining = 0

    payment_doc = {
        "amount": round(remaining, 2),
        "note": "Liquidación total de la venta a crédito",
        "created_by": session.get("user_id"),
        "created_by_name": session.get("user_name", ""),
        "created_at": datetime.utcnow()
    }

    db()["sales"].update_one(
        {
            "_id": sale_oid,
            "company_id": company_id()
        },
        {
            "$set": {
                "amount_paid": total,
                "balance": 0,
                "payment_status": "paid",
                "is_paid": True,
                "paid_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            },
            "$push": {
                "payments": payment_doc
            }
        }
    )

    flash("Venta liquidada correctamente ✅", "success")
    return redirect(url_for("company_sales.sales_list"))


def money(value):
    try:
        return f"${float(value or 0):,.2f}"
    except Exception:
        return "$0.00"


def safe_text(value):
    return str(value or "").strip()


def draw_wrapped_text(pdf, text, x, y, max_chars=85, line_height=11):
    text = safe_text(text)

    if not text:
        return y

    lines = []
    current = ""

    for word in text.split():
        if len(current + " " + word) <= max_chars:
            current = (current + " " + word).strip()
        else:
            lines.append(current)
            current = word

    if current:
        lines.append(current)

    for line in lines:
        pdf.drawString(x, y, line)
        y -= line_height

    return y


def get_sale_for_pdf(sale_id):
    try:
        sale_oid = ObjectId(sale_id)
    except Exception:
        return None

    sale = db()["sales"].find_one({
        "_id": sale_oid,
        "company_id": company_id()
    })

    if not sale:
        return None

    sale["_id"] = str(sale["_id"])

    total = float(sale.get("total", 0) or 0)
    amount_paid = float(sale.get("amount_paid", total if sale.get("payment_status") == "paid" else 0) or 0)
    balance = float(sale.get("balance", total - amount_paid) or 0)

    if balance < 0:
        balance = 0

    sale["amount_paid"] = amount_paid
    sale["balance"] = balance

    return sale


@company_sales_bp.route("/sales/<sale_id>/pdf/ticket")
def sale_ticket_pdf(sale_id):
    if not login_required():
        return redirect(url_for("login"))

    sale = get_sale_for_pdf(sale_id)

    if not sale:
        flash("Venta no encontrada.", "danger")
        return redirect(url_for("company_sales.sales_list"))

    output = BytesIO()

    width = 80 * mm
    height = 220 * mm

    pdf = canvas.Canvas(output, pagesize=(width, height))

    y = height - 15 * mm

    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawCentredString(width / 2, y, "STORE TRACK")
    y -= 12

    pdf.setFont("Helvetica", 8)
    pdf.drawCentredString(width / 2, y, safe_text(sale.get("company_name", "")))
    y -= 16

    pdf.line(8 * mm, y, width - 8 * mm, y)
    y -= 12

    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(8 * mm, y, "TICKET DE VENTA")
    y -= 11

    pdf.setFont("Helvetica", 7)
    pdf.drawString(8 * mm, y, f"Folio: {sale.get('_id')}")
    y -= 10

    created_at = sale.get("created_at")
    fecha = created_at.strftime("%d/%m/%Y %H:%M") if created_at else ""

    pdf.drawString(8 * mm, y, f"Fecha: {fecha}")
    y -= 10

    cliente = sale.get("customer", {}).get("name", "Venta rápida")
    pdf.drawString(8 * mm, y, f"Cliente: {cliente}")
    y -= 12

    estado = "PAGADA" if sale.get("payment_status") == "paid" else "PENDIENTE"
    pdf.drawString(8 * mm, y, f"Estado: {estado}")
    y -= 14

    pdf.line(8 * mm, y, width - 8 * mm, y)
    y -= 12

    pdf.setFont("Helvetica-Bold", 7)
    pdf.drawString(8 * mm, y, "Producto")
    pdf.drawRightString(width - 8 * mm, y, "Importe")
    y -= 10

    pdf.setFont("Helvetica", 7)

    for item in sale.get("items", []):
        name = safe_text(item.get("name", ""))
        qty = int(item.get("qty", 0) or 0)
        price = float(item.get("price", 0) or 0)
        line_total = float(item.get("line_total", price * qty) or 0)

        if len(name) > 25:
            name = name[:22] + "..."

        pdf.drawString(8 * mm, y, name)
        pdf.drawRightString(width - 8 * mm, y, money(line_total))
        y -= 9

        pdf.drawString(10 * mm, y, f"{qty} x {money(price)}")
        y -= 10

        if y < 25 * mm:
            pdf.showPage()
            y = height - 15 * mm
            pdf.setFont("Helvetica", 7)

    y -= 4
    pdf.line(8 * mm, y, width - 8 * mm, y)
    y -= 14

    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(8 * mm, y, "TOTAL")
    pdf.drawRightString(width - 8 * mm, y, money(sale.get("total", 0)))
    y -= 11

    if sale.get("sale_type") == "credit":
        pdf.setFont("Helvetica", 7)
        pdf.drawString(8 * mm, y, "Abonado")
        pdf.drawRightString(width - 8 * mm, y, money(sale.get("amount_paid", 0)))
        y -= 10

        pdf.drawString(8 * mm, y, "Pendiente")
        pdf.drawRightString(width - 8 * mm, y, money(sale.get("balance", 0)))
        y -= 10

    y -= 10
    pdf.setFont("Helvetica", 7)
    pdf.drawCentredString(width / 2, y, "Gracias por su compra")

    pdf.save()
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name=f"ticket_venta_{sale_id}.pdf",
        mimetype="application/pdf"
    )

def get_company_info():
    try:
        company = db()["companies"].find_one({
            "_id": ObjectId(company_id())
        })
    except Exception:
        company = None

    if not company:
        return {
            "name": session.get("company_name", ""),
            "email": "",
            "phone": "",
            "address": ""
        }

    branding = company.get("pdf_branding", {}) or {}

    return {
        "name": branding.get("logo_text") or company.get("name", session.get("company_name", "")),
        "email": branding.get("company_email", ""),
        "phone": branding.get("company_phone", ""),
        "address": branding.get("company_address", "")
    }


@company_sales_bp.route("/sales/<sale_id>/pdf/nota")
def sale_formal_note_pdf(sale_id):
    if not login_required():
        return redirect(url_for("login"))

    sale = get_sale_for_pdf(sale_id)

    if not sale:
        flash("Venta no encontrada.", "danger")
        return redirect(url_for("company_sales.sales_list"))

    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=letter)
    width, height = letter

    branding = company_pdf_branding()

    logo_text = branding.get("logo_text", "")
    logo_image = branding.get("logo_image", "")
    watermark_text = branding.get("watermark_text", "")

    company_info = {
        "name": branding.get("logo_text") or session.get("company_name", ""),
        "email": branding.get("company_email", ""),
        "phone": branding.get("company_phone", ""),
        "address": branding.get("company_address", "")
    }

    if watermark_text:
        pdf.saveState()
        pdf.setFont("Helvetica-Bold", 42)
        pdf.setFillGray(0.85, 0.20)
        pdf.translate(width / 2, height / 2)
        pdf.rotate(35)
        pdf.drawCentredString(0, 0, watermark_text)
        pdf.restoreState()

    y = height - 50
    left_x = 40
    right_margin = 40

    pdf.setFont("Helvetica-Bold", 22)
    pdf.drawString(left_x, y, "NOTA DE VENTA")

    created_at = sale.get("created_at")
    fecha = created_at.strftime("%d/%m/%Y %H:%M") if created_at else ""

    y -= 16
    pdf.setFont("Helvetica", 9)
    pdf.drawString(left_x, y, f"Fecha: {fecha}")
    y -= 24

    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(left_x, y, safe_text(company_info.get("name", "")))
    y -= 15

    pdf.setFont("Helvetica", 9)

    company_email = safe_text(company_info.get("email", ""))
    company_phone = safe_text(company_info.get("phone", ""))
    company_address = safe_text(company_info.get("address", ""))

    if company_email:
        pdf.drawString(left_x, y, f"Correo: {company_email}")
        y -= 12

    if company_phone:
        pdf.drawString(left_x, y, f"Teléfono: {company_phone}")
        y -= 12

    if company_address:
        y = draw_wrapped_text(
            pdf,
            f"Dirección: {company_address}",
            left_x,
            y,
            max_chars=60,
            line_height=11
        )
        y -= 5

    logo_top_y = height - 55

    if logo_image:
        logo_path = os.path.join(
            current_app.root_path,
            "static",
            logo_image.replace("/", os.sep)
        )

        if os.path.exists(logo_path):
            try:
                pdf.drawImage(
                    ImageReader(logo_path),
                    width - 160,
                    logo_top_y - 45,
                    width=115,
                    height=65,
                    preserveAspectRatio=True,
                    mask="auto"
                )
            except Exception:
                if logo_text:
                    pdf.setFont("Helvetica-Bold", 14)
                    pdf.drawRightString(width - right_margin, logo_top_y, logo_text)
        elif logo_text:
            pdf.setFont("Helvetica-Bold", 14)
            pdf.drawRightString(width - right_margin, logo_top_y, logo_text)

    elif logo_text:
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawRightString(width - right_margin, logo_top_y, logo_text)

    header_bottom = min(y, height - 145)
    pdf.line(40, header_bottom, width - 40, header_bottom)
    y = header_bottom - 25

    estado = "PAGADA" if sale.get("payment_status") == "paid" else "PENDIENTE DE PAGO"
    tipo = "VENTA A CRÉDITO" if sale.get("sale_type") == "credit" else "VENTA DE CONTADO"

    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(40, y, "Información de la venta")
    y -= 16

    pdf.setFont("Helvetica", 9)
    pdf.drawString(40, y, f"Folio: {sale.get('_id')}")
    y -= 13
    pdf.drawString(40, y, f"Tipo: {tipo}")
    y -= 13
    pdf.drawString(40, y, f"Estado: {estado}")
    y -= 24

    customer = sale.get("customer", {})

    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(40, y, "Datos del cliente")
    y -= 16

    pdf.setFont("Helvetica", 9)
    pdf.drawString(40, y, f"Nombre: {safe_text(customer.get('name', 'Venta rápida'))}")
    y -= 13
    pdf.drawString(40, y, f"Teléfono: {safe_text(customer.get('phone', ''))}")
    y -= 13
    pdf.drawString(40, y, f"Correo: {safe_text(customer.get('email', ''))}")
    y -= 13

    pdf.drawString(40, y, "Dirección:")
    y -= 12

    y = draw_wrapped_text(
        pdf,
        customer.get("address", ""),
        55,
        y,
        max_chars=90,
        line_height=11
    )

    y -= 12
    pdf.line(40, y, width - 40, y)
    y -= 22

    pdf.setFillColorRGB(0.10, 0.45, 0.95)
    pdf.rect(40, y - 4, width - 80, 20, fill=1, stroke=0)

    pdf.setFillColorRGB(1, 1, 1)
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(45, y + 2, "PRODUCTO")
    pdf.drawString(255, y + 2, "SKU")
    pdf.drawRightString(365, y + 2, "PRECIO")
    pdf.drawRightString(435, y + 2, "CANT.")
    pdf.drawRightString(540, y + 2, "IMPORTE")
    y -= 20

    pdf.setFillColorRGB(0, 0, 0)
    pdf.setFont("Helvetica", 8)

    row_fill = False

    for item in sale.get("items", []):
        if y < 100:
            pdf.showPage()
            y = height - 50

            pdf.setFillColorRGB(0.10, 0.45, 0.95)
            pdf.rect(40, y - 4, width - 80, 20, fill=1, stroke=0)

            pdf.setFillColorRGB(1, 1, 1)
            pdf.setFont("Helvetica-Bold", 8)
            pdf.drawString(45, y + 2, "PRODUCTO")
            pdf.drawString(255, y + 2, "SKU")
            pdf.drawRightString(365, y + 2, "PRECIO")
            pdf.drawRightString(435, y + 2, "CANT.")
            pdf.drawRightString(540, y + 2, "IMPORTE")
            y -= 20

            pdf.setFillColorRGB(0, 0, 0)
            pdf.setFont("Helvetica", 8)

        if row_fill:
            pdf.setFillColorRGB(0.95, 0.97, 1)
            pdf.rect(40, y - 3, width - 80, 16, fill=1, stroke=0)
            pdf.setFillColorRGB(0, 0, 0)

        name = safe_text(item.get("name", ""))
        sku = safe_text(item.get("sku", ""))
        qty = int(item.get("qty", 0) or 0)
        price = float(item.get("price", 0) or 0)
        line_total = float(item.get("line_total", price * qty) or 0)

        if len(name) > 34:
            name = name[:31] + "..."

        pdf.drawString(45, y, name)
        pdf.drawString(255, y, sku[:18])
        pdf.drawRightString(365, y, money(price))
        pdf.drawRightString(435, y, str(qty))
        pdf.drawRightString(540, y, money(line_total))

        y -= 16
        row_fill = not row_fill

    y -= 10
    pdf.line(40, y, width - 40, y)
    y -= 20

    totals_x_label = 410
    totals_x_value = 540

    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawRightString(totals_x_label, y, "Subtotal:")
    pdf.drawRightString(totals_x_value, y, money(sale.get("subtotal", 0)))
    y -= 15

    pdf.drawRightString(totals_x_label, y, "Total:")
    pdf.drawRightString(totals_x_value, y, money(sale.get("total", 0)))
    y -= 15

    if sale.get("sale_type") == "credit":
        pdf.setFont("Helvetica", 9)
        pdf.drawRightString(totals_x_label, y, "Abonado:")
        pdf.drawRightString(totals_x_value, y, money(sale.get("amount_paid", 0)))
        y -= 14

        pdf.setFillColorRGB(0.93, 0.96, 1)
        pdf.rect(360, y - 5, 190, 20, fill=1, stroke=0)
        pdf.setFillColorRGB(0, 0, 0)

        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawRightString(totals_x_label, y, "Saldo pendiente:")
        pdf.drawRightString(totals_x_value, y, money(sale.get("balance", 0)))
        y -= 25

    if sale.get("payments"):
        y -= 5

        if y < 120:
            pdf.showPage()
            y = height - 50

        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(40, y, "Historial de pagos / abonos")
        y -= 15

        pdf.setFont("Helvetica", 8)

        for payment in sale.get("payments", []):
            if y < 70:
                pdf.showPage()
                y = height - 50
                pdf.setFont("Helvetica", 8)

            payment_date = payment.get("created_at")
            payment_date_str = payment_date.strftime("%d/%m/%Y %H:%M") if payment_date else ""

            line = f"{payment_date_str} | {money(payment.get('amount', 0))} | {safe_text(payment.get('note', ''))}"
            pdf.drawString(40, y, line[:110])
            y -= 12

    y = max(y, 70)

    pdf.setFont("Helvetica", 8)
    pdf.drawString(40, 45, "Documento generado por Store Track.")
    pdf.drawString(40, 33, "Esta nota no sustituye un CFDI/factura fiscal.")

    pdf.save()
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name=f"nota_venta_{sale_id}.pdf",
        mimetype="application/pdf"
    )