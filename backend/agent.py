import os
import shutil
import subprocess
import json
import logging
from typing import Dict, Any, Tuple
import google.generativeai as genai

logger = logging.getLogger(__name__)

def clone_repo(repo_url: str, session_id: str) -> Tuple[bool, str]:
    """Clones a public Git repository into a temporary directory."""
    temp_dir = os.path.join(os.path.dirname(__file__), "temp_repos", session_id)
    
    # Clean directory if it exists
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)
        
    os.makedirs(temp_dir, exist_ok=True)
    
    try:
        # Shallow clone (depth=1) for speed
        subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, "."],
            cwd=temp_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            timeout=60 # 1 minute timeout
        )
        return True, temp_dir
    except subprocess.TimeoutExpired:
        return False, "Git clone timed out."
    except subprocess.CalledProcessError as e:
        err_msg = e.stderr.decode('utf-8', errors='ignore') or "Unknown Git error."
        return False, f"Failed to clone repository: {err_msg}"

def scan_codebase(repo_path: str) -> Dict[str, Any]:
    """Scans the file structure and checks key configuration files."""
    file_structure = []
    key_files = {}
    project_type = "other"
    
    # Scanned files limit to avoid blowing up LLM context
    max_files = 100
    file_count = 0
    
    for root, dirs, files in os.walk(repo_path):
        # Ignore git files and node_modules
        if ".git" in root or "node_modules" in root or "venv" in root or "__pycache__" in root:
            continue
            
        # Limit depth to 4
        rel_root = os.path.relpath(root, repo_path)
        depth = 0 if rel_root == "." else len(rel_root.split(os.sep))
        if depth > 4:
            continue
            
        for file in files:
            file_count += 1
            if file_count > max_files:
                break
                
            rel_path = os.path.join(rel_root, file) if rel_root != "." else file
            file_structure.append(rel_path)
            
            # Detect key files and read their contents
            lower_name = file.lower()
            if lower_name in ["package.json", "requirements.txt", "go.mod", "cargo.toml", "pom.xml", "gemfile", "dockerfile"]:
                full_path = os.path.join(root, file)
                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                        # Limit config file read size to 4000 characters
                        key_files[rel_path] = f.read(4000)
                except Exception as e:
                    key_files[rel_path] = f"Error reading file: {str(e)}"
                    
        if file_count > max_files:
            break
            
    # Detect project type based on files
    flat_files = [f.lower() for f in file_structure]
    if "package.json" in flat_files:
        project_type = "node"
    elif "requirements.txt" in flat_files or "pyproject.toml" in flat_files:
        project_type = "python"
    elif "go.mod" in flat_files:
        project_type = "go"
    
    return {
        "file_structure": file_structure,
        "key_files": key_files,
        "project_type": project_type
    }

def get_mock_dockerfile(project_type: str, attempt: int, behavior: str) -> Dict[str, Any]:
    """Generates mock Dockerfile response for simulation runs when API key is missing."""
    if project_type == "node":
        if attempt == 1 and behavior == "fail-and-fix":
            dockerfile = (
                "FROM node:20-alpine\n"
                "WORKDIR /app\n"
                "COPY package*.json ./\n"
                "RUN npm ci\n" # This will fail in simulation mode
                "COPY . .\n"
                "EXPOSE 3000\n"
                "CMD [\"npm\", \"start\"]\n"
            )
            rationale = "Initial NodeJS Dockerfile. Uses standard npm ci for clean installations."
        else:
            dockerfile = (
                "FROM node:20-alpine\n"
                "WORKDIR /app\n"
                "COPY package*.json ./\n"
                "RUN npm install --legacy-peer-deps\n" # Fixing the dependency issue
                "COPY . .\n"
                "EXPOSE 3000\n"
                "CMD [\"npm\", \"start\"]\n"
            )
            rationale = "Corrected NodeJS Dockerfile. Changed npm ci to npm install --legacy-peer-deps to resolve the ejs/express-ejs-layouts peer dependency conflict."
            
        docker_compose = (
            "version: '3.8'\n"
            "services:\n"
            "  web:\n"
            "    build: .\n"
            "    ports:\n"
            "      - '3000:3000'\n"
            "    environment:\n"
            "      - NODE_ENV=production\n"
        )
        return {
            "dockerfile": dockerfile,
            "docker_compose": docker_compose,
            "rationale": rationale,
            "project_type": "node",
            "port": 3000
        }
        
    elif project_type == "python":
        if attempt == 1 and behavior == "fail-and-fix":
            dockerfile = (
                "FROM python:3.11-slim\n"
                "WORKDIR /app\n"
                "COPY requirements.txt .\n"
                "RUN pip install -r requirements.txt\n" # This will fail because psycopg2 requires gcc / libpq-dev
                "COPY . .\n"
                "EXPOSE 8000\n"
                "CMD [\"python\", \"app.py\"]\n"
            )
            rationale = "Initial Python Dockerfile. Copies requirements and installs them directly."
        else:
            dockerfile = (
                "FROM python:3.11-slim\n"
                "WORKDIR /app\n"
                "RUN apt-get update && apt-get install -y libpq-dev gcc --no-install-recommends && rm -rf /var/lib/apt/lists/*\n" # Fix build dependencies
                "COPY requirements.txt .\n"
                "RUN pip install -r requirements.txt\n"
                "COPY . .\n"
                "EXPOSE 8000\n"
                "CMD [\"python\", \"app.py\"]\n"
            )
            rationale = "Corrected Python Dockerfile. Added gcc and libpq-dev apt dependencies to compile postgres driver binaries."
            
        docker_compose = (
            "version: '3.8'\n"
            "services:\n"
            "  api:\n"
            "    build: .\n"
            "    ports:\n"
            "      - '8000:8000'\n"
        )
        return {
            "dockerfile": dockerfile,
            "docker_compose": docker_compose,
            "rationale": rationale,
            "project_type": "python",
            "port": 8000
        }
        
    else: # Go / default
        if attempt == 1 and behavior == "fail-and-fix":
            dockerfile = (
                "FROM golang:1.21-alpine\n"
                "WORKDIR /app\n"
                "COPY go.mod go.sum ./\n"
                "RUN go build -o main .\n" # Fails: gorilla/mux missing in go.mod
                "COPY . .\n"
                "EXPOSE 8080\n"
                "CMD [\"./main\"]\n"
            )
            rationale = "Initial Go Dockerfile. Attempts compile directly."
        else:
            dockerfile = (
                "FROM golang:1.21-alpine\n"
                "WORKDIR /app\n"
                "COPY go.mod go.sum ./\n"
                "RUN go mod download && go build -o main .\n" # Correct mod download before build
                "COPY . .\n"
                "EXPOSE 8080\n"
                "CMD [\"./main\"]\n"
            )
            rationale = "Corrected Go Dockerfile. Fetches modules correctly using go mod download before compiler phase."
            
        docker_compose = (
            "version: '3.8'\n"
            "services:\n"
            "  server:\n"
            "    build: .\n"
            "    ports:\n"
            "      - '8080:8080'\n"
        )
        return {
            "dockerfile": dockerfile,
            "docker_compose": docker_compose,
            "rationale": rationale,
            "project_type": "go",
            "port": 8080
        }

