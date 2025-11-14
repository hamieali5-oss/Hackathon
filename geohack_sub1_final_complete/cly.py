import argparse
from pathlib import Path
from rich import print

from ingest import load_pdf
from splitter import split_documents
from embeddings import get_embedder
from vectorstore import build_index, load_index
from rag_chain import build_rag_chain
from summary import generate_summary


def cmd_index(args):
    docs_folder = Path(args.docs)
    index_dir = Path(args.index)
    index_dir.mkdir(parents=True, exist_ok=True)

    pdf_files = sorted(docs_folder.glob("*.pdf"))
    if not pdf_files:
        print("[red]No PDF files found in the docs folder.[/red]")
        return

    all_docs = []
    for pdf in pdf_files:
        d = load_pdf(pdf)
        all_docs.extend(d)

    splits = split_documents(all_docs, chunk_size=args.chunk_size, chunk_overlap=args.chunk_overlap)
    embedder = get_embedder()
    build_index(splits, embedder, index_dir)

    print(f"[green]Indexing complete. Total chunks: {len(splits)}[/green]")


def cmd_summarize(args):
    index_dir = Path(args.index)
    pdf_path = Path(args.doc)

    docs = load_pdf(pdf_path)
    db = load_index(index_dir, get_embedder())
    chain = build_rag_chain()

    summary = generate_summary(
        pdf_path=pdf_path,
        docs=docs,
        db=db,
        rag_chain=chain,
        word_limit=args.words,
        k_retrieve=args.k,
        global_query=args.query
    )

    print("\n[bold]SUMMARY:[/bold]\n")
    print(summary["summary"])

    print("\n[bold]Citations:[/bold]")
    for c in summary["citations"]:
        print(f"- {c['file']} (page {c['page']})")

    out_json = index_dir / f"{pdf_path.stem}.summary.json"
    out_json.write_text(summary["full_json"], encoding="utf-8")
    print(f"[green]Saved:[/green] {out_json}")


def cmd_preview(args):
    db = load_index(Path(args.index), get_embedder())
    hits = db.similarity_search(args.query, k=args.k)

    print({"query": args.query, "topk": args.k})
    for h in hits:
        print(f"[{Path(h.metadata['source']).name} p.{h.metadata['page']}] {h.page_content[:300]}...")


def main():
    parser = argparse.ArgumentParser(description="GeoHackathon Subchallenge 1 — Improved RAG System")
    sub = parser.add_subparsers(dest="cmd")

    p_idx = sub.add_parser("index", help="Build a Chroma index from PDFs")
    p_idx.add_argument("--docs", required=True)
    p_idx.add_argument("--index", required=True)
    p_idx.add_argument("--chunk-size", type=int, default=800)
    p_idx.add_argument("--chunk-overlap", type=int, default=120)
    p_idx.set_defaults(func=cmd_index)

    p_sum = sub.add_parser("summarize", help="Summarize a PDF")
    p_sum.add_argument("--doc", required=True)
    p_sum.add_argument("--index", required=True)
    p_sum.add_argument("--words", type=int, default=200)
    p_sum.add_argument("--query", type=str, default=None)
    p_sum.add_argument("--k", type=int, default=20)
    p_sum.set_defaults(func=cmd_summarize)

    p_prev = sub.add_parser("preview", help="Preview retrieved chunks")
    p_prev.add_argument("--index", required=True)
    p_prev.add_argument("--query", required=True)
    p_prev.add_argument("--k", type=int, default=5)
    p_prev.set_defaults(func=cmd_preview)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
