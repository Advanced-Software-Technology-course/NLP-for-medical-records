from db import db
from datetime import datetime
import re

class Consultation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    transcript = db.Column(db.Text, nullable=True)
    summary = db.Column(db.Text, nullable=True)
    soap_notes = db.Column(db.Text, nullable=True)  # Storing as text
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
        
        # Simple regex to capture content between headers
        # Assumes S-O-A-P order roughly, but robust to missing sections
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
        
        # If no sections identified, put everything in Subjective or try to be helpful
        if all(v == '' for v in sections.values()):
             sections['subjective'] = text

        return sections

    def to_dict(self):
        return {
            "id": self.id,
            "transcript": self.transcript,
            "aiSummary": self.summary, # Frontend expects aiSummary
            "soap": self.parse_soap_notes(), # Return parsed object
            "created_at": self.created_at.isoformat()
        }
