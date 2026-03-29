import time

start_time = time.time()
print("Starting imports at timestamp:", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
from rag_pipeline import setup_knowledge_base, get_relevant_context

transcript = """
SPEAKER_0: Since yesterday I have chest pain and shortness of breath.
SPEAKER_1: Any fever, cough, or prior cardiac history?
SPEAKER_0: Mild fever, no prior heart disease.
"""
print("Started knowledge base retrieval at timestamp:", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
vs = setup_knowledge_base(
kb_path="../data/knowledge_base",
chroma_path="../data/chroma_db",
csv_whitelist=["clinical_lab_facts.csv", "DDI_data_clean.csv"],
#force_rebuild=True
)

ctx = get_relevant_context(
transcript,
vs,
final_k=5,
retrieve_k=8,
max_queries=4
)
end_time = time.time()
print(f"RAG retrieval took {end_time - start_time:.2f} seconds")

print("Retrieved context:")
print(ctx)