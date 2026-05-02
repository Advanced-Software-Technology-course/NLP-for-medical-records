from flask import Flask, jsonify
from flask_cors import CORS
from config import Config
from db import init_db, db
from routes.api import api_bp
# Import models to ensure they are registered for create_all
from models import Consultation

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Initialize CORS
    CORS(app)

    # Initialize DB
    init_db(app)

    # Initialize Blueprints
    app.register_blueprint(api_bp, url_prefix='/api')

    @app.route('/')
    def index():
        return jsonify({"message": "Medical Records API is running"})

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, port=5000)

