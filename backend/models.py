from db import db
from datetime import datetime
import json
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
    # Per-sentence transcription confidence data, stored as a JSON string so
    # the confidence colouring on the Transcript page survives a reload from History.
    sentence_confidences = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def get_sentence_confidences(self):
        """Return the stored sentence confidences as a Python list (empty if none/invalid)."""
        if not self.sentence_confidences:
            return []
        try:
            data = json.loads(self.sentence_confidences)
            return data if isinstance(data, list) else []
        except (ValueError, TypeError):
            return []

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
        def full_name(person):
            if not person:
                return ''
            parts = [person.title or '', person.first_name, person.last_name]
            return ' '.join(p for p in parts if p).strip()

        return {
            "id": self.id,
            "doctor_id": self.doctor_id,
            "patient_id": self.patient_id,
            "doctorName": full_name(self.doctor),
            "patientName": full_name(self.patient),
            "transcript": self.transcript,
            "aiSummary": self.summary,
            "soap": self.parse_soap_notes(),
            "sentence_confidences": self.get_sentence_confidences(),
            "created_at": self.created_at.isoformat()
        }