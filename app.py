from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from bson.objectid import ObjectId
from routes.product_routes import product_bp
from routes.data_quality_routes import data_quality_bp
from routes.company_sales_routes import company_sales_bp
import extensions as ext
import os
import random
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv
from datetime import datetime, timedelta
from routes.client_routes import client_bp
from routes.plan_routes import plan_bp
from helpers.plan_rules import PLANS, has_feature, plan_name, max_users
from werkzeug.utils import secure_filename
from routes.analytics_routes import analytics_bp
from routes.business_intelligence_routes import business_intelligence_bp


load_dotenv()

app = Flask(__name__)
app.secret_key = "supersecretkey"

ext.init_mongo()
db = ext.db

@app.context_processor
def inject_plan_helpers():
    current_plan = session.get("company_plan", "basic")

    return {
        "current_plan": current_plan,
        "current_plan_name": plan_name(current_plan),
        "has_plan_feature": lambda feature: has_feature(current_plan, feature),
        "PLANS": PLANS
    }

app.register_blueprint(company_sales_bp)
app.register_blueprint(product_bp)
app.register_blueprint(data_quality_bp)
app.register_blueprint(client_bp)
app.register_blueprint(plan_bp)
app.register_blueprint(analytics_bp)
app.register_blueprint(business_intelligence_bp)


# =========================
# DECORADORES
# =========================

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):

        if "user_id" not in session:
            return redirect(url_for("login"))

        return f(*args, **kwargs)

    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):

        if "user_id" not in session:
            return redirect(url_for("login"))

        if session.get("role") != "admin_empresa":
            return redirect(url_for("login"))

        return f(*args, **kwargs)

    return decorated_function


def developer_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):

        if "user_id" not in session:
            return redirect(url_for("login"))

        if session.get("role") != "developer":
            return redirect(url_for("login"))

        return f(*args, **kwargs)

    return decorated_function


# =========================
# CORREO RECUPERACIÓN
# =========================

def send_recovery_code(to_email, code):
    mail_user = os.getenv("MAIL_USER")
    mail_pass = os.getenv("MAIL_PASS")
    mail_host = os.getenv("MAIL_HOST", "smtp.gmail.com")
    mail_port = int(os.getenv("MAIL_PORT", "587"))

    if not mail_user or not mail_pass:
        raise Exception("Faltan MAIL_USER o MAIL_PASS en el archivo .env")

    subject = "Código de recuperación - STORE TRACK"

    body = f"""
Hola.

Tu código de recuperación de contraseña es:

{code}

Este código expira en 10 minutos.

Si tú no solicitaste este cambio, ignora este correo.

STORE TRACK
"""

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = mail_user
    msg["To"] = to_email

    server = smtplib.SMTP(mail_host, mail_port)
    server.starttls()
    server.login(mail_user, mail_pass)
    server.sendmail(mail_user, to_email, msg.as_string())
    server.quit()


# =========================
# RUTAS PRINCIPALES
# =========================

@app.route("/")
def index():
    return redirect(url_for("login"))


@app.route("/register-company", methods=["GET", "POST"])
def register_company():

    if request.method == "POST":
        company_name = request.form.get("company", "").strip()
        admin_name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        existing_company = db["companies"].find_one({"name": company_name})

        if existing_company:
            return render_template(
                "register_empresa.html",
                message="La empresa ya existe"
            )

        company_doc = {
            "name": company_name,
            "active": True,
            "plan": "basic",
            "plan_name": "Básico",
            "theme_color": "#8fd8b7",
            "pdf_branding": {
                "logo_text": "",
                "logo_image": "",
                "watermark_text": ""
            },
            "created_at": datetime.utcnow()
        }

        result = db["companies"].insert_one(company_doc)

        admin_doc = {
            "company_id": str(result.inserted_id),
            "name": admin_name,
            "email": email,
            "password": generate_password_hash(password),
            "role": "admin_empresa",
            "created_at": datetime.utcnow()
        }

        db["users"].insert_one(admin_doc)

        return redirect(url_for("login"))

    return render_template("register_empresa.html")


