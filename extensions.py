from pymongo import MongoClient

mongo_client = None
db = None

def init_mongo():
    global mongo_client, db

    mongo_client = MongoClient("mongodb://localhost:27017/")
    db = mongo_client["multiempresa_pos"]

    print("MongoDB conectado")
