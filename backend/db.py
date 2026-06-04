from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

db = SQLAlchemy()

def _migrate(db):
    """Add any new columns to existing tables without dropping data."""
    with db.engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(consultations)"))}
        new_cols = {
            "cpu_usage": "REAL",
            "sentence_confidences": "TEXT",
            "original_summary": "TEXT",
            "original_soap_notes": "TEXT",
            "edited_at": "DATETIME",
        }
        for col, col_type in new_cols.items():
            if col not in cols:
                conn.execute(text(f"ALTER TABLE consultations ADD COLUMN {col} {col_type}"))
        conn.commit()


def init_db(app):
    db.init_app(app)
    with app.app_context():
        db.create_all()
        _migrate(db)
