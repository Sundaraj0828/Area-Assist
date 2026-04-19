from pymongo import MongoClient
from flask import current_app

client = None
db = None

def get_db():
    global client, db
    if client is None:
        client = MongoClient(current_app.config['MONGO_URI'])
        db = client.get_database()
    return db

def get_collection(collection_name):
    return get_db()[collection_name]
