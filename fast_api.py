from pypdf import PdfReader
import hashlib
import ollama
from sentence_transformers import SentenceTransformer
import faiss
from fastapi import FastAPI,UploadFile,File,Depends
from langchain_text_splitters import RecursiveCharacterTextSplitter
import uuid
import numpy as np
from pydantic import BaseModel
import mysql.connector
import os
import re
from Authenticate import get_user,api_key_generator
app = FastAPI()

model = SentenceTransformer("all-MiniLM-L6-v2")
pswd = 'bheem@3052006'

connection = mysql.connector.connect(
    host = 'localhost',
    user = 'root',
    password = pswd,
    database = 'rag_db'
)

sql_comm = connection.cursor()  # Execution of commands

class Queries(BaseModel):
    query : str

class User(BaseModel):
    user_name : str

if os.path.exists("vector_db/index.faiss"):
    index = faiss.read_index("vector_db/index.faiss")
else:
    index = faiss.IndexIDMap(faiss.IndexFlatL2(384))

@app.post("/create_key")
def authenticate_user(usr_name: User):
    get_id = api_key_generator(usr_name.user_name)

    return {"api_key": get_id}

@app.post("/upload_file")

async def pdf_upload(input: UploadFile = File(...),auth : int = Depends(get_user)):
    if auth is None:
        return {"result": "API KEY NOT FOUND !"}
    file_bytes = await input.read()
    pdf = PdfReader(input.file)

    text = ""

    for page in pdf.pages:
        pdf_ext = page.extract_text()

        if pdf_ext:
            text += pdf_ext + "\n"

    chunker = RecursiveCharacterTextSplitter(
                chunk_size=500,
                chunk_overlap=120,
                separators=["\n\n", "\n", " ", ""]
    )
    
    chunks = chunker.split_text(text)

    embeddings = model.encode(chunks,show_progress_bar=True)

    embeddings = embeddings.astype('float32')

    # Generating vector IDs
    document_id = hashlib.sha256(file_bytes).hexdigest()[:32]
    sql_comm.execute("select * from chunk where document_id = %s LIMIT 1",(document_id,))
    if sql_comm.fetchone():
        return {"result": "PDF already Exists !"}
    vector_ids = np.array([uuid.uuid4().int >> 65 for i in range(len(chunks))],dtype = np.int64)
    # Put unique 64 bit ids in an array


    # Insert into MySQL database

    for i in range(len(chunks)):
        vector_id = vector_ids[i]

        # Add to FAISS

        index.add_with_ids(np.array([embeddings[i]],dtype=np.float32),
                           np.array([vector_id], dtype=np.int64)
                           )
        sql_comm.execute(
            """
            INSERT INTO CHUNK (vector_id, document_id, chunk_text)
            VALUES (%s ,%s ,%s)
            """, (int(vector_id),document_id,chunks[i])
        )

    connection.commit()
    faiss.write_index(index,"vector_db/uid")

    return{"Result": "Uploaded !"}

@app.post("/ask")
def Query(user_query: Queries, auth: int = Depends(get_user)):
    if auth is None:
        return {"result": "API KEY NOT FOUND !"}
    ask = user_query.query
    embed_qry = model.encode([ask]).astype(np.float32)

    D, I = index.search(embed_qry,5)

    vector_ids = I[0]

    vector_ids = [int(i) for i in vector_ids if i!= -1]   # Prevents edge case of unable to find chunks

    chunk_numbers = ",".join(["%s"]*len(vector_ids)) # Creates (%s,%s,%s...upto len(vector_ids))

    sql_comm.execute(
        f"""
    SELECT chunk_text FROM chunk WHERE vector_id IN ({chunk_numbers})
        """, vector_ids
    )

    retr_chunks = sql_comm.fetchall()
    context = "\n\n".join(row[0] for row in retr_chunks)

    response = ollama.chat(
        model = 'qwen2.5:1.5b',
        messages= [
           { 
            'role' : 'system',
            'content' : """You are a PDF Assistant, answer to the user's queries according to the context only. 
            Keep the answers short and simple"""
           },
           {
               'role' : 'user',
               'content': f"question: {ask}, context: {context}"
           }
        ],
        options = {"temperature": 0.4}  # Keep answers grounded and improvise if no info is found
    )
    response_refined = response["message"]["content"]
    response_refined = re.sub("\n+"," ", response_refined).strip()
    return {"response": response_refined}