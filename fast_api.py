from pypdf import PdfReader
import ollama
from sentence_transformers import SentenceTransformer
import faiss
from fastapi import FastAPI,UploadFile,File
from langchain_text_splitters import RecursiveCharacterTextSplitter
import uuid
import numpy as np
from pydantic import BaseModel
import mysql.connector

app = FastAPI()

model = SentenceTransformer("all-MiniLM-L6-v2")
pswd = '********'

connection = mysql.connector.connect(
    host = 'localhost',
    user = 'root',
    password = pswd,
    database = 'rag_db'
)

sql_comm = connection.cursor()  # Execution of commands

faiss_db = faiss.IndexFlatL2(384)

index = faiss.IndexIDMap(faiss_db)  # For vector ids

class Queries(BaseModel):
    query : str

@app.post("/upload_file")

async def pdf_upload(input: UploadFile = File(...)):
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
    
    document_id = uuid.uuid4().hex
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

@app.post("/ask")
async def Query(user_query: Queries):
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
            'content' : "You are a PDF Assistant, answer to the user's queries according to the context only"
           },
           {
               'role' : 'user',
               'content': f"question: {ask}, context: {context}"
           }
        ]
    )

    return {"response": response["message"]["content"]}