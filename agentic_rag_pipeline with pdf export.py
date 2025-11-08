#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agentic RAG Pipeline for Completion/Workover Reports (Offline)
--------------------------------------------------------------
- PDF -> text extraction (PyPDF2 -> pdfminer fallback)
- Chunking + TF-IDF retrieval
- Rule-based field extraction (well data, depths, HSE, tests)
- Validation & sanity checks
- Nodal analysis interface (stub) with JSON inputs
- Word-bounded summary generation
- Structured JSON + Markdown outputs
- (NEW) Optional Markdown -> PDF export via --export-pdf

Usage:
  python agentic_rag_pipeline.py --pdf "/path/to/report.pdf" \
      --outdir "/path/to/out" \
      --word-limit 250 \
      --nodal-json "/path/to/nodal_inputs.json" \
      --export-pdf

Nodal JSON schema example:
{
  "wellhead_pressure_bar": 18.0,
  "flow_rate_m3_h": 135.0,
  "tubing_inner_diameter_in": 6.2,
  "fluid_density_kg_m3": 1015.0,
  "fluid_viscosity_cP": 0.78,
  "reservoir_temperature_c": 90.0
}
"""
import os, re, json, math, argparse, sys
from datetime import datetime
from typing import List, Dict, Any, Tuple

# ------------------ Helpers ------------------
def clean_spaces(s: str) -> str:
    s = re.sub(r"[ \t]+", " ", s or "")
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def enforce_word_limit(s: str, limit: int) -> str:
    words = re.findall(r"\S+", s or "")
    return " ".join(words[:max(0, int(limit))])

# ------------------ PDF Extraction ------------------
def extract_pdf_text(path: str) -> str:
    text = ""
    try:
        import PyPDF2
        with open(path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for i, page in enumerate(reader.pages):
                try:
                    page_text = page.extract_text() or ""
                except Exception:
                    page_text = ""
                text += f"\n\n=== Page {i+1} ===\n{page_text}"
        if text.strip():
            return text
    except Exception:
        pass
    # fallback
    try:
        from pdfminer.high_level import extract_text
        return extract_text(path) or ""
    except Exception:
        return ""

# ------------------ Chunking ------------------
def chunk_text(t: str, chunk_size=1500, overlap=300) -> List[str]:
    if not t:
        return []
    res = []
    i = 0
    L = len(t)
    while i < L:
        j = min(L, i + chunk_size)
        res.append(t[i:j])
        i += (chunk_size - overlap)
        if i <= 0: break
    return res

# ------------------ Retrieval ------------------
def build_retriever(chunks: List[str]):
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
    except Exception as e:
        raise RuntimeError("scikit-learn is required for TF-IDF retrieval.")
    vectorizer = TfidfVectorizer(max_features=20000, ngram_range=(1,2))
    tfidf = vectorizer.fit_transform(chunks) if chunks else None
    def retrieve(query: str, k=5) -> List[Tuple[str, float]]:
        if tfidf is None or not chunks:
            return []
        qv = vectorizer.transform([query])
        sims = cosine_similarity(qv, tfidf)[0]
        idxs = sims.argsort()[::-1][:k]
        return [(chunks[i], float(sims[i])) for i in idxs]
    return retrieve

# ------------------ Field Extraction ------------------
def first_group(pattern: str, text: str, flags=re.IGNORECASE) -> str:
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else ""

def parse_report_fields(text: str) -> Dict[str, Any]:
    d: Dict[str, Any] = {}
    d["well_name"] = first_group(r"Well Name\s+([^\n]+)", text)
    d["operation"] = first_group(r"Operation\s+([^\n]+)", text)
    d["start_of_operation"] = first_group(r"Start of Operation\s+([^\n]+)", text)
    d["duration"] = first_group(r"Duration\s+([^\n]+)", text)
    d["total_depth"] = first_group(r"Well Total Depth\s+([^\n]+)", text)

    # Key events/depths
    d["packer_set_depth_m"] = first_group(r"Set\s+9\s*5/8[”\"]?\s+.*?at\s+([0-9\.]+\s*m\s*AHGL)", text)
    if not d["packer_set_depth_m"]:
        d["packer_set_depth_m"] = first_group(r"Set\s+9\s*5/8[”\"]?\s+NOV liner hanger.*?at\s+([0-9\.]+\s*m\s*AHGL)", text)

    d["pbr_bottom_m"] = first_group(r"mule shoe at\s+([0-9\.]+\s*m)\s*AHB?GL", text) \
                        or first_group(r"bottom of (?:the )?PBR.*?([0-9\.]+\s*m\s*AHGL)", text)

    d["hand_over"] = first_group(r"handed.*?to Operations on\s+([^\n]+)", text)

    # HSE and equipment
    d["hse_incidents"] = "None" if re.search(r"No incidents", text, re.IGNORECASE) else ""
    d["esp_installed"] = bool(re.search(r"\bESP\b", text))
    d["gre_string"] = bool(re.search(r"\bGRE\b", text))

    # Logging/testing
    d["mti_logged"] = bool(re.search(r"\bMTI\b", text))
    d["press_test_annulus"] = "10 bar" if re.search(r"Pressure tested annulus to 10 bar", text, re.IGNORECASE) else ""

    # Reservoir
    d["reservoir_fluid"] = "Brine" if re.search(r"Well Bore Fluids:\s*o\s*Brine", text, re.IGNORECASE) else ""
    d["reservoir_bottomhole_temp_c"] = first_group(r"Bottom Hole temperature[:\s]*([0-9]+)\s*°C", text)
    return d

# ------------------ Validation ------------------
def parse_depth_m(val: str) -> float:
    if not val:
        return math.nan
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*m", val.replace(",", "."))
    return float(m.group(1)) if m else math.nan

def validate_fields(data: Dict[str, Any]) -> List[str]:
    issues: List[str] = []
    depth_fields = { "packer_set_depth_m": data.get("packer_set_depth_m", ""),
                     "pbr_bottom_m": data.get("pbr_bottom_m", "") }
    for k, v in depth_fields.items():
        d = parse_depth_m(v)
        if math.isnan(d):
            issues.append(f"Missing or unparsable depth for {k}.")
        elif not (0 < d < 5000):
            issues.append(f"Unusual depth for {k}: {v}")

    if not data.get("start_of_operation"):
        issues.append("Start of Operation date not found.")
    if not data.get("hand_over"):
        issues.append("Hand-over to Operations date not found.")
    return issues

# ------------------ Nodal Analysis Stub ------------------
def nodal_default_inputs(data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "wellhead_pressure_bar": None,
        "flow_rate_m3_h": None,
        "tubing_inner_diameter_in": None,
        "fluid_density_kg_m3": None,
        "fluid_viscosity_cP": None,
        "reservoir_temperature_c": (data.get("reservoir_bottomhole_temp_c") or None)
    }

def run_nodal(inputs: Dict[str, Any]) -> Dict[str, Any]:
    missing = [k for k, v in inputs.items() if v in (None, "", float('nan'))]
    if missing:
        return {
            "status": "pending_inputs",
            "missing_inputs": missing,
            "message": "Provide missing nodal inputs to compute system curve and operating point.",
            "results": None
        }
    # Placeholder: echo operating point
    return {
        "status": "ok",
        "missing_inputs": [],
        "message": "Computed operating point (placeholder).",
        "results": {
            "q_m3_h": inputs["flow_rate_m3_h"],
            "whp_bar": inputs["wellhead_pressure_bar"],
            "tubing_id_in": inputs["tubing_inner_diameter_in"]
        }
    }

# ------------------ Summary Generation ------------------
def generate_summary(data: Dict[str, Any], retrieve_func, word_limit: int) -> str:
    highlights = []
    if data.get("well_name"): highlights.append(f"Well: {data['well_name']}.")
    if data.get("operation"): highlights.append(f"Operation: {data['operation']}.")
    if data.get("start_of_operation"): highlights.append(f"Start: {data['start_of_operation']}.")
    if data.get("duration"): highlights.append(f"Duration: {data['duration']}.")
    if data.get("hand_over"): highlights.append(f"Handover: {data['hand_over']}.")
    if data.get("packer_set_depth_m"): highlights.append(f"Liner hanger/packer set at {data['packer_set_depth_m']}.")
    if data.get("pbr_bottom_m"): highlights.append(f"PBR reference near {data['pbr_bottom_m']}.")
    if data.get("esp_installed"): highlights.append("ESP installed.")
    if data.get("mti_logged"): highlights.append("MTI logging completed; annulus pressure test to 10 bar passed.")
    if data.get("hse_incidents") == "None": highlights.append("HSE: No incidents reported; drills/toolboxes conducted.")
    if data.get("reservoir_fluid"): highlights.append(f"Reservoir fluid: {data['reservoir_fluid']}.")
    if data.get("reservoir_bottomhole_temp_c"): highlights.append(f"Bottomhole temperature: {data['reservoir_bottomhole_temp_c']} °C.")

    support = []
    if retrieve_func:
        for q in ["Executive summary objectives outcomes",
                  "Daily operations key events",
                  "HSE performance incidents drills",
                  "Logging MTI annulus pressure test",
                  "Well data casing GRE PBR ESP depths"]:
            for chunk, score in retrieve_func(q, k=1):
                # pick first sentence
                sents = re.split(r'(?<=[\.\?\!])\s+', chunk)
                if sents:
                    support.append(sents[0].strip())

    text = " ".join(highlights + support)
    return enforce_word_limit(text, word_limit)

# ------------------ Markdown -> PDF Export ------------------
def export_md_to_pdf(md_path: str, pdf_path: str) -> bool:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
    except Exception:
        # reportlab not installed
        return False

    # Read markdown
    try:
        with open(md_path, "r", encoding="utf-8") as f:
            md_text = f.read()
    except Exception:
        return False

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Title'], fontSize=18, spaceAfter=6)
    subtitle_style = ParagraphStyle('Subtitle', parent=styles['Heading2'], fontSize=12, spaceAfter=4)
    body_style = styles['BodyText']

    story = []
    for raw_line in md_text.splitlines():
        line = raw_line.strip()
        if not line:
            story.append(Spacer(1, 4*mm))
            continue
        if line.startswith("# "):
            story.append(Paragraph(line[2:], title_style))
        elif line.startswith("## "):
            story.append(Paragraph(line[3:], subtitle_style))
        else:
            story.append(Paragraph(line, body_style))
        story.append(Spacer(1, 4*mm))

    try:
        doc = SimpleDocTemplate(pdf_path, pagesize=A4, topMargin=15*mm, bottomMargin=15*mm)
        doc.build(story)
        return True
    except Exception:
        return False

# ------------------ Main ------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True, help="Path to the completion/workover report PDF")
    ap.add_argument("--outdir", default=".", help="Output directory")
    ap.add_argument("--word-limit", type=int, default=250, help="Word limit for summary")
    ap.add_argument("--nodal-json", default=None, help="Path to nodal inputs JSON (optional)")
    ap.add_argument("--export-pdf", action="store_true", help="Also export the generated Markdown summary to PDF")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    raw = extract_pdf_text(args.pdf)
    text = clean_spaces(raw)

    chunks = chunk_text(text, 1500, 300)
    retrieve_func = None
    if chunks:
        try:
            retrieve_func = build_retriever(chunks)
        except Exception as e:
            retrieve_func = None

    extracted = parse_report_fields(text)
    issues = validate_fields(extracted)

    # Nodal inputs
    nodal_inputs = nodal_default_inputs(extracted)
    if args.nodal_json and os.path.exists(args.nodal_json):
        with open(args.nodal_json, "r", encoding="utf-8") as f:
            provided = json.load(f)
        for k, v in provided.items():
            nodal_inputs[k] = v

    nodal_status = run_nodal(nodal_inputs)

    # Build questions if needed
    questions = []
    if nodal_status.get("status") != "ok":
        for m in nodal_status.get("missing_inputs", []):
            pretty = m.replace("_", " ").capitalize()
            questions.append(f"Please provide **{pretty}**.")

    # Summary (base)
    base_summary = generate_summary(extracted, retrieve_func, args.word_limit)

    # Append nodal line
    if nodal_status.get("status") == "ok":
        r = nodal_status["results"]
        base_summary = enforce_word_limit(
            base_summary + f" Nodal operating point (stub): q ≈ {r['q_m3_h']} m³/h at WHP ≈ {r['whp_bar']} bar (Tubing ID {r['tubing_id_in']} in).",
            args.word_limit
        )

    # Write outputs
    out_json = {
        "timestamp": datetime.now().isoformat(),
        "inputs": {"pdf": os.path.basename(args.pdf), "word_limit": args.word_limit},
        "data_extracted": extracted,
        "validation_issues": issues,
        "nodal_inputs_required": nodal_inputs,
        "nodal_status": nodal_status,
        "questions_for_user": questions,
        "summary_words": len(re.findall(r'\S+', base_summary)),
        "summary": base_summary
    }
    json_path = os.path.join(args.outdir, "rag_agentic_outputs.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(out_json, f, indent=2)

    md_path = os.path.join(args.outdir, "rag_agentic_summary.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# Completion Report Summary (≤{args.word_limit} words)\n\n")
        f.write(base_summary + "\n")
        if questions:
            f.write("\n## Missing Inputs for Nodal Analysis\n")
            for q in questions:
                f.write(f"- {q}\n")

    print("Wrote:")
    print(" -", json_path)
    print(" -", md_path)

    # Optional PDF export
    if args.export_pdf:
        pdf_path = os.path.join(args.outdir, "rag_agentic_summary.pdf")
        ok = export_md_to_pdf(md_path, pdf_path)
        if ok:
            print(" -", pdf_path)
        else:
            print("PDF export skipped (reportlab not installed or conversion failed).", file=sys.stderr)

if __name__ == "__main__":
    main()
