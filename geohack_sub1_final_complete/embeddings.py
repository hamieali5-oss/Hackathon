from langchain_community.embeddings import HuggingFaceEmbeddings

EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

def get_embedder():
    return HuggingFaceEmbeddings(model_name=EMBED_MODEL)
