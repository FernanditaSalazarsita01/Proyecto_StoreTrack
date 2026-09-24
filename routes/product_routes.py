import os
import re
import csv
import json
from io import StringIO
from datetime import datetime

from bson import ObjectId
from bson.errors import InvalidId
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.utils import secure_filename

from io import BytesIO
from flask import send_file, Response
from openpyxl import Workbook

import extensions as ext

product_bp = Blueprint("products", __name__)

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
ALLOWED_IMPORT_EXTENSIONS = {"json", "sql"}


def db():
    return ext.db


def company_id():
    return session.get("company_id")


def login_required():
    return session.get("user_id") and session.get("company_id")


def is_admin_empresa():
    return session.get("role") == "admin_empresa"

def current_company_plan():
    company = db()["companies"].find_one({
        "_id": ObjectId(company_id())
    })

    if company:
        return company.get("plan", "basic")

    return session.get("company_plan", "basic")


def has_feature(plan, feature):
    """
    Valida si el plan actual tiene habilitada una característica.

    Se normalizan nombres comunes de planes para evitar fallos cuando
    en la base se guarden como "pro", "professional", "profesional",
    "premium", "enterprise", etc.
    """
    plan_key = str(plan or "basic").strip().lower()

    aliases = {
        "free": "basic",
        "gratis": "basic",
        "basico": "basic",
        "básico": "basic",
        "basic": "basic",

        "pro": "professional",
        "profesional": "professional",
        "professional": "professional",

        "premium": "premium",

        "enterprise": "enterprise",
        "empresarial": "enterprise",
    }

    plan_key = aliases.get(plan_key, plan_key)

    plan_features = {
        "basic": {
            "manual_backups": False,
            "custom_backups": False,
        },
        "professional": {
            "manual_backups": True,
            "custom_backups": True,
        },
        "premium": {
            "manual_backups": True,
            "custom_backups": True,
        },
        "enterprise": {
            "manual_backups": True,
            "custom_backups": True,
        },
    }

    return plan_features.get(plan_key, plan_features["basic"]).get(feature, False)


def deny_upgrade(message):
    session["upgrade_message"] = message
    return redirect(url_for("plans.company_plans"))


def require_plan_feature(feature, message):
    plan = current_company_plan()

    if not has_feature(plan, feature):
        return deny_upgrade(message)

    return None


def safe_object_id(value):
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


def allowed_image(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def allowed_import(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMPORT_EXTENSIONS


def company_upload_folder():
    cid = company_id()
    folder = os.path.join("static", "uploads", str(cid), "products")
    os.makedirs(folder, exist_ok=True)
    return folder


def image_public_path(filename):
    if not filename:
        return ""
    return f"uploads/{company_id()}/products/{filename}"


def to_float(value):
    try:
        if value is None or value == "":
            return 0.0
        return float(str(value).replace(",", "").strip())
    except Exception:
        return 0.0


def to_int(value):
    try:
        if value is None or value == "":
            return 0
        return int(float(str(value).replace(",", "").strip()))
    except Exception:
        return 0


def normalize_text(value):
    return str(value or "").strip()


def get_product_payload(form):
    return {
        "name": normalize_text(form.get("name")),
        "sku": normalize_text(form.get("sku")),
        "category": normalize_text(form.get("category")),
        "provider": normalize_text(form.get("provider")),
        "unit": normalize_text(form.get("unit")),
        "price": to_float(form.get("price")),
        "stock": to_int(form.get("stock")),
        "description": normalize_text(form.get("description")),
    }


def save_product_image(file):
    if not file or not file.filename:
        return ""

    if not allowed_image(file.filename):
        return ""

    filename = secure_filename(file.filename)
    final_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{filename}"
    file.save(os.path.join(company_upload_folder(), final_name))

    return final_name


def ensure_indexes():
    try:
        db()["products"].create_index([("company_id", 1)])
        db()["products"].create_index([("company_id", 1), ("sku", 1)], unique=True)
        db()["sales"].create_index([("company_id", 1)])
        db()["backups"].create_index([("company_id", 1)])
        db()["custom_backups"].create_index([("company_id", 1)])
    except Exception:
        pass


def serialize_product(p):
    p["_id"] = str(p["_id"])
    return p


# ============================================================
# VISTA: ALTA / IMPORTACIÓN DE PRODUCTOS
# ============================================================
@product_bp.route("/crud")
@product_bp.route("/productos/add")
def crud():
    if not login_required():
        return redirect(url_for("login"))

    ensure_indexes()

    cid = company_id()

    products = list(
        db()["products"]
        .find({"company_id": cid})
        .sort("created_at", -1)
    )

    products = [serialize_product(p) for p in products]

    categories = db()["products"].distinct("category", {"company_id": cid})

    kpis = {
        "users": db()["users"].count_documents({"company_id": cid}),
        "categories": len(categories),
        "products": db()["products"].count_documents({"company_id": cid}),
        "sales": db()["sales"].count_documents({"company_id": cid}),
    }

    return render_template("crud.html", products=products, kpis=kpis)


# ============================================================
# VISTA: TABLA CRUD DE PRODUCTOS
# ============================================================
@product_bp.route("/productos")
@product_bp.route("/products/table")
@product_bp.route("/crud/tabla")
def products_table():
    if not login_required():
        return redirect(url_for("login"))

    cid = company_id()
    search = normalize_text(request.args.get("q"))

    query = {"company_id": cid}

    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"sku": {"$regex": search, "$options": "i"}},
            {"category": {"$regex": search, "$options": "i"}},
            {"provider": {"$regex": search, "$options": "i"}},
        ]

    products = list(
        db()["products"]
        .find(query)
        .sort("created_at", -1)
    )

    products = [serialize_product(p) for p in products]

    return render_template(
        "crud_table_only.html",
        products=products,
        q=search
    )


