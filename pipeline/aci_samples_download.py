from datasets import load_dataset
import json
import os

# load just the test split (smallest)
ds = load_dataset("ClinicianFOCUS/ACI-Bench-Refined", split="test")

# look at what fields are available
print(ds.column_names)
print(ds[0])  # print first sample

os.makedirs("../data/aci_bench_samples", exist_ok=True)

for i in range(5):
    sample = ds[i]
    
    # adjust column names based on what print(ds.column_names) showed you
    dialogue = sample.get("dialogue") or sample.get("conversation") or sample.get("text")
    note = sample.get("note") or sample.get("clinical_note") or sample.get("summary")

    with open(f"../data/aci_bench_samples/sample_{i+1}_transcript.txt", "w", encoding="utf-8") as f:
        f.write(dialogue)

    with open(f"../data/aci_bench_samples/sample_{i+1}_groundtruth.txt", "w", encoding="utf-8") as f:
        f.write(note)

    print(f"Sample {i+1} saved.")