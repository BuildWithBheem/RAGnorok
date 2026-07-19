# ⚡ RAGnorok

**A self-hosted, multi-tenant Retrieval-Augmented Generation API — your documents, your data, your machine.**

RAGnorok turns any PDF into a queryable knowledge base. Upload a document, ask it questions in plain English, and get grounded answers pulled straight from the source text — no OpenAI key, no cloud vector DB, no data leaving your infrastructure.

---

## 🧠 What it does

1. **Ingests** a PDF, splits it into overlapping chunks, and embeds each chunk into a 384-dimensional vector.
2. **Indexes** those vectors per-user in a dedicated FAISS index on disk, while the raw chunk text and metadata live in MySQL.
3. **Retrieves** the top-k most relevant chunks for a natural-language question via similarity search.
4. **Generates** a short, grounded answer using a locally-running LLM (Ollama) — constrained to only use retrieved context.

Every user gets their own isolated FAISS index and API key. Documents are content-hashed, so re-uploading the same PDF is a no-op instead of a duplicate.

---

## 🏗️ Architecture

```
                     ┌─────────────────────┐
                     │   Client / Frontend  │
                     └──────────┬──────────┘
                                │  API Key (auth)
                                ▼
                     ┌─────────────────────┐
                     │   FastAPI Gateway    │
                     │  /create_key         │
                     │  /upload_file        │
                     │  /ask                │
                     └──────────┬──────────┘
                                │
              ┌─────────────────┼─────────────────┐
              ▼                 ▼                 ▼
    ┌──────────────────┐ ┌─────────────┐ ┌───────────────────┐
    │  RecursiveCharacter│ │  MySQL      │ │  FAISS (per-user)  │
    │  TextSplitter      │ │  users      │ │  IndexIDMap +      │
    │  + SentenceTransformer│ chunk table│ │  IndexFlatL2(384)  │
    │  (all-MiniLM-L6-v2)│ └─────────────┘ └───────────────────┘
    └──────────────────┘                            │
              │                                     │
              ▼                                     ▼
    ┌───────────────────────────────────────────────────────┐
    │        Ollama (qwen2.5:1.5b) — grounded generation      │
    └───────────────────────────────────────────────────────┘
```

---

## 🔧 Tech Stack

| Layer               | Technology                                      |
|---------------------|--------------------------------------------------|
| API Framework       | FastAPI                                          |
| Embeddings          | `sentence-transformers` (`all-MiniLM-L6-v2`, 384-dim) |
| Vector Search       | FAISS (`IndexIDMap` + `IndexFlatL2`, per-user index files) |
| Relational Storage  | MySQL (chunk text, document metadata, user auth) |
| Text Chunking       | LangChain `RecursiveCharacterTextSplitter`       |
| LLM Inference       | Ollama (`qwen2.5:1.5b`), fully local              |
| PDF Parsing         | `pypdf`                                          |
| Auth                | API-key based, per-user isolation                |

---

## 📡 API Reference

### `POST /create_key`
Registers a new user and issues an API key.

**Request**
```json
{
  "user": "bheem"
}
```

**Response**
```json
{
  "api_key": "generated-api-key-here"
}
```
If the username already exists, returns `{"User": "A username like this already exists"}`.

---

### `POST /upload_file`
Uploads a PDF, chunks it, embeds it, and adds it to the caller's personal FAISS index.

**Form Data**
| Field      | Type   | Description                       |
|------------|--------|------------------------------------|
| `input`    | file   | The PDF to ingest                  |
| `usr_name` | string | Username                           |

**Headers**
| Header  | Description        |
|---------|---------------------|
| Auth    | API key (via `Depends(get_user)`) |

**Response**
```json
{ "Result": "Uploaded !" }
```
- Documents are SHA-256 hashed, so re-uploading an identical file returns `{"result": "PDF already Exists !"}` instead of duplicating vectors.
- Chunking: 500 characters per chunk, 120-character overlap.

---

### `POST /ask`
Asks a question against a previously uploaded document.

**Request**
```json
{
  "query": "What is the main conclusion of the paper?",
  "user_name": "bheem",
  "doc_id": "sha256-document-hash"
}
```

**Response**
```json
{ "response": "The paper concludes that..." }
```
Internally: embeds the query → retrieves top-5 nearest chunks from FAISS → filters by `document_id` and user in MySQL → feeds the retrieved context to `qwen2.5:1.5b` with a strict "answer only from context" system prompt → returns a cleaned, single-line response.

If no relevant chunks are found: `{"response": "I couldn't find any relevant information in this document."}`

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10+
- MySQL Server running locally
- [Ollama](https://ollama.com) installed with the model pulled:
  ```bash
  ollama pull qwen2.5:1.5b
  ```

### Installation
```bash
git clone https://github.com/BuildWithBheem/RAGnorok.git
cd RAGnorok
pip install -r requirements.txt
```

### Database Setup
Create the database and required tables:
```sql
CREATE DATABASE rag_db;
USE rag_db;

CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(255) UNIQUE NOT NULL,
    api_key VARCHAR(255) UNIQUE NOT NULL
);

CREATE TABLE chunk (
    vector_id BIGINT NOT NULL,
    document_id VARCHAR(64) NOT NULL,
    chunk_text TEXT NOT NULL,
    id INT NOT NULL,
    FOREIGN KEY (id) REFERENCES users(id)
);
```

### Environment
Update the MySQL credentials in the app (host, user, password) and ensure a `vector_db/` directory exists for FAISS index persistence:
```bash
mkdir vector_db
```

### Run
```bash
uvicorn main:app --reload
```

---

## 🔐 Multi-Tenancy & Isolation

- Every user's FAISS index is a **separate file** (`vector_db/user{id}`) — no cross-contamination between users' documents.
- Every query is scoped by `user_id` **and** `document_id` at the SQL layer, so retrieval never leaks chunks from other documents or other users, even if vector IDs collide.
- API keys gate every endpoint except registration.

---

## 🗺️ Upcoming Improvements

- [ ] Async DB access
- [ ] Configurable chunk size / overlap / top-k per request
- [ ] Swap MySQL chunk storage for a hybrid store (e.g., SQLite + FAISS metadata) for lighter local deployments
- [ ] Rate limiting per API key
- [ ] Multi-document querying (cross-document `/ask`)


*Built by [Bheem](https://github.com/BuildWithBheem)*