# ============================================================
# CREAR PRODUCTO
# ============================================================
@product_bp.route("/products/create", methods=["POST"])
def create_product():
    if not login_required():
        return redirect(url_for("login"))

    cid = company_id()
    payload = get_product_payload(request.form)

    if not payload["name"] or not payload["sku"] or not payload["category"]:
        flash("Nombre, SKU y categoría son obligatorios.", "warning")
        return redirect(url_for("products.crud"))

    exists = db()["products"].find_one({
        "company_id": cid,
        "sku": payload["sku"]
    })

    if exists:
        flash("Ya existe un producto con ese SKU en esta empresa.", "warning")
        return redirect(url_for("products.crud"))

    image_filename = save_product_image(request.files.get("image"))

    product_doc = {
        "company_id": cid,
        "company_name": session.get("company_name", ""),
        **payload,
        "image_filename": image_filename,
        "image_path": image_public_path(image_filename),
        "created_by": session.get("user_id"),
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }

    db()["products"].insert_one(product_doc)

    flash("Producto creado correctamente ✅", "success")
    return redirect(url_for("products.crud"))


# ============================================================
# EDITAR PRODUCTO
# ============================================================
@product_bp.route("/products/<product_id>/edit")
def edit_product(product_id):
    if not login_required():
        return redirect(url_for("login"))

    obj_id = safe_object_id(product_id)

    if not obj_id:
        flash("ID inválido.", "warning")
        return redirect(url_for("products.products_table"))

    product = db()["products"].find_one({
        "_id": obj_id,
        "company_id": company_id()
    })

    if not product:
        flash("Producto no encontrado o no pertenece a esta empresa.", "warning")
        return redirect(url_for("products.products_table"))

    product = serialize_product(product)

    return render_template("edit.html", product=product)


# ============================================================
# ACTUALIZAR PRODUCTO
# ============================================================
@product_bp.route("/products/<product_id>/update", methods=["POST"])
def update_product(product_id):
    if not login_required():
        return redirect(url_for("login"))

    cid = company_id()
    obj_id = safe_object_id(product_id)

    if not obj_id:
        flash("ID inválido.", "warning")
        return redirect(url_for("products.products_table"))

    product = db()["products"].find_one({
        "_id": obj_id,
        "company_id": cid
    })

    if not product:
        flash("Producto no encontrado o no pertenece a esta empresa.", "warning")
        return redirect(url_for("products.products_table"))

    payload = get_product_payload(request.form)

    if not payload["name"] or not payload["sku"] or not payload["category"]:
        flash("Nombre, SKU y categoría son obligatorios.", "warning")
        return redirect(url_for("products.edit_product", product_id=product_id))

    duplicated = db()["products"].find_one({
        "_id": {"$ne": obj_id},
        "company_id": cid,
        "sku": payload["sku"]
    })

    if duplicated:
        flash("Ya existe otro producto con ese SKU en esta empresa.", "warning")
        return redirect(url_for("products.edit_product", product_id=product_id))

    image_filename = product.get("image_filename", "")

    new_image = save_product_image(request.files.get("image"))
    if new_image:
        image_filename = new_image

    update_doc = {
        **payload,
        "image_filename": image_filename,
        "image_path": image_public_path(image_filename),
        "updated_at": datetime.utcnow(),
        "updated_by": session.get("user_id")
    }

    db()["products"].update_one(
        {"_id": obj_id, "company_id": cid},
        {"$set": update_doc}
    )

    flash("Producto actualizado correctamente ✅", "success")
    return redirect(url_for("products.products_table"))


