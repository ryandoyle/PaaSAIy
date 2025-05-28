import os
import random
import string
import subprocess
import tempfile
import json
import shutil
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

class ExecutionHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    app_id = db.Column(db.Integer, db.ForeignKey('app.id'), nullable=False)
    code = db.Column(db.Text, nullable=False)
    output = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    app = db.relationship('App', backref=db.backref('execution_history', lazy=True))

class AppExecutor:
    def __init__(self, app_entry):
        self.app_entry = app_entry
        self.generated_code = None
        self.temp_path = None
        self.python_cmd = 'python'

    def generate_code(self):
        """Generate Python code using OpenAI."""
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": 
            """You are a Python expert. 
            Generate a complete, runnable Python application based on the user's prompt. 
            The code should be well-documented and follow best practices. 
            It must only return the raw python script that can be copied and pasted into a file and run. 
            Do not return any markdown formatting.
            
            Important: Any user inputs or configuration values should be read from environment variables using os.getenv() and will 
            pe prefixed with AIPAAS_. 
            Do not use input() or hardcoded values.
            Example: If the user asks for a number use number = os.getenv('AIPAAS_NUMBER')"""
            },
                {"role": "user", "content": self.app_entry.prompt}
            ]
        )
        self.generated_code = response.choices[0].message.content
        return self.generated_code

    def create_temp_file(self):
        """Create a temporary file with the generated code."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as temp_file:
            temp_file.write(self.generated_code)
            self.temp_path = temp_file.name
        return self.temp_path

    def cleanup(self):
        """Clean up temporary files."""
        if self.temp_path and os.path.exists(self.temp_path):
            os.unlink(self.temp_path)

    def execute(self, env_vars=None):
        """Execute the generated code with the given environment variables."""
        if env_vars is None:
            env_vars = {}
            
        # Include the system PATH in the environment variables
        env_vars.update({'PATH': os.environ.get('PATH', '')})

        try:
            # Create temporary file if not already created
            if not self.temp_path:
                self.create_temp_file()

            # Run the code in a subprocess
            result = subprocess.run(
                [self.python_cmd, self.temp_path],
                capture_output=True,
                text=True,
                env=env_vars,
                timeout=30  # 30 second timeout
            )

            # Store execution history
            output = result.stdout if result.returncode == 0 else result.stderr
            history = ExecutionHistory(
                app_id=self.app_entry.id,
                code=self.generated_code,
                output=output
            )
            db.session.add(history)
            db.session.commit()

            return {
                'success': result.returncode == 0,
                'output': output,
                'error': result.stderr if result.returncode != 0 else None
            }

        except subprocess.TimeoutExpired:
            output = 'Error: Application execution timed out after 30 seconds'
            history = ExecutionHistory(
                app_id=self.app_entry.id,
                code=self.generated_code,
                output=output
            )
            db.session.add(history)
            db.session.commit()
            return {
                'success': False,
                'output': output,
                'error': output
            }
        except Exception as e:
            output = f'Error executing application: {str(e)}'
            history = ExecutionHistory(
                app_id=self.app_entry.id,
                code=self.generated_code,
                output=output
            )
            db.session.add(history)
            db.session.commit()
            return {
                'success': False,
                'output': output,
                'error': str(e)
            }
        finally:
            self.cleanup()

    def detect_content_type(self, output):
        """Detect the content type of the output."""
        content_type = 'text/plain'
        
        # Try to detect JSON
        try:
            json.loads(output)
            content_type = 'application/json'
        except:
            # Try to detect HTML
            if output.strip().startswith('<!DOCTYPE') or output.strip().startswith('<html'):
                content_type = 'text/html'
            # Try to detect XML
            elif output.strip().startswith('<?xml') or output.strip().startswith('<root'):
                content_type = 'application/xml'
            # Try to detect CSV
            elif ',' in output and '\n' in output and len(output.split('\n')[0].split(',')) > 1:
                content_type = 'text/csv'
            # Try to detect markdown
            elif any(marker in output for marker in ['# ', '## ', '### ', '* ', '- ']):
                content_type = 'text/markdown'

        return content_type

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

@app.route('/app/<route>', methods=['GET'])
def run_app(route):
    try:
        # Get the app entry from the database
        app_entry = App.query.filter_by(route=route).first()
        if not app_entry:
            return jsonify({'error': 'Application not found'}), 404

        # Render the app template
        return render_template('app.html', route=route, prompt=app_entry.prompt)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/app/<route>/execute', methods=['GET'])
def execute_app(route):
    try:
        # Get the app entry from the database
        app_entry = App.query.filter_by(route=route).first()
        if not app_entry:
            return jsonify({'error': 'Application not found'}), 404

        try:
            # Create executor and run the app
            executor = AppExecutor(app_entry)
            executor.generate_code()
            
            # Prepare environment variables
            env = {}
            for key, value in request.args.items():
                env[f'AIPAAS_{key.upper()}'] = value

            result = executor.execute(env)

            if not result['success']:
                return jsonify({
                    'code': executor.generated_code,
                    'output': result['error']
                })

            return jsonify({
                'code': executor.generated_code,
                'output': result['output']
            })

        except Exception as e:
            return jsonify({
                'error': f'Error generating code: {str(e)}',
                'code': None,
                'output': None
            }), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/app/<route>/history', methods=['GET'])
def get_execution_history(route):
    try:
        # Get the app entry from the database
        app_entry = App.query.filter_by(route=route).first()
        if not app_entry:
            return jsonify({'error': 'Application not found'}), 404

        # Get execution history, ordered by most recent first
        history = ExecutionHistory.query.filter_by(app_id=app_entry.id).order_by(ExecutionHistory.created_at.desc()).all()
        
        return jsonify({
            'history': [{
                'code': entry.code,
                'output': entry.output,
                'created_at': entry.created_at.strftime('%Y-%m-%d %H:%M:%S')
            } for entry in history]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/app/<route>/delete', methods=['POST'])
def delete_app(route):
    try:
        app_entry = App.query.filter_by(route=route).first_or_404()
        
        # Delete all associated execution history records first
        ExecutionHistory.query.filter_by(app_id=app_entry.id).delete()
        
        # Now delete the app entry
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

@app.route('/app/<route>/run', methods=['GET'])
def run_app_output(route):
    try:
        # Get the app entry from the database
        app_entry = App.query.filter_by(route=route).first()
        if not app_entry:
            return jsonify({'error': 'Application not found'}), 404

        try:
            # Create executor and run the app
            executor = AppExecutor(app_entry)
            executor.generate_code()
            
            # Prepare environment variables
            env = {}
            for key, value in request.args.items():
                env[f'AIPAAS_{key.upper()}'] = value

            result = executor.execute(env)

            if not result['success']:
                return result['error'], 500, {'Content-Type': 'text/plain'}

            # Detect content type and return output
            content_type = executor.detect_content_type(result['output'])
            return result['output'], 200, {'Content-Type': content_type}

        except Exception as e:
            return str(e), 500, {'Content-Type': 'text/plain'}
    except Exception as e:
        return str(e), 500, {'Content-Type': 'text/plain'}

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=3000) 