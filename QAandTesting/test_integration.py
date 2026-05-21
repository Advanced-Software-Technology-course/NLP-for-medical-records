import io
import os
import sys
import pytest

# Add backend path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../backend')))

from app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config['TESTING'] = True

    with app.test_client() as client:
        yield client


# ---------------------------------------------------
# TEST 1: API HEALTH CHECK
# ---------------------------------------------------

def test_api_root(client):
    response = client.get('/')

    assert response.status_code == 200

    data = response.get_json()

    assert "message" in data
    assert data["message"] == "Medical Records API is running"


# ---------------------------------------------------
# TEST 2: INVALID FILE TYPE
# ---------------------------------------------------

def test_invalid_file_upload(client):
    data = {
        'file': (io.BytesIO(b"not audio"), 'test.txt')
    }

    response = client.post(
        '/api/process',
        data=data,
        content_type='multipart/form-data'
    )

    assert response.status_code == 400

    json_data = response.get_json()

    assert "error" in json_data
    assert json_data["error"] == "Invalid file type"


# ---------------------------------------------------
# TEST 3: NO FILE PROVIDED
# ---------------------------------------------------

def test_no_file_upload(client):
    response = client.post(
        '/api/process',
        data={},
        content_type='multipart/form-data'
    )

    assert response.status_code == 400

    json_data = response.get_json()

    assert "error" in json_data
    assert json_data["error"] == "No file part"


# ---------------------------------------------------
# TEST 4: EMPTY FILENAME
# ---------------------------------------------------

def test_empty_filename(client):
    data = {
        'file': (io.BytesIO(b''), '')
    }

    response = client.post(
        '/api/process',
        data=data,
        content_type='multipart/form-data'
    )

    assert response.status_code == 400

    json_data = response.get_json()

    assert "error" in json_data
    assert json_data["error"] == "No selected file"


# ---------------------------------------------------
# TEST 5: VALID AUDIO FILE
# ---------------------------------------------------

def test_valid_audio_upload(client):
    audio_path = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            '../data/test_audio/test_audio.mp3'
        )
    )

    if not os.path.exists(audio_path):
        pytest.skip("Test audio file not found")

    with open(audio_path, 'rb') as audio:
        data = {
            'file': (audio, 'test_audio.mp3')
        }

        response = client.post(
            '/api/process',
            data=data,
            content_type='multipart/form-data'
        )

    assert response.status_code == 200

    json_data = response.get_json()

    assert "message" in json_data
    assert json_data["message"] == "Processing complete"

    assert "data" in json_data

    result = json_data["data"]

    assert "transcript" in result
    assert "summary" in result
    assert "soap_notes" in result

    assert isinstance(result["transcript"], str)
    assert isinstance(result["summary"], str)
    assert isinstance(result["soap_notes"], str)