# ============================================================
# ELIMINAR PRODUCTO
# ============================================================
@product_bp.route("/products/<product_id>/delete", methods=["POST"])
def delete_product(product_id):
    if not login_required():
        return redirect(url_for("login"))

    obj_id = safe_object_id(product_id)

    if not obj_id:
        flash("ID inválido.", "warning")
        return redirect(url_for("products.products_table"))

    result = db()["products"].delete_one({
        "_id": obj_id,
        "company_id": company_id()
    })

    if result.deleted_count == 0:
        flash("No se pudo eliminar el producto.", "warning")
    else:
        flash("Producto eliminado correctamente ✅", "success")

    return redirect(url_for("products.products_table"))


# ============================================================
# IMPORTAR JSON / SQL
# ============================================================
@product_bp.route("/products/import", methods=["POST"])
def import_products():
    if not login_required():
        return redirect(url_for("login"))

    file = request.files.get("file")

    if not file or not file.filename:
        flash("Selecciona un archivo.", "warning")
        return redirect(url_for("products.crud"))

    if not allowed_import(file.filename):
        flash("Solo se permiten archivos .json o .sql.", "warning")
        return redirect(url_for("products.crud"))

    filename = file.filename.lower()
    cid = company_id()

    inserted = 0
    duplicated = 0
    errors = 0

    try:
        content = file.read().decode("utf-8", errors="ignore")

        if filename.endswith(".json"):
            rows = parse_json_products(content)
        else:
            rows = parse_sql_products(content)

        for item in rows:
            sku = normalize_text(item.get("sku"))

            if not sku:
                errors += 1
                continue

            exists = db()["products"].find_one({
                "company_id": cid,
                "sku": sku
            })

            if exists:
                duplicated += 1
                continue

            doc = {
                "company_id": cid,
                "company_name": session.get("company_name", ""),
                "name": normalize_text(item.get("name")),
                "sku": sku,
                "category": normalize_text(item.get("category")),
                "provider": normalize_text(item.get("provider")),
                "unit": normalize_text(item.get("unit")),
                "price": to_float(item.get("price")),
                "stock": to_int(item.get("stock")),
                "description": normalize_text(item.get("description")),
                "image_filename": "",
                "image_path": "",
                "created_by": session.get("user_id"),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }

            if not doc["name"] or not doc["category"]:
                errors += 1
                continue

            db()["products"].insert_one(doc)
            inserted += 1

        flash(
            f"Importación terminada. Insertados: {inserted}, duplicados: {duplicated}, errores: {errors}",
            "success"
        )

    except Exception as e:
        flash(f"Error al importar: {str(e)}", "danger")

    return redirect(url_for("products.crud"))


def parse_json_products(content):
    data = json.loads(content)

    if isinstance(data, dict):
        data = data.get("products", [])

    if not isinstance(data, list):
        raise ValueError("El JSON debe ser una lista o contener la llave 'products'.")

    return data


def parse_sql_products(content):
    rows = []

    pattern = re.compile(
        r"INSERT\s+INTO\s+[`\"\[]?\w+[`\"\]]?\s*\((.*?)\)\s*VALUES\s*(.*?);",
        re.IGNORECASE | re.DOTALL
    )

    matches = pattern.findall(content)

    for columns_raw, values_raw in matches:
        columns = [
            c.strip().replace("`", "").replace('"', "").replace("[", "").replace("]", "")
            for c in columns_raw.split(",")
        ]

        value_groups = extract_sql_value_groups(values_raw)

        for group in value_groups:
            values = parse_sql_values(group)

            if len(values) != len(columns):
                continue

            item = dict(zip(columns, values))
            rows.append(normalize_import_columns(item))

    return rows


