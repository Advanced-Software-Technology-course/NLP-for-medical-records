import os
import sys
from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename
from models import Consultation, db

try:
    from pipeline.medical_pipeline import transcribe_audio, summarize_transcript, summarize_soap_notes
except ImportError as e:
    print(f"Error importing pipeline modules: {e}")
    # Placeholder functions if import fails (for testing backend structure without pipeline deps)
    def transcribe_audio(*args): return "Mock Transcript"
    def summarize_transcript(*args): return "Mock Summary"
    def summarize_soap_notes(*args): return "Subjective: ... Objective: ... Assessment: ... Plan: ..."

api_bp = Blueprint('api', __name__)

ALLOWED_EXTENSIONS = {'mp3', 'wav', 'm4a', 'flac'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@api_bp.route('/process', methods=['POST'])
def process_audio():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        # Ensure upload folder exists
        if not os.path.exists(current_app.config['UPLOAD_FOLDER']):
            os.makedirs(current_app.config['UPLOAD_FOLDER'])
            
        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        try:
            gladia_token = current_app.config.get('GLADIA_TOKEN')
            groq_token = current_app.config.get('GROQ_TOKEN')

            if not gladia_token or not groq_token:
               print("Warning: Missing API tokens.")

            # 1. Transcribe
            transcript = transcribe_audio(filepath, gladia_token)

            # 2. Summarize
            summary = summarize_transcript(transcript, groq_token)

            # 3. SOAP Notes
            soap_notes = summarize_soap_notes(transcript, groq_token)

            # 4. Save to DB
            consultation = Consultation(
                transcript=transcript,
                summary=summary,
                soap_notes=soap_notes
            )
            db.session.add(consultation)
            db.session.commit()

            return jsonify({
                'message': 'Processing complete',
                'data': consultation.to_dict()
            }), 200

        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500

    return jsonify({'error': 'Invalid file type'}), 400

@api_bp.route('/history', methods=['GET'])
def get_history():
    consultations = Consultation.query.order_by(Consultation.created_at.desc()).all()
    return jsonify([c.to_dict() for c in consultations]), 200
