from pymongo import MongoClient
from werkzeug.security import generate_password_hash
from datetime import datetime

client = MongoClient("mongodb://localhost:27017/")
db = client["multiempresa_pos"]

company_name = "DEVELOPER"
developer_email = "developer@storetrack.com"
developer_password = "123456"

company = db["companies"].find_one({"name": company_name})

if not company:
    result = db["companies"].insert_one({
        "name": company_name,
        "active": True,
        "theme_color": "#3b82f6",
        "created_at": datetime.utcnow()
    })

    company_id = str(result.inserted_id)
    print("Empresa DEVELOPER creada")
else:
    company_id = str(company["_id"])
    print("Empresa DEVELOPER ya existía")

user = db["users"].find_one({
    "company_id": company_id,
    "email": developer_email
})

if not user:
    db["users"].insert_one({
        "company_id": company_id,
        "name": "Developer",
        "email": developer_email,
        "password": generate_password_hash(developer_password),
        "role": "developer",
        "created_at": datetime.utcnow()
    })

    print("Usuario developer creado")
else:
    print("Usuario developer ya existía")

print("Datos de acceso:")
print("Empresa:", company_name)
print("Correo:", developer_email)
print("Contraseña:", developer_password)