def extract_sql_value_groups(values_raw):
    groups = []
    current = ""
    depth = 0
    in_quote = False
    quote_char = ""

    for char in values_raw:
        if char in ("'", '"'):
            if not in_quote:
                in_quote = True
                quote_char = char
            elif quote_char == char:
                in_quote = False

        if char == "(" and not in_quote:
            depth += 1
            if depth == 1:
                current = ""
                continue

        if char == ")" and not in_quote:
            depth -= 1
            if depth == 0:
                groups.append(current)
                current = ""
                continue

        if depth >= 1:
            current += char

    return groups


def parse_sql_values(group):
    reader = csv.reader(
        StringIO(group),
        delimiter=",",
        quotechar="'",
        escapechar="\\",
        skipinitialspace=True
    )

    values = next(reader)

    clean = []

    for v in values:
        v = v.strip()

        if v.upper() == "NULL":
            clean.append("")
        else:
            clean.append(v)

    return clean


def normalize_import_columns(item):
    mapping = {
        "nombre": "name",
        "name": "name",
        "producto": "name",

        "sku": "sku",
        "codigo": "sku",
        "código": "sku",
        "clave": "sku",

        "categoria": "category",
        "categoría": "category",
        "category": "category",

        "proveedor": "provider",
        "provider": "provider",

        "unidad": "unit",
        "unit": "unit",

        "precio": "price",
        "price": "price",

        "stock": "stock",
        "existencia": "stock",
        "cantidad": "stock",

        "descripcion": "description",
        "descripción": "description",
        "description": "description",
    }

    normalized = {}

    for key, value in item.items():
        clean_key = key.strip().lower()
        final_key = mapping.get(clean_key)

        if final_key:
            normalized[final_key] = value

    return normalized


# ============================================================
# ADMIN VERIFY
# ============================================================
@product_bp.route("/admin/verify", methods=["POST"])
def admin_verify():
    if not login_required():
        return jsonify({"ok": False, "msg": "Sesión no válida"}), 401

    data = request.get_json(silent=True) or {}

    email = normalize_text(data.get("email")).lower()
    password = data.get("password", "")

    from werkzeug.security import check_password_hash

    user = db()["users"].find_one({
        "company_id": company_id(),
        "email": email,
        "role": "admin_empresa"
    })

    if not user:
        return jsonify({"ok": False, "msg": "Administrador no encontrado"}), 401

    if not check_password_hash(user.get("password", ""), password):
        return jsonify({"ok": False, "msg": "Credenciales incorrectas"}), 401

    return jsonify({"ok": True, "msg": "Validación correcta"})


# ============================================================
# BACKUP PERSONALIZADO EN BASE DE DATOS
# ============================================================
@product_bp.route("/custom-backups/create-db", methods=["POST"])
def custom_backup_create_db():
    if not login_required():
        return jsonify({"ok": False, "msg": "Sesión no válida"}), 401
    if not has_feature(current_company_plan(), "custom_backups"):
        return jsonify({
            "ok": False,
            "msg": "Los backups personalizados están disponibles desde el plan Profesional."
        }), 403

    if not is_admin_empresa():
        return jsonify({"ok": False, "msg": "Solo administrador puede crear backups"}), 403

    data = request.get_json(silent=True) or {}
    fields = data.get("fields", [])

    if not fields:
        return jsonify({"ok": False, "msg": "Selecciona al menos un campo"}), 400

    allowed_fields = {
        "name", "sku", "category", "provider",
        "price", "stock", "unit", "description"
    }

    fields = [f for f in fields if f in allowed_fields]

    if not fields:
        return jsonify({"ok": False, "msg": "Campos no válidos"}), 400

    products = list(db()["products"].find({"company_id": company_id()}))

    clean_products = []

    for p in products:
        item = {}
        for field in fields:
            item[field] = p.get(field, "")
        clean_products.append(item)

    backup_doc = {
        "company_id": company_id(),
        "company_name": session.get("company_name", ""),
        "type": "custom",
        "fields": fields,
        "products": clean_products,
        "count": len(clean_products),
        "created_by": session.get("user_id"),
        "created_at": datetime.utcnow()
    }

    db()["custom_backups"].insert_one(backup_doc)

    return jsonify({
        "ok": True,
        "msg": "Backup personalizado creado correctamente ✅"
    })