def generate_dockerfile(analysis: Dict[str, Any], api_key: str = None) -> Dict[str, Any]:
    """Generates initial Dockerfile using Gemini API."""
    key = api_key or os.environ.get("GEMINI_API_KEY")
    
    if not key:
        logger.info("No Gemini API key available. Generating mock Dockerfile.")
        return get_mock_dockerfile(analysis["project_type"], 1, "always-success")
        
    prompt = f"""
    You are DockerForge, an expert agentic AI developer that generates optimal, working Dockerfiles and docker-compose.yml configurations for repositories.
    
    Analyze the following codebase structure and configuration files:
    
    Project Type: {analysis['project_type']}
    
    File Tree Structure:
    {json.dumps(analysis['file_structure'], indent=2)}
    
    Configuration Files Content:
    {json.dumps(analysis['key_files'], indent=2)}
    
    Determine the optimal base image, build steps, startup command, and exposed port.
    Generate a Dockerfile and docker-compose.yml configuration.
    
    Your response MUST be in raw JSON format matching this schema:
    {{
        "dockerfile": "complete Dockerfile contents as a single string",
        "docker_compose": "complete docker-compose.yml contents as a single string",
        "rationale": "short explanation of your architectural choices",
        "project_type": "node|python|go|other",
        "port": 3000 (detected integer port to expose)
    }}
    
    Do NOT wrap the output in markdown block symbols like ```json. Make sure the response is a pure JSON parseable string.
    """
    
    try:
        genai.configure(api_key=key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        data = json.loads(response.text)
        return data
    except Exception as e:
        logger.error(f"Gemini generation error: {str(e)}. Falling back to mock generator.")
        return get_mock_dockerfile(analysis["project_type"], 1, "always-success")

def correct_dockerfile(dockerfile: str, log_error: str, analysis: Dict[str, Any], api_key: str = None) -> Dict[str, Any]:
    """Analyzes the build logs error and corrects the Dockerfile using Gemini API."""
    key = api_key or os.environ.get("GEMINI_API_KEY")
    
    if not key:
        logger.info("No Gemini API key available. Generating corrected mock Dockerfile.")
        return get_mock_dockerfile(analysis["project_type"], 2, "fail-and-fix")
        
    prompt = f"""
    You are DockerForge, an expert agentic AI developer. A previously generated Dockerfile failed to build. 
    Analyze the build error and correct the Dockerfile.
    
    Failed Dockerfile:
    {dockerfile}
    
    Docker Build Error Logs:
    {log_error}
    
    Project Context Details:
    {json.dumps(analysis['key_files'], indent=2)}
    
    Propose a fix. Generate a corrected Dockerfile and updated docker-compose.yml.
    
    Your response MUST be in raw JSON format matching this schema:
    {{
        "dockerfile": "corrected complete Dockerfile contents",
        "docker_compose": "corrected docker-compose.yml contents",
        "rationale": "reasoning explaining why it failed and how you corrected it",
        "project_type": "node|python|go|other",
        "port": 3000 (port integer)
    }}
    
    Do NOT wrap the output in markdown block symbols like ```json. Make sure the response is a pure JSON parseable string.
    """
    
    try:
        genai.configure(api_key=key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        data = json.loads(response.text)
        return data
    except Exception as e:
        logger.error(f"Gemini correction error: {str(e)}. Falling back to mock correction solver.")
        return get_mock_dockerfile(analysis["project_type"], 2, "fail-and-fix")
