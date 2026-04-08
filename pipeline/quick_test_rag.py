import time

start_time = time.time()
print("Starting imports at timestamp:", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
from rag_pipeline import setup_knowledge_base, get_relevant_context
import os
transcript = """
SPEAKER_0: Since yesterday I have chest pain and shortness of breath.
SPEAKER_1: Any fever, cough, or prior cardiac history?
SPEAKER_0: Mild fever, no prior heart disease.
"""
base_dir = os.path.dirname(os.path.abspath(__file__))

print("Started knowledge base retrieval at timestamp:", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
vs = setup_knowledge_base(
    kb_path=os.path.join(base_dir, "..", "data", "knowledge_base"),
    chroma_path=os.path.join(base_dir, "..", "data", "chroma_db"),
    csv_whitelist=["clinical_lab_facts.csv", "DDI_data_clean.csv"],
)

ctx = get_relevant_context(
transcript,
vs,
final_k=5,
retrieve_k=8,
max_queries=4,
include_icd_suggestions=True,
icd_path=os.path.join(base_dir, "..", "data", "icd10_codes.txt")
)
end_time = time.time()
print(f"RAG retrieval took {end_time - start_time:.2f} seconds")

print("Retrieved context:")
print(ctx)  