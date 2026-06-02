from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

db = SQLAlchemy()

def _migrate(db):
    """Add any new columns to existing tables without dropping data."""
    with db.engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(consultations)"))}
        if "cpu_usage" not in cols:
            conn.execute(text("ALTER TABLE consultations ADD COLUMN cpu_usage REAL"))
            conn.commit()


def init_db(app):
    db.init_app(app)
    with app.app_context():
        db.create_all()
        _migrate(db)
