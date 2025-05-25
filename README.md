# Python App Generator

A web application that generates and runs Python applications based on natural language prompts.

## Features

- Generate Python applications from natural language descriptions
- View the generated code before execution
- Run generated applications and view their output
- Modern, responsive UI built with Tailwind CSS
- Secure code generation and execution

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Create a `.env` file in the project root and add your OpenAI API key:
```
OPENAI_API_KEY=your_api_key_here
```

3. Run the application:
```bash
python app.py
```

4. Open your browser and navigate to `http://localhost:5000`

## Usage

1. Enter a description of the application you want to create in the text area
2. Click "Generate Application" to create the Python code
3. Review the generated code in the "Generated Code" section
4. The application will automatically run and display its output
5. Any errors or output will be shown in the output section

## Example Prompts

- "Create a program that calculates the Fibonacci sequence up to n numbers and displays them in a formatted table"
- "Write a script that reads a CSV file and creates a bar chart of the data using matplotlib"
- "Create a simple web scraper that extracts headlines from a news website"

## Security Notes

- Generated code is executed in a controlled environment
- File names are sanitized before saving
- Maximum code length is limited by the OpenAI API
- All generated code is saved for reference

## Directory Structure

```
.
├── app.py              # Main Flask application
├── requirements.txt    # Python dependencies
├── templates/         # HTML templates
│   └── index.html    # Main page template
└── user_apps/        # Directory for generated applications
``` 