@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":
        company = request.form.get("company", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        company_doc = db["companies"].find_one({"name": company})

        if not company_doc:
            return render_template("login.html", message="Empresa no encontrada")

        user = db["users"].find_one({
            "company_id": str(company_doc["_id"]),
            "email": email
        })

        if not user:
            return render_template("login.html", message="Usuario no encontrado")

        if not check_password_hash(user["password"], password):
            return render_template("login.html", message="Contraseña incorrecta")

        session["user_id"] = str(user["_id"])
        session["company_id"] = str(company_doc["_id"])
        session["company_name"] = company_doc.get("name", "")
        session["theme_color"] = company_doc.get("theme_color", "#8fd8b7")
        session["company_plan"] = company_doc.get("plan", "basic")
        session["company_plan_name"] = company_doc.get("plan_name", "Básico")
        session["role"] = user.get("role", "")
        session["user_name"] = user.get("name", "")
        session["email"] = user.get("email", "")

        if session["role"] == "developer":
            return redirect(url_for("developer_home"))

        if session["role"] == "admin_empresa":
            return redirect(url_for("admin_home"))

        return redirect(url_for("user_home"))

    return render_template("login.html")

# =========================
# PANEL DEVELOPER
# =========================

@app.route("/developer/home")
@developer_required
def developer_home():

    companies = list(db["companies"].find().sort("name", 1))

    total_companies = db["companies"].count_documents({})
    active_companies = db["companies"].count_documents({"active": True})
    inactive_companies = db["companies"].count_documents({"active": False})
    total_users = db["users"].count_documents({})

    # =========================
    # FECHAS
    # =========================
    now = datetime.utcnow()
    start_month = datetime(now.year, now.month, 1)

    new_companies_month = db["companies"].count_documents({
        "created_at": {
            "$gte": start_month
        }
    })

    # =========================
    # SUSCRIPCIONES ACTIVAS
    # =========================
    active_subscriptions = db["companies"].count_documents({
        "active": True,
        "plan": {
            "$exists": True,
            "$ne": ""
        }
    })

    # =========================
    # VENTAS GLOBALES REALES
    # =========================
    global_sales_pipeline = [
        {
            "$match": {
                "payment_status": "paid"
            }
        },
        {
            "$group": {
                "_id": None,
                "total": {
                    "$sum": "$total"
                },
                "count": {
                    "$sum": 1
                }
            }
        }
    ]

    global_sales_result = list(db["sales"].aggregate(global_sales_pipeline))

    if global_sales_result:
        global_sales_total = float(global_sales_result[0].get("total", 0) or 0)
        global_sales_count = int(global_sales_result[0].get("count", 0) or 0)
    else:
        global_sales_total = 0
        global_sales_count = 0

    # =========================
    # RESUMEN POR PLAN
    # =========================
    plans_summary = []

    estimated_income = 0

    companies_by_plan_labels = []
    companies_by_plan_values = []

    sales_by_plan_labels = []
    sales_by_plan_values = []

    users_by_plan_labels = []
    users_by_plan_values = []

    for plan_key, plan_data in PLANS.items():

        plan_companies = list(db["companies"].find({
            "plan": plan_key
        }))

        company_ids = [
            str(company["_id"])
            for company in plan_companies
        ]

        companies_count = len(plan_companies)

        if company_ids:
            users_count = db["users"].count_documents({
                "company_id": {
                    "$in": company_ids
                }
            })

            products_count = db["products"].count_documents({
                "company_id": {
                    "$in": company_ids
                }
            })

            sales_pipeline = [
                {
                    "$match": {
                        "company_id": {
                            "$in": company_ids
                        },
                        "payment_status": "paid"
                    }
                },
                {
                    "$group": {
                        "_id": None,
                        "total": {
                            "$sum": "$total"
                        },
                        "count": {
                            "$sum": 1
                        }
                    }
                }
            ]

            sales_result = list(db["sales"].aggregate(sales_pipeline))

            if sales_result:
                sales_total = float(sales_result[0].get("total", 0) or 0)
                sales_count = int(sales_result[0].get("count", 0) or 0)
            else:
                sales_total = 0
                sales_count = 0

        else:
            users_count = 0
            products_count = 0
            sales_total = 0
            sales_count = 0

        plan_price = float(plan_data.get("price", 0) or 0)
        income_by_plan = companies_count * plan_price

        estimated_income += income_by_plan

        adoption = round(
            (companies_count / total_companies) * 100,
            1
        ) if total_companies > 0 else 0

        plan_row = {
            "key": plan_key,
            "name": plan_data.get("name", plan_key),
            "companies": companies_count,
            "users": users_count,
            "products": products_count,
            "sales_count": sales_count,
            "sales_total": sales_total,
            "income": income_by_plan,
            "adoption": adoption
        }

        plans_summary.append(plan_row)

        companies_by_plan_labels.append(plan_row["name"])
        companies_by_plan_values.append(companies_count)

        sales_by_plan_labels.append(plan_row["name"])
        sales_by_plan_values.append(round(sales_total, 2))

        users_by_plan_labels.append(plan_row["name"])
        users_by_plan_values.append(users_count)

    # =========================
    # MÉTRICAS DESTACADAS DE PLANES
    # =========================
    default_plan_metric = {
        "name": "Sin datos",
        "companies": 0,
        "sales_total": 0,
        "users": 0
    }

    if plans_summary:
        plan_most_used = max(
            plans_summary,
            key=lambda plan: plan["companies"]
        )

        plan_more_sales = max(
            plans_summary,
            key=lambda plan: plan["sales_total"]
        )

        plan_more_users = max(
            plans_summary,
            key=lambda plan: plan["users"]
        )

        plans_with_companies = [
            plan for plan in plans_summary
            if plan["companies"] > 0
        ]

        if plans_with_companies:
            plan_less_adoption = min(
                plans_with_companies,
                key=lambda plan: plan["companies"]
            )
        else:
            plan_less_adoption = default_plan_metric
    else:
        plan_most_used = default_plan_metric
        plan_more_sales = default_plan_metric
        plan_more_users = default_plan_metric
        plan_less_adoption = default_plan_metric

    # =========================
    # DATOS REALES POR EMPRESA
    # =========================
    enriched_companies = []
    top_companies_sales = []

    for company in companies:
        company_id = str(company["_id"])

        company["id"] = company_id

        company["total_users"] = db["users"].count_documents({
            "company_id": company_id
        })

        company["total_products"] = db["products"].count_documents({
            "company_id": company_id
        })

        company_sales_pipeline = [
            {
                "$match": {
                    "company_id": company_id,
                    "payment_status": "paid"
                }
            },
            {
                "$group": {
                    "_id": None,
                    "total": {
                        "$sum": "$total"
                    },
                    "count": {
                        "$sum": 1
                    }
                }
            }
        ]

        company_sales_result = list(db["sales"].aggregate(company_sales_pipeline))

        if company_sales_result:
            company_sales_total = float(company_sales_result[0].get("total", 0) or 0)
            company_sales_count = int(company_sales_result[0].get("count", 0) or 0)
        else:
            company_sales_total = 0
            company_sales_count = 0

        company["total_sales"] = company_sales_count
        company["sales_total"] = company_sales_total

        company["admin"] = db["users"].find_one({
            "company_id": company_id,
            "role": "admin_empresa"
        })

        company["display_date"] = company.get("created_at") or company.get("updated_at")

        enriched_companies.append(company)

        top_companies_sales.append({
            "id": company_id,
            "name": company.get("name", "Sin nombre"),
            "plan": company.get("plan_name") or company.get("plan") or "Sin plan",
            "users": company["total_users"],
            "products": company["total_products"],
            "sales_count": company_sales_count,
            "sales_total": company_sales_total
        })

    top_companies_sales = sorted(
        top_companies_sales,
        key=lambda company: company["sales_total"],
        reverse=True
    )[:5]

    recent_companies = sorted(
        enriched_companies,
        key=lambda company: company.get("created_at") or company.get("updated_at") or datetime.min,
        reverse=True
    )[:5]

    # =========================
    # RENDER
    # =========================
    return render_template(
        "developer_home.html",

        companies=enriched_companies,

        total_companies=total_companies,
        active_companies=active_companies,
        inactive_companies=inactive_companies,
        total_users=total_users,

        active_subscriptions=active_subscriptions,
        new_companies_month=new_companies_month,
        estimated_income=estimated_income,

        global_sales_total=global_sales_total,
        global_sales_count=global_sales_count,

        plan_most_used=plan_most_used,
        plan_more_sales=plan_more_sales,
        plan_more_users=plan_more_users,
        plan_less_adoption=plan_less_adoption,

        plans_summary=plans_summary,
        top_companies_sales=top_companies_sales,
        recent_companies=recent_companies,

        companies_by_plan_labels=companies_by_plan_labels,
        companies_by_plan_values=companies_by_plan_values,

        sales_by_plan_labels=sales_by_plan_labels,
        sales_by_plan_values=sales_by_plan_values,

        users_by_plan_labels=users_by_plan_labels,
        users_by_plan_values=users_by_plan_values
    )

# =========================
# PANEL DEVELOPER
# =========================
@app.route("/developer/companies")
@developer_required
def developer_companies():

    companies = list(db["companies"].find().sort("name", 1))

    total_companies = db["companies"].count_documents({})
    active_companies = db["companies"].count_documents({"active": True})
    inactive_companies = db["companies"].count_documents({"active": False})
    total_users = db["users"].count_documents({})

    for company in companies:
        company_id = str(company["_id"])

        company["id"] = company_id

        company["total_users"] = db["users"].count_documents({
            "company_id": company_id
        })

        company["admin"] = db["users"].find_one({
            "company_id": company_id,
            "role": "admin_empresa"
        })

        company["display_date"] = company.get("created_at") or company.get("updated_at")

    return render_template(
        "developer/companies.html",
        companies=companies,
        total_companies=total_companies,
        active_companies=active_companies,
        inactive_companies=inactive_companies,
        total_users=total_users
    )

@app.route("/developer/company/<company_id>")
@developer_required
def developer_company_detail(company_id):

    company = db["companies"].find_one({
        "_id": ObjectId(company_id)
    })

    if not company:
        return redirect(url_for("developer_home"))

    users = list(db["users"].find({
        "company_id": company_id
    }).sort("created_at", -1))

    admin_user = db["users"].find_one({
        "company_id": company_id,
        "role": "admin_empresa"
    })

    total_users = db["users"].count_documents({
        "company_id": company_id
    })

    total_admins = db["users"].count_documents({
        "company_id": company_id,
        "role": "admin_empresa"
    })

    total_normal_users = db["users"].count_documents({
        "company_id": company_id,
        "role": "user"
    })

    total_products = db["products"].count_documents({
        "company_id": company_id
    })

    total_sales = db["sales"].count_documents({
        "company_id": company_id
    })

    company["id"] = str(company["_id"])
    company["display_date"] = company.get("created_at") or company.get("updated_at")

    return render_template(
        "developer_company_detail.html",
        company=company,
        users=users,
        admin_user=admin_user,
        total_users=total_users,
        total_admins=total_admins,
        total_normal_users=total_normal_users,
        total_products=total_products,
        total_sales=total_sales
    )


@app.route("/developer/company/<company_id>/toggle-active", methods=["POST"])
@developer_required
def developer_toggle_company(company_id):

    company = db["companies"].find_one({
        "_id": ObjectId(company_id)
    })

    if not company:
        return redirect(url_for("developer_home"))

    current_status = company.get("active", True)

    db["companies"].update_one(
        {"_id": ObjectId(company_id)},
        {
            "$set": {
                "active": not current_status,
                "updated_at": datetime.utcnow()
            }
        }
    )

    return redirect(url_for("developer_company_detail", company_id=company_id))

# =========================
# RECUPERACIÓN DE CONTRASEÑA
# =========================

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():

    if request.method == "POST":
        company = request.form.get("company", "").strip()
        email = request.form.get("email", "").strip().lower()

        company_doc = db["companies"].find_one({"name": company})

        generic_message = "Si los datos son correctos, recibirás un código en tu correo."

        if not company_doc:
            return render_template("forgot_password.html", message=generic_message)

        user = db["users"].find_one({
            "company_id": str(company_doc["_id"]),
            "email": email
        })

        if not user:
            return render_template("forgot_password.html", message=generic_message)

        db["password_codes"].update_many(
            {
                "company_id": str(company_doc["_id"]),
                "user_id": str(user["_id"]),
                "used": False
            },
            {
                "$set": {
                    "used": True,
                    "used_at": datetime.utcnow(),
                    "reason": "Código reemplazado"
                }
            }
        )

        code = str(random.randint(100000, 999999))

        db["password_codes"].insert_one({
            "company_id": str(company_doc["_id"]),
            "company_name": company_doc.get("name", ""),
            "user_id": str(user["_id"]),
            "email": email,
            "code": code,
            "used": False,
            "expires_at": datetime.utcnow() + timedelta(minutes=10),
            "created_at": datetime.utcnow()
        })

        try:
            send_recovery_code(email, code)
        except Exception as e:
            return render_template(
                "forgot_password.html",
                message=f"No se pudo enviar el correo: {e}"
            )

        session["reset_company_id"] = str(company_doc["_id"])
        session["reset_email"] = email

        return redirect(url_for("verify_code"))

    return render_template("forgot_password.html")


@app.route("/verify-code", methods=["GET", "POST"])
def verify_code():

    reset_company_id = session.get("reset_company_id")
    reset_email = session.get("reset_email")

    if not reset_company_id or not reset_email:
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        code = request.form.get("code", "").strip()

        code_doc = db["password_codes"].find_one({
            "company_id": reset_company_id,
            "email": reset_email,
            "code": code,
            "used": False
        })

        if not code_doc:
            return render_template(
                "verify_code.html",
                message="Código incorrecto."
            )

        if code_doc["expires_at"] < datetime.utcnow():
            return render_template(
                "verify_code.html",
                message="El código expiró. Solicita uno nuevo."
            )

        session["verified_reset_code_id"] = str(code_doc["_id"])

        return redirect(url_for("reset_password"))

    return render_template("verify_code.html")


@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():

    code_id = session.get("verified_reset_code_id")
    reset_company_id = session.get("reset_company_id")
    reset_email = session.get("reset_email")

    if not code_id or not reset_company_id or not reset_email:
        return redirect(url_for("forgot_password"))

    code_doc = db["password_codes"].find_one({
        "_id": ObjectId(code_id),
        "company_id": reset_company_id,
        "email": reset_email,
        "used": False
    })

    if not code_doc:
        return redirect(url_for("forgot_password"))

    if code_doc["expires_at"] < datetime.utcnow():
        return render_template(
            "reset_password.html",
            message="El código expiró. Solicita uno nuevo."
        )

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if len(password) < 6:
            return render_template(
                "reset_password.html",
                message="La contraseña debe tener al menos 6 caracteres."
            )

        if password != confirm_password:
            return render_template(
                "reset_password.html",
                message="Las contraseñas no coinciden."
            )

        db["users"].update_one(
            {
                "_id": ObjectId(code_doc["user_id"]),
                "company_id": reset_company_id,
                "email": reset_email
            },
            {
                "$set": {
                    "password": generate_password_hash(password),
                    "updated_at": datetime.utcnow()
                }
            }
        )

        db["password_codes"].update_one(
            {"_id": ObjectId(code_id)},
            {
                "$set": {
                    "used": True,
                    "used_at": datetime.utcnow()
                }
            }
        )

        session.pop("reset_company_id", None)
        session.pop("reset_email", None)
        session.pop("verified_reset_code_id", None)

        return render_template(
            "login.html",
            message="Contraseña actualizada correctamente. Ya puedes iniciar sesión."
        )

    return render_template("reset_password.html")


# =========================
# ADMIN EMPRESA
# =========================

@app.route("/admin/home")
@admin_required
def admin_home():

    users = list(db["users"].find({
        "company_id": session["company_id"]
    }))

    return render_template(
        "admin_home.html",
        users=users
    )
# =========================
# ADMIN EMPRESA
# =========================

def check_user_limit():
    company_id = session.get("company_id")

    company_doc = db["companies"].find_one({
        "_id": ObjectId(company_id)
    })

    if company_doc:
        plan_key = company_doc.get("plan", "basic")
    else:
        plan_key = session.get("company_plan", "basic")

    allowed_users = max_users(plan_key)

    # None significa usuarios ilimitados
    if allowed_users is None:
        return None

    current_users = db["users"].count_documents({
        "company_id": company_id
    })

    if current_users >= allowed_users:
        session["upgrade_message"] = (
            f"Tu plan actual permite hasta {allowed_users} usuarios. "
            "Mejora tu plan para agregar más usuarios."
        )
        return redirect(url_for("plans.company_plans"))

    return None

@app.route("/create-user", methods=["POST"])
@admin_required
def create_user():

    blocked = check_user_limit()

    if blocked:
        return blocked

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if not name or not email or not password:
        session["upgrade_message"] = "Completa nombre, correo y contraseña para crear el usuario."
        return redirect(url_for("admin_home"))

    exists = db["users"].find_one({
        "company_id": session["company_id"],
        "email": email
    })

    if exists:
        session["upgrade_message"] = "Ya existe un usuario registrado con ese correo."
        return redirect(url_for("admin_home"))

    user_doc = {
        "company_id": session["company_id"],
        "name": name,
        "email": email,
        "password": generate_password_hash(password),
        "role": "user",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }

    db["users"].insert_one(user_doc)

    return redirect(url_for("admin_home"))


@app.route("/admin/personalizacion", methods=["GET", "POST"])
@admin_required
def personalizacion():

    company_id = session.get("company_id")

    company_doc = db["companies"].find_one({
        "_id": ObjectId(company_id)
    })

    if not company_doc:
        return redirect(url_for("login"))

    if request.method == "POST":
        color = request.form.get("color", "#8fd8b7")

        db["companies"].update_one(
            {"_id": ObjectId(company_id)},
            {
                "$set": {
                    "theme_color": color,
                    "updated_at": datetime.utcnow()
                }
            }
        )

        session["theme_color"] = color

        return redirect(url_for("personalizacion"))

    return render_template(
        "personalizacion.html",
        color=company_doc.get("theme_color", "#8fd8b7")
    )


# =========================
# USUARIO NORMAL
# =========================

@app.route("/user/home")
@login_required
def user_home():

    return render_template("user_home.html")


# =========================
# LOGOUT
# =========================

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# =========================
# PERSONALIZACIÓN PDF
# =========================

ALLOWED_LOGO_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


def allowed_logo_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_LOGO_EXTENSIONS
    )

