from pypdf import PdfReader
import hashlib
import ollama
from sentence_transformers import SentenceTransformer
import faiss
from fastapi import FastAPI,UploadFile,File,Depends,Form
from fastapi.middleware.cors import CORSMiddleware
from langchain_text_splitters import RecursiveCharacterTextSplitter
import uuid
import numpy as np
from pydantic import BaseModel
import mysql.connector
import os
import re
import io
from Authenticate import get_user,api_key_generator

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

model = SentenceTransformer("all-MiniLM-L6-v2")
pswd = '********************'

connection = mysql.connector.connect(
    host = 'localhost',
    user = 'root',
    password = pswd,
    database = 'rag_db'
)

sql_comm = connection.cursor()  # Execution of commands

class Queries(BaseModel):
    query : str
    user_name : str
    doc_id:str
class create_user(BaseModel):
    user : str
@app.post("/create_key")
def authenticate_user(usr_name: create_user):
    sql_comm.execute('''select id from users where username = %s''',(usr_name.user,))

    if not sql_comm.fetchone():
        get_id = api_key_generator(usr_name.user,)
        return {"api_key": get_id}
    else:
        return {"User": "A username like this already exists"}

@app.post("/upload_file")

async def pdf_upload(input: UploadFile = File(...),usr_name : str = Form(...),auth : int = Depends(get_user)):
    if auth is None:
        return {"result": "API KEY NOT FOUND !"}
    
    user_id = auth

    file_bytes = await input.read() # Reaches EOF
    pdf = PdfReader(io.BytesIO(file_bytes)) # To read the file from the beginning

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
    sql_comm.execute("select * from chunk where document_id = %s and id = %s LIMIT 1",(document_id,user_id))
    if sql_comm.fetchone():
        return {"result": "PDF already Exists !"}
    vector_ids = np.array([uuid.uuid4().int >> 65 for i in range(len(chunks))],dtype = np.int64)
    # Put unique 64 bit ids in an array

    if os.path.exists(f"vector_db/user{user_id}"):
        index = faiss.read_index(f"vector_db/user{user_id}")
    else:
        index = faiss.IndexIDMap(faiss.IndexFlatL2(384))

    # Insert into MySQL database

    for i in range(len(chunks)):
        vector_id = vector_ids[i]

        # Add to FAISS

        index.add_with_ids(np.array([embeddings[i]],dtype=np.float32),
                           np.array([vector_id], dtype=np.int64)
                           )
        sql_comm.execute(
            """
            INSERT INTO CHUNK (vector_id, document_id, chunk_text,id)
            VALUES (%s ,%s ,%s,%s)
            """, (int(vector_id),document_id,chunks[i],user_id)
        )

    connection.commit()

    faiss.write_index(index,f"vector_db/user{user_id}")
    return{"Result": "Uploaded !"}

@app.post("/ask")
def Query(user_query: Queries, auth: int = Depends(get_user)):
    if auth is None:
        return {"result": "API KEY NOT FOUND !"}
    ask = user_query.query
    embed_qry = model.encode([ask]).astype(np.float32)

    user_id = auth
    index = faiss.read_index(f"vector_db/user{user_id}")
    D, I = index.search(embed_qry,5)

    vector_ids = I[0]

    vector_ids = [int(i) for i in vector_ids if i!= -1]   # Prevents edge case of unable to find chunks

    if not vector_ids:
        return {"response": "I couldn't find any relevant information in this document."}
    
    chunk_numbers = ",".join(["%s"]*len(vector_ids)) # Creates (%s,%s,%s...upto len(vector_ids))
    sql_comm.execute(
        f"""
    SELECT chunk_text
FROM chunk
WHERE vector_id IN ({chunk_numbers})
  AND id = %s
  AND document_id = %s
        """, (*vector_ids,user_id,user_query.doc_id)
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