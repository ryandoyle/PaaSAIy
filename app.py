import os
import random
import string
import subprocess
import tempfile
from datetime import datetime

from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
import openai

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'user_apps'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///apps.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database
db = SQLAlchemy(app)

# Configure OpenAI
openai.api_key = os.getenv('OPENAI_API_KEY')

class App(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    route = db.Column(db.String(10), unique=True, nullable=False)
    prompt = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    def to_dict(self):
        return {
            'route': self.route,
            'prompt': self.prompt,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }

# Create database tables
with app.app_context():
    db.create_all()

def generate_route():
    """Generate a random 6-character route."""
    while True:
        route = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
        if not App.query.filter_by(route=route).first():
            return route

def generate_python_code(prompt):
    """Generate Python code based on the user's prompt using OpenAI."""
    try:
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": """You are a Python expert. Generate only the Python code without any explanations or markdown formatting. The code should be complete and runnable.
Important: Any user inputs or configuration values should be read from environment variables using os.getenv(). Do not use input() or hardcoded values.
Example: If the user needs to provide a number, use: number = os.getenv('AIPAAS_NUMBER')"""},
                {"role": "user", "content": f"Create a Python script that: {prompt}"}
            ],
            temperature=0.7,
            max_tokens=1000
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        raise Exception(f"Error generating code: {str(e)}")

@app.route('/')
def index():
    # Get all apps, ordered by creation date (newest first)
    apps = App.query.order_by(App.created_at.desc()).all()
    return render_template('index.html', apps=apps)

@app.route('/register', methods=['POST'])
def register_app():
    prompt = request.form.get('prompt')
    if not prompt:
        return jsonify({'error': 'No prompt provided'}), 400
    
    try:
        # Generate a unique route
        route = generate_route()
        
        # Store the prompt in the database
        app_entry = App(route=route, prompt=prompt)
        db.session.add(app_entry)
        db.session.commit()
        
        return jsonify({
            'message': 'Application registered successfully',
            'route': route
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/app/<route>', methods=['GET', 'POST'])
def run_app(route):
    try:
        # Get the app entry from the database
        app_entry = App.query.filter_by(route=route).first()
        if not app_entry:
            return jsonify({'error': 'Application not found'}), 404

        if request.method == 'POST':
            try:
                # Generate code using OpenAI
                response = openai.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": """You are a Python expert. Generate a complete, runnable Python application based on the user's prompt. The code should be well-documented and follow best practices. It must only return the raw python script that can be copied and pasted into a file and run. Do not return any markdown formatting.
Important: Any user inputs or configuration values should be read from environment variables using os.getenv() and will pe prefixed with AIPAAS_. Do not use input() or hardcoded values.
Example: If the user asks for a number use number = os.getenv('AIPAAS_NUMBER')"""},
                        {"role": "user", "content": app_entry.prompt}
                    ]
                )
                generated_code = response.choices[0].message.content

                # Create a temporary file to store the generated code
                with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as temp_file:
                    temp_file.write(generated_code)
                    temp_path = temp_file.name

                try:
                    # Prepare environment variables for the subprocess
                    env = {} # os.environ.copy()
                    for key, value in request.args.items():
                        env[f'AIPAAS_{key.upper()}'] = value

                    # Run the code in a subprocess
                    result = subprocess.run(
                        ['python3', temp_path],
                        capture_output=True,
                        text=True,
                        env=env,
                        timeout=30  # 30 second timeout
                    )

                    # Clean up the temporary file
                    os.unlink(temp_path)

                    # Check if there was an error
                    if result.returncode != 0:
                        return jsonify({
                            'code': generated_code,
                            'output': f'Error executing application:\n{result.stderr}'
                        })

                    # Return the output
                    output = result.stdout or 'Application executed successfully.'
                    return jsonify({
                        'code': generated_code,
                        'output': output
                    })

                except subprocess.TimeoutExpired:
                    os.unlink(temp_path)
                    return jsonify({
                        'code': generated_code,
                        'output': 'Error: Application execution timed out after 30 seconds'
                    })
                except Exception as e:
                    os.unlink(temp_path)
                    return jsonify({
                        'code': generated_code,
                        'output': f'Error executing application: {str(e)}'
                    })

            except Exception as e:
                return jsonify({
                    'error': f'Error generating code: {str(e)}',
                    'code': None,
                    'output': None
                }), 500
        else:
            # For GET requests, render the app template
            return render_template('app.html', route=route, prompt=app_entry.prompt)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/app/<route>/delete', methods=['POST'])
def delete_app(route):
    app_entry = App.query.filter_by(route=route).first_or_404()
    try:
        db.session.delete(app_entry)
        db.session.commit()
        return jsonify({'message': 'Application deleted successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/app/<route>/update-prompt', methods=['POST'])
def update_prompt(route):
    try:
        app_entry = App.query.filter_by(route=route).first()
        if not app_entry:
            return jsonify({'error': 'Application not found'}), 404

        data = request.get_json()
        if not data or 'prompt' not in data:
            return jsonify({'error': 'No prompt provided'}), 400

        new_prompt = data['prompt'].strip()
        if not new_prompt:
            return jsonify({'error': 'Prompt cannot be empty'}), 400

        app_entry.prompt = new_prompt
        db.session.commit()

        return jsonify({'message': 'Prompt updated successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True) 