# ============================================================
# CREAR BACKUP DE PRODUCTOS
# ============================================================
@product_bp.route("/backups/create", methods=["POST"])
def create_backup():
    if not login_required():
        return redirect(url_for("login"))

    blocked = require_plan_feature(
        "manual_backups",
        "Tu plan actual no permite crear backups manuales."
    )

    if blocked:
        return blocked

    if session.get("role") != "admin_empresa":
        flash("Solo el administrador puede crear backups.", "warning")
        return redirect(url_for("products.products_table"))

    cid = company_id()

    products = list(db()["products"].find({"company_id": cid}).sort("created_at", -1))

    clean_products = []
    for p in products:
        p["_id"] = str(p["_id"])
        clean_products.append({
            "_id": p.get("_id"),
            "name": p.get("name", ""),
            "sku": p.get("sku", ""),
            "category": p.get("category", ""),
            "provider": p.get("provider", ""),
            "price": p.get("price", 0),
            "stock": p.get("stock", 0),
            "unit": p.get("unit", ""),
            "description": p.get("description", ""),
            "image_filename": p.get("image_filename", ""),
            "created_at": str(p.get("created_at", "")),
            "updated_at": str(p.get("updated_at", ""))
        })
    

    backup_doc = {
        "company_id": cid,
        "company_name": session.get("company_name", ""),
        "products": clean_products,
        "count": len(clean_products),
        "created_by": session.get("user_id"),
        "created_at": datetime.utcnow()
    }

    db()["backups"].insert_one(backup_doc)

    flash("Backup creado correctamente ✅", "success")
    return redirect(url_for("products.backups_list"))


# ============================================================
# LISTA DE BACKUPS
# ============================================================
@product_bp.route("/backups")
def backups_list():
    if not login_required():
        return redirect(url_for("login"))

    if session.get("role") != "admin_empresa":
        flash("Solo el administrador puede ver backups.", "warning")
        return redirect(url_for("products.products_table"))

    backups = list(
        db()["backups"]
        .find({"company_id": company_id()})
        .sort("created_at", -1)
    )

    for b in backups:
        b["_id"] = str(b["_id"])

    return render_template("backups.html", backups=backups)


# ============================================================
# DETALLE DEL BACKUP
# ============================================================
@product_bp.route("/backups/<backup_id>")
def backup_detail(backup_id):
    if not login_required():
        return redirect(url_for("login"))

    obj_id = safe_object_id(backup_id)

    if not obj_id:
        flash("ID inválido.", "warning")
        return redirect(url_for("products.backups_list"))

    backup = db()["backups"].find_one({
        "_id": obj_id,
        "company_id": company_id()
    })

    if not backup:
        flash("Backup no encontrado.", "warning")
        return redirect(url_for("products.backups_list"))

    backup["_id"] = str(backup["_id"])

    return render_template("backup_detail.html", backup=backup)


# ============================================================
# ELIMINAR BACKUP
# ============================================================
@product_bp.route("/backups/<backup_id>/delete", methods=["POST"])
def backups_delete(backup_id):
    if not login_required():
        return redirect(url_for("login"))

    obj_id = safe_object_id(backup_id)

    if not obj_id:
        flash("ID inválido.", "warning")
        return redirect(url_for("products.backups_list"))

    db()["backups"].delete_one({
        "_id": obj_id,
        "company_id": company_id()
    })

    flash("Backup eliminado correctamente ✅", "success")
    return redirect(url_for("products.backups_list"))


def get_backup_or_redirect(backup_id):
    obj_id = safe_object_id(backup_id)

    if not obj_id:
        return None

    return db()["backups"].find_one({
        "_id": obj_id,
        "company_id": company_id()
    })


# ============================================================
# DESCARGAR JSON
# ============================================================
@product_bp.route("/backups/<backup_id>/download/json")
def backup_download_json(backup_id):
    backup = get_backup_or_redirect(backup_id)

    if not backup:
        flash("Backup no encontrado.", "warning")
        return redirect(url_for("products.backups_list"))

    data = {
        "company_id": backup.get("company_id"),
        "company_name": backup.get("company_name"),
        "created_at": str(backup.get("created_at")),
        "count": backup.get("count", 0),
        "products": backup.get("products", [])
    }

    return Response(
        json.dumps(data, indent=4, ensure_ascii=False),
        mimetype="application/json",
        headers={
            "Content-Disposition": f"attachment; filename=backup_productos_{backup_id}.json"
        }
    )


