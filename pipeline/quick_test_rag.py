from rag_pipeline import setup_knowledge_base, get_relevant_context

transcript = """
SPEAKER_0: Since yesterday I have chest pain and shortness of breath.
SPEAKER_1: Any fever, cough, or prior cardiac history?
SPEAKER_0: Mild fever, no prior heart disease.
"""

vs = setup_knowledge_base(
kb_path="data/knowledge_base",
chroma_path="data/chroma_db",
csv_whitelist=["webbeteg_fogalomtar.csv", "clinical_lab_facts.csv", "DDI_data_clean.csv"],
#force_rebuild=True
)

ctx = get_relevant_context(
transcript,
vs,
final_k=5,
retrieve_k=12,
max_queries=8
)

print("Retrieved context:")
print(ctx)