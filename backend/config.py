import os
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN_FILE = os.path.join(BASE_DIR, ".api_token.json")

def load_tokens():
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading tokens: {e}")
            return {}
    return {}

tokens = load_tokens()


def get_app_data_dir():
    # Prefer LOCALAPPDATA on Windows; fall back to APPDATA and then home dir.
    base_appdata = (
        os.getenv("LOCALAPPDATA")
        or os.getenv("APPDATA")
        or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    )
    app_dir = os.path.join(base_appdata, "NLPMedicalRecords")
    os.makedirs(app_dir, exist_ok=True)
    return app_dir


class Config:
    APP_DATA_DIR = get_app_data_dir()
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(APP_DATA_DIR, 'medical.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'backend', 'uploads')
    GLADIA_TOKEN = tokens.get("gladia-token")
    GROQ_TOKEN = tokens.get("groq-token")

    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)

