📘 README.md — GeoHackathon 2025 — Subchallenge 1
🛢️ GeoHackathon 2025 — Subchallenge 1
RAG-based Summarization of Well Reports (Improved Solution)

CPU–only • Open-source LLM • ChromaDB • Sentence-Transformers • LangChain

📌 Obiettivo

Produrre un riassunto tecnico (≤ N parole) di un report PDF (NLOG style),
utilizzando una pipeline Retrieval-Augmented Generation (RAG):

Indicizzazione PDF → chunking → embeddings → ChromaDB

Recupero dei chunk rilevanti

Prompt engineering controllato per evitare allucinazioni

Generazione del summary tramite google/flan-t5-base (CPU-only)

Output finale con citazioni (file + pagina)

La soluzione rispetta tutte le linee guida del GeoHackathon.

📂 Struttura del progetto
geohack_sub1/
│
├── README.md
├── requirements.txt
│
└── src/
    ├── cli.py
    ├── ingest.py
    ├── splitter.py
    ├── embeddings.py
    ├── vectorstore.py
    ├── rag_chain.py
    ├── summary.py
    └── utils.py  (opzionale)

🔧 Installazione

Attiva una virtualenv (Windows/Mac/Linux):

python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt

📥 1) Inserisci i PDF

Metti tutti i file PDF nella cartella:

data/raw/


Crea la cartella se non esiste:

mkdir -p data/raw

🧱 2) Costruisci l’indice RAG (ChromaDB)
python -m src.cli index --docs data/raw --index data/index


Parametri opzionali:

--chunk-size (default 800)

--chunk-overlap (default 120)

L’indice verrà creato in:

data/index/

📝 3) Ottieni un riassunto tecnico (≤ N parole) con citazioni

Esempio:

python -m src.cli summarize \
    --doc data/raw/WellReport-12.pdf \
    --index data/index \
    --words 200 \
    --k 20


Output:

Riassunto (stampato a schermo)

Citazioni (file + pagina)

File JSON salvato automaticamente:

data/index/WellReport-12.summary.json

🔍 4) Debug: vedere i chunk recuperati dal sistema
python -m src.cli preview \
    --index data/index \
    --query "completion and well test data" \
    --k 5

🤖 Dettagli tecnici della pipeline
🔹 Embeddings

sentence-transformers/all-MiniLM-L6-v2 (CPU-friendly, 384-d)

🔹 Vector Store

ChromaDB persistente su disco

🔹 Retriever

Semantic search

Over-retrieval (k * 3)

Filtro preferenziale dei chunk appartenenti al PDF target

🔹 LLM

google/flan-t5-base

Pipeline HuggingFace Transformers

CPU-only

🔹 Prompt di generazione

Caratteristiche:

“Answer from context only”

Word limit rigoroso

Zero allucinazioni

Preserva dati numerici (depth, pressure, rates)

🧪 Esempio di comando completo
python -m src.cli summarize \
    --doc data/raw/NLOG-Report-05.pdf \
    --index data/index \
    --words 180 \
    --k 24 \
    --query "well completion, testing data, reservoir, production overview"

🟦 Compatibilità

Python 3.9+

CPU-only

Testato su Windows 10, Ubuntu 22, macOS M1 (emulazione CPU)

🏁 Stato del progetto

✔ Subchallenge 1 completata (RAG + summary + citations)

⏳ Subchallenge 2 — extraction pipeline (verrà integrata)

⏳ Subchallenge 3 — nodal analysis + agent system (verrà integrata)
