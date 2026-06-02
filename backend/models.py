from db import db
from datetime import datetime
import re

class Doctor(db.Model):
    __tablename__ = 'doctors'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(50), nullable=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    consultations = db.relationship('Consultation', backref='doctor', lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "created_at": self.created_at.isoformat()
        }


class Patient(db.Model):
    __tablename__ = 'patients'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(50), nullable=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    date_of_birth = db.Column(db.Date, nullable=True)
    taj_number = db.Column(db.String(20), nullable=True, unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    consultations = db.relationship('Consultation', backref='patient', lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "date_of_birth": self.date_of_birth.isoformat() if self.date_of_birth else None,
            "taj_number": self.taj_number,
            "created_at": self.created_at.isoformat()
        }


class Consultation(db.Model):
    __tablename__ = 'consultations'

    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey('doctors.id'), nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    transcript = db.Column(db.Text, nullable=True)
    summary = db.Column(db.Text, nullable=True)
    soap_notes = db.Column(db.Text, nullable=True)
    cpu_usage = db.Column(db.Float, nullable=True)
    cpu_usage = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def parse_soap_notes(self):
        """Attempts to parse the SOAP notes string into a dictionary."""
        if not self.soap_notes:
            return {k: '' for k in ['subjective', 'objective', 'assessment', 'plan']}

        text = self.soap_notes
        sections = {
            'subjective': '',
            'objective': '',
            'assessment': '',
            'plan': ''
        }

        patterns = {
            'subjective': re.compile(r'subjective[:\-\s]*(.*?)(?=(?:objective|assessment|plan)|\Z)', re.IGNORECASE | re.DOTALL),
            'objective': re.compile(r'objective[:\-\s]*(.*?)(?=(?:assessment|plan)|\Z)', re.IGNORECASE | re.DOTALL),
            'assessment': re.compile(r'assessment[:\-\s]*(.*?)(?=(?:plan)|\Z)', re.IGNORECASE | re.DOTALL),
            'plan': re.compile(r'plan[:\-\s]*(.*?)(?=\Z)', re.IGNORECASE | re.DOTALL)
        }

        for key, pattern in patterns.items():
            match = pattern.search(text)
            if match:
                sections[key] = match.group(1).strip()

        if all(v == '' for v in sections.values()):
            sections['subjective'] = text

        return sections

    def to_dict(self):
        return {
            "id": self.id,
            "doctor_id": self.doctor_id,
            "patient_id": self.patient_id,
            "transcript": self.transcript,
            "aiSummary": self.summary,
            "soap": self.parse_soap_notes(),
            "cpu_usage": self.cpu_usage,
            "cpu_usage": self.cpu_usage,
            "created_at": self.created_at.isoformat()
        }