@app.route("/empresa/pdf-branding", methods=["GET", "POST"])
@app.route("/empresa/pdf-branding/", methods=["GET", "POST"])
@admin_required
def pdf_branding():
    print("ENTRÉ A PDF BRANDING:", request.method)

    company_id = session.get("company_id")

    try:
        company_doc = db["companies"].find_one({
            "_id": ObjectId(company_id)
        })
    except Exception:
        company_doc = None

    if not company_doc:
        return redirect(url_for("login"))

    plan_key = company_doc.get("plan", session.get("company_plan", "basic"))

    if not has_feature(plan_key, "pdf_branding"):
        session["upgrade_message"] = (
            "Tu plan actual no incluye personalización de PDF. "
            "Mejora tu plan para agregar logo y marca de agua."
        )
        return redirect(url_for("plans.company_plans"))

    branding = company_doc.get("pdf_branding", {}) or {}

    if request.method == "POST":
        print("FORMULARIO RECIBIDO:", request.form)

        logo_text = request.form.get("logo_text", "").strip()
        company_email = request.form.get("company_email", "").strip()
        company_phone = request.form.get("company_phone", "").strip()
        company_address = request.form.get("company_address", "").strip()
        watermark_text = request.form.get("watermark_text", "").strip()
        remove_logo = request.form.get("remove_logo", "")

        updated_branding = {
            "logo_text": logo_text,
            "company_email": company_email,
            "company_phone": company_phone,
            "company_address": company_address,
            "watermark_text": watermark_text,
            "logo_image": branding.get("logo_image", "")
        }

        upload_folder = os.path.join(
            app.root_path,
            "static",
            "uploads",
            "pdf_logos"
        )

        os.makedirs(upload_folder, exist_ok=True)

        if remove_logo == "1":
            old_logo = branding.get("logo_image", "")

            if old_logo:
                old_logo_path = os.path.join(
                    app.root_path,
                    "static",
                    old_logo.replace("/", os.sep)
                )

                if os.path.exists(old_logo_path):
                    try:
                        os.remove(old_logo_path)
                    except Exception:
                        pass

            updated_branding["logo_image"] = ""

        logo_file = request.files.get("logo_file")

        if logo_file and logo_file.filename:
            if not allowed_logo_file(logo_file.filename):
                flash("Formato de logo no permitido. Usa PNG, JPG, JPEG o WEBP.", "danger")
                return redirect(url_for("pdf_branding"))

            extension = secure_filename(logo_file.filename).rsplit(".", 1)[1].lower()
            filename = f"{company_id}_logo.{extension}"

            file_path = os.path.join(upload_folder, filename)
            logo_file.save(file_path)

            updated_branding["logo_image"] = f"uploads/pdf_logos/{filename}"

        db["companies"].update_one(
            {
                "_id": ObjectId(company_id)
            },
            {
                "$set": {
                    "pdf_branding": updated_branding,
                    "updated_at": datetime.utcnow()
                }
            }
        )

        print("PDF BRANDING GUARDADO:", updated_branding)

        flash("Configuración de PDF guardada correctamente ✅", "success")
        return redirect(url_for("pdf_branding"))

    return render_template(
        "empresa/pdf-branding.html",
        branding=branding
    )

# =========================
# EJECUCIÓN
# =========================

if __name__ == "__main__":
    print("RUTAS REGISTRADAS:")
    print(app.url_map)
    app.run(debug=True, port=5051)