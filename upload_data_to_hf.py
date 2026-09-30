"""
Carica i file dati nel bucket HuggingFace oracle-live-storage.
Esegui una volta sola dal PC prima di spegnerlo.

pip install huggingface_hub
"""
import os
from huggingface_hub import HfApi

REPO_ID = "Fabio14i/oracle-live-storage"
REPO_TYPE = "model"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

FILES_TO_UPLOAD = [
    "oracle_brain.pkl",
    "oracle_brain_candidate.pkl",
    "Matches.csv",
    "oracle_data.db",
    "vip_members.db",
    "live_training_data.csv",
    "web_stats.json",
    "Performance_Log.csv",
    "EloRatings.csv",
    "missing_teams_queue.json",
]

api = HfApi()

for fname in FILES_TO_UPLOAD:
    local_path = os.path.join(BASE_DIR, fname)
    if not os.path.exists(local_path):
        print(f"SKIP (non trovato): {fname}")
        continue
    size_mb = os.path.getsize(local_path) / 1024 / 1024
    print(f"Uploading {fname} ({size_mb:.1f} MB)...")
    api.upload_file(
        path_or_fileobj=local_path,
        path_in_repo=fname,
        repo_id=REPO_ID,
        repo_type=REPO_TYPE,
    )
    print(f"  OK: {fname}")

print("\nUpload completato.")
