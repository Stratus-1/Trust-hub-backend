# database.py
from motor.motor_asyncio import AsyncIOMotorClient
from os import getenv
from dotenv import load_dotenv
import pyodbc

load_dotenv()

# MongoDB setup
client = AsyncIOMotorClient(getenv("MONGO_URI"))
db = client["trust_registry"]
trusts_collection = db["trusts"]

# MSSQL setup
def get_mssql_connection():
    conn_str = getenv(
        "SQLSERVER_CONN",
        'DRIVER={ODBC Driver 18 for SQL Server};'
        'SERVER=136.144.191.59\\RBKSERVER;'
        'DATABASE=HKFT_Master;'
        'UID=RBK;'
        'PWD=RBK#4000;'
        'TrustServerCertificate=yes'
    )
    return pyodbc.connect(conn_str)

if __name__ == "__main__":
    try:
        conn = get_mssql_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")  # Simple test query
        result = cursor.fetchone()
        print("✅ MSSQL connection successful, test query result:", result)
        cursor.close()
        conn.close()
    except Exception as e:
        print("❌ MSSQL connection failed:", e)
