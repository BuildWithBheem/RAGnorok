import mysql.connector
from fastapi import HTTPException,Header
pswd = "*******************"
connection = mysql.connector.connect(
host = 'localhost',
    user = 'root',
    password = pswd,
    database = 'rag_db'

)

sql_comm = connection.cursor()

import secrets   # Module for secure generation of passkeys

def api_key_generator(username):
    api_key  = secrets.token_hex()

    sql_comm.execute("insert into users (username,api_key) values (%s,%s) ",(username,api_key,))

    connection.commit()

    return api_key

def get_user(user_api: str = Header(...,convert_underscores=False)):

    sql_comm.execute("select id from users where api_key = %s",(user_api,))

    key = sql_comm.fetchone()

    if not key:
        return None
    
    return key[0]
