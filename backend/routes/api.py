import os
import sys
import json
from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename
from models import db
import models as md
import cpu_monitor

# Add project root to sys.path so we can import 'pipeline'
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

try:
    from pipeline.medical_pipeline import transcribe_audio, summarize_transcript, summarize_soap_notes
except ImportError as e:
    print(f"Error importing pipeline modules: {e}")
    # Placeholder functions if import fails (for testing backend structure without pipeline deps)
    def transcribe_audio(*args): return "Mock Transcript", [], 0.0
    def summarize_transcript(*args): return "Mock Summary"
    def summarize_soap_notes(*args): return "Subjective: ... Objective: ... Assessment: ... Plan: ..."

api_bp = Blueprint('api', __name__)

ALLOWED_EXTENSIONS = {'mp3', 'wav', 'm4a', 'flac', 'webm'}

@api_bp.route('/cpu/start', methods=['POST'])
def cpu_start():
    cpu_monitor.start()
    return jsonify({'status': 'monitoring started'}), 200

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ── Doctors ───────────────────────────────────────────────────────────────────

@api_bp.route('/doctors', methods=['GET'])
def get_doctors():
    doctors = md.Doctor.query.order_by(md.Doctor.last_name).all()
    return jsonify([d.to_dict() for d in doctors]), 200

@api_bp.route('/doctors', methods=['POST'])
def create_doctor():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    if not data.get('first_name') or not data.get('last_name'):
        return jsonify({'error': 'first_name and last_name are required'}), 400

    doctor = md.Doctor(
        title=data.get('title') or None,
        first_name=data['first_name'].strip(),
        last_name=data['last_name'].strip(),
    )
    db.session.add(doctor)
    db.session.commit()
    return jsonify(doctor.to_dict()), 201


# ── Patients ──────────────────────────────────────────────────────────────────

@api_bp.route('/patients', methods=['GET'])
def get_patients():
    patients = md.Patient.query.order_by(md.Patient.last_name).all()
    return jsonify([p.to_dict() for p in patients]), 200

@api_bp.route('/patients', methods=['POST'])
def create_patient():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    if not data.get('first_name') or not data.get('last_name'):
        return jsonify({'error': 'first_name and last_name are required'}), 400

    from datetime import date
    dob = None
    if data.get('date_of_birth'):
        try:
            dob = date.fromisoformat(data['date_of_birth'])
        except ValueError:
            return jsonify({'error': 'Invalid date_of_birth format, use YYYY-MM-DD'}), 400

    patient = md.Patient(
        title=data.get('title') or None,
        first_name=data['first_name'].strip(),
        last_name=data['last_name'].strip(),
        date_of_birth=dob,
        taj_number=data.get('taj_number') or None,
    )
    db.session.add(patient)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'error': 'TAJ number already exists'}), 409
    return jsonify(patient.to_dict()), 201


# ── Consultations ─────────────────────────────────────────────────────────────

@api_bp.route('/process', methods=['POST'])
def process_audio():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if not (file and allowed_file(file.filename)):
        return jsonify({'error': 'Invalid file type'}), 400

    doctor_id = request.form.get('doctor_id')
    patient_id = request.form.get('patient_id')
    if not doctor_id or not patient_id:
        return jsonify({'error': 'doctor_id and patient_id are required'}), 400

    filename = secure_filename(file.filename)
    if not os.path.exists(current_app.config['UPLOAD_FOLDER']):
        os.makedirs(current_app.config['UPLOAD_FOLDER'])

    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

        try:
            cpu_avg = cpu_monitor.stop()

            gladia_token = current_app.config.get('GLADIA_TOKEN')
            groq_token = current_app.config.get('GROQ_TOKEN')
 
            if not gladia_token or not groq_token:
                print("Warning: Missing API tokens.")
 
            # 1. Transcribe
            transcript, sentence_confidences, transcription_confidence_avg = transcribe_audio(filepath, gladia_token)

        print("SENTENCE CONFIDENCES:", sentence_confidences)
        print("TRANSCRIPTION CONFIDENCE AVG:", transcription_confidence_avg)

        if not transcript:
            transcript = ""

        print("TRANSCRIPT:", transcript)

        summary = summarize_transcript(transcript, groq_token)
        soap_notes = summarize_soap_notes(transcript, groq_token)

        consultation = md.Consultation(
            doctor_id=int(doctor_id),
            patient_id=int(patient_id),
            transcript=transcript,
            summary=summary,
            soap_notes=soap_notes,
            cpu_usage=cpu_avg,
            sentence_confidences=json.dumps(sentence_confidences or [])
        )
        db.session.add(consultation)
        db.session.commit()

        return jsonify({
            'message': 'Processing complete',
            'data': {
                'id': consultation.id,
                'transcript': transcript,
                'summary': summary,
                'soap_notes': soap_notes,
                'sentence_confidences': sentence_confidences,
                'transcription_confidence_avg': transcription_confidence_avg
            }
        }), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@api_bp.route('/history', methods=['GET'])
def get_history():
    consultations = md.Consultation.query.order_by(md.Consultation.created_at.desc()).all()
    return jsonify([c.to_dict() for c in consultations]), 200


@api_bp.route('/consultations/<int:consultation_id>', methods=['PATCH'])
def update_consultation(consultation_id):
    """
    Update the editable fields of a consultation (AI summary and/or SOAP notes).
    This is what makes a doctor's edits persist when they revisit the note in History.

    Accepts JSON with any of:
      - summary: str               → the edited AI summary
      - soap: { subjective, objective, assessment, plan }  → edited SOAP fields
    """
    consultation = md.Consultation.query.get(consultation_id)
    if not consultation:
        return jsonify({'error': 'Consultation not found'}), 404

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    if 'summary' in data:
        consultation.summary = data['summary']

    if 'soap' in data and isinstance(data['soap'], dict):
        soap = data['soap']
        # Re-serialize into the labelled text format that parse_soap_notes() understands,
        # so the structured note round-trips correctly on the next load.
        consultation.soap_notes = (
            f"Subjective: {soap.get('subjective', '').strip()}\n"
            f"Objective: {soap.get('objective', '').strip()}\n"
            f"Assessment: {soap.get('assessment', '').strip()}\n"
            f"Plan: {soap.get('plan', '').strip()}"
        )

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

    return jsonify({'message': 'Consultation updated', 'data': consultation.to_dict()}), 200