# ============================================================
# DESCARGAR SQL
# ============================================================
@product_bp.route("/backups/<backup_id>/download/sql")
def backup_download_sql(backup_id):
    backup = get_backup_or_redirect(backup_id)

    if not backup:
        flash("Backup no encontrado.", "warning")
        return redirect(url_for("products.backups_list"))

    lines = []

    for p in backup.get("products", []):
        name = str(p.get("name", "")).replace("'", "''")
        sku = str(p.get("sku", "")).replace("'", "''")
        category = str(p.get("category", "")).replace("'", "''")
        provider = str(p.get("provider", "")).replace("'", "''")
        unit = str(p.get("unit", "")).replace("'", "''")
        description = str(p.get("description", "")).replace("'", "''")
        price = float(p.get("price") or 0)
        stock = int(p.get("stock") or 0)

        lines.append(
            "INSERT INTO products "
            "(name, sku, category, provider, price, stock, unit, description) "
            f"VALUES ('{name}', '{sku}', '{category}', '{provider}', {price}, {stock}, '{unit}', '{description}');"
        )

    sql_content = "\n".join(lines)

    return Response(
        sql_content,
        mimetype="application/sql",
        headers={
            "Content-Disposition": f"attachment; filename=backup_productos_{backup_id}.sql"
        }
    )


# ============================================================
# DESCARGAR EXCEL
# ============================================================
@product_bp.route("/backups/<backup_id>/download/xlsx")
def backup_download_xlsx(backup_id):
    backup = get_backup_or_redirect(backup_id)

    if not backup:
        flash("Backup no encontrado.", "warning")
        return redirect(url_for("products.backups_list"))

    wb = Workbook()
    ws = wb.active
    ws.title = "Productos"

    headers = [
        "Nombre", "SKU", "Categoría", "Proveedor",
        "Precio", "Stock", "Unidad", "Descripción"
    ]

    ws.append(headers)

    for p in backup.get("products", []):
        ws.append([
            p.get("name", ""),
            p.get("sku", ""),
            p.get("category", ""),
            p.get("provider", ""),
            p.get("price", 0),
            p.get("stock", 0),
            p.get("unit", ""),
            p.get("description", "")
        ])

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name=f"backup_productos_{backup_id}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# ============================================================
# DESCARGAR PDF SIMPLE
# ============================================================
@product_bp.route("/backups/<backup_id>/download/pdf")
def backup_download_pdf(backup_id):
    backup = get_backup_or_redirect(backup_id)

    if not backup:
        flash("Backup no encontrado.", "warning")
        return redirect(url_for("products.backups_list"))

    try:
        from reportlab.lib.pagesizes import letter, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet
    except ImportError:
        flash("Instala reportlab: pip install reportlab", "danger")
        return redirect(url_for("products.backup_detail", backup_id=backup_id))

    output = BytesIO()

    doc = SimpleDocTemplate(
        output,
        pagesize=landscape(letter),
        rightMargin=25,
        leftMargin=25,
        topMargin=25,
        bottomMargin=25
    )

    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("Backup de productos", styles["Title"]))
    elements.append(Paragraph(f"Empresa: {backup.get('company_name', '')}", styles["Normal"]))
    elements.append(Paragraph(f"Total productos: {backup.get('count', 0)}", styles["Normal"]))
    elements.append(Spacer(1, 12))

    data = [["Nombre", "SKU", "Categoría", "Proveedor", "Precio", "Stock", "Unidad"]]

    for p in backup.get("products", []):
        data.append([
            p.get("name", ""),
            p.get("sku", ""),
            p.get("category", ""),
            p.get("provider", ""),
            f"${p.get('price', 0)}",
            p.get("stock", 0),
            p.get("unit", "")
        ])

    table = Table(data, repeatRows=1)

    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f3c4c")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (4, 1), (5, -1), "CENTER"),
    ]))

    elements.append(table)

    doc.build(elements)

    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name=f"backup_productos_{backup_id}.pdf",
        mimetype="application/pdf"
    )