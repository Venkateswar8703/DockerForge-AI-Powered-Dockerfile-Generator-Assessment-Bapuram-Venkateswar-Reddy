import os
import subprocess
import time
import socket
import urllib.request
from typing import Generator, Dict, Any, Tuple

def is_docker_installed() -> bool:
    """Checks if docker CLI is available in the system PATH."""
    try:
        subprocess.run(["docker", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def check_port_open(port: int, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    """Checks if a TCP port is open on the host."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError):
        return False

def ping_container(port: int, path: str = "/", timeout: float = 3.0) -> Tuple[bool, str]:
    """Attempts to make an HTTP GET request to the container port."""
    url = f"http://127.0.0.1:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            status = response.status
            return (200 <= status < 300, f"HTTP GET {url} returned {status}")
    except Exception as e:
        return (False, f"HTTP GET {url} failed: {str(e)}")

def run_real_docker_build(repo_path: str, dockerfile_content: str, tag: str) -> Generator[Dict[str, Any], None, Tuple[bool, str]]:
    """Runs a real docker build command and yields build output logs line-by-line."""
    dockerfile_path = os.path.join(repo_path, "Dockerfile")
    
    # Write the Dockerfile
    with open(dockerfile_path, "w", encoding="utf-8") as f:
        f.write(dockerfile_content)
        
    cmd = ["docker", "build", "-t", tag, "."]
    yield {"type": "log", "log": {"type": "info", "text": f"Running: {' '.join(cmd)}"}}
    
    try:
        # Use subprocess.Popen to stream logs in real-time
        process = subprocess.Popen(
            cmd,
            cwd=repo_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        full_log = []
        if process.stdout:
            for line in iter(process.stdout.readline, ""):
                stripped_line = line.rstrip()
                full_log.append(stripped_line)
                yield {"type": "log", "log": {"type": "stdout", "text": stripped_line}}
                
        process.wait()
        
        success = process.returncode == 0
        status_msg = "Docker build completed successfully." if success else "Docker build failed."
        yield {"type": "log", "log": {"type": "info" if success else "error", "text": status_msg}}
        
        return success, "\n".join(full_log)
        
    except Exception as e:
        err_msg = f"Failed to execute docker build: {str(e)}"
        yield {"type": "log", "log": {"type": "error", "text": err_msg}}
        return False, err_msg

def run_real_docker_container(tag: str, container_name: str, host_port: int, container_port: int) -> Generator[Dict[str, Any], None, bool]:
    """Runs the docker container, verifies it responds, and cleans up."""
    # Ensure no container with the same name is running
    subprocess.run(["docker", "rm", "-f", container_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    cmd = [
        "docker", "run", "-d",
        "-p", f"{host_port}:{container_port}",
        "--name", container_name,
        tag
    ]
    
    yield {"type": "log", "log": {"type": "info", "text": f"Running: {' '.join(cmd)}"}}
    
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        container_id = res.stdout.strip()[:12]
        yield {"type": "log", "log": {"type": "success", "text": f"Container started: ID {container_id}"}}
        
        # Stream logs for 5 seconds to show container startup output
        yield {"type": "log", "log": {"type": "info", "text": "Fetching container logs..."}}
        time.sleep(2.0) # Wait for start
        
        logs_res = subprocess.run(["docker", "logs", container_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for line in logs_res.stdout.splitlines():
            yield {"type": "log", "log": {"type": "stdout", "text": f"[Container] {line}"}}
        for line in logs_res.stderr.splitlines():
            yield {"type": "log", "log": {"type": "stdout", "text": f"[Container] {line}"}}
            
        # Verify port connection
        yield {"type": "log", "log": {"type": "info", "text": f"Testing connection on host port {host_port}..."}}
        
        # Simple TCP port check
        is_open = check_port_open(host_port)
        if not is_open:
            yield {"type": "log", "log": {"type": "error", "text": f"Port {host_port} is not accepting connections."}}
            # Clean up
            subprocess.run(["docker", "rm", "-f", container_name])
            return False
            
        # HTTP health check ping
        success, ping_msg = ping_container(host_port)
        if success:
            yield {"type": "log", "log": {"type": "success", "text": f"Health check passed! {ping_msg}"}}
        else:
            yield {"type": "log", "log": {"type": "warn", "text": f"TCP port is open but HTTP ping failed: {ping_msg}"}}
            yield {"type": "log", "log": {"type": "info", "text": "Considering container verified since port is listening."}}
            success = True
            
        # Clean up
        yield {"type": "log", "log": {"type": "info", "text": f"Stopping and removing container {container_name}..."}}
        subprocess.run(["docker", "rm", "-f", container_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return success
        
    except Exception as e:
        yield {"type": "log", "log": {"type": "error", "text": f"Container verification execution failed: {str(e)}"}}
        subprocess.run(["docker", "rm", "-f", container_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return False

def run_simulated_docker_build(project_type: str, behavior: str, attempt: int) -> Generator[Dict[str, Any], None, Tuple[bool, str]]:
    """Simulates a docker build logs flow with custom settings to test self-correction."""
    yield {"type": "log", "log": {"type": "info", "text": f"Running: docker build . -f Dockerfile (Attempt {attempt}/3 - Simulated)"}}
    time.sleep(1.0)
    
    # Standard steps depending on project type
    base_image = "node:20-alpine" if project_type == "node" else "python:3.11-slim" if project_type == "python" else "golang:1.21-alpine"
    
    steps = [
        f"Step 1/6 : FROM {base_image}",
        " ---> Resolving dependencies...",
        " ---> Copying cache build arguments...",
        f" ---> Using image cache for {base_image}",
        "Step 2/6 : WORKDIR /app",
        " ---> Running in container context...",
        "Step 3/6 : COPY package*.json ./" if project_type == "node" else "COPY requirements.txt ./" if project_type == "python" else "COPY go.mod go.sum ./ ",
    ]
    
    for step in steps:
        yield {"type": "log", "log": {"type": "stdout", "text": step}}
        time.sleep(0.4)
        
    # Attempt 1 failures
    if attempt == 1 and behavior == "fail-and-fix":
        if project_type == "node":
            yield {"type": "log", "log": {"type": "stdout", "text": "Step 4/6 : RUN npm ci"}}
            time.sleep(1.0)
            err_log = (
                "npm ERR! code ERESOLVE\n"
                "npm ERR! ERESOLVE unable to resolve dependency tree\n"
                "npm ERR! \n"
                "npm ERR! Found: react@19.0.0\n"
                "npm ERR!   react@\"^19.0.0\" from the root project\n"
                "npm ERR! \n"
                "npm ERR! Could not resolve dependency:\n"
                "npm ERR! peer react@\"^18.2.0\" from react-slick\n"
                "npm ERR! \n"
                "npm ERR! Fix the upstream dependency conflict, or retry\n"
                "npm ERR! this command with --legacy-peer-deps to accept an incorrect\n"
                "npm ERR! (and potentially broken) dependency resolution.\n"
                "npm ERR! \n"
                "npm ERR! A complete log of this run can be found in:\n"
                "npm ERR!     /root/.npm/_logs/2026-05-28T05_40_10Z-debug.log\n"
                "ERROR: Service 'web' failed to build: The command '/bin/sh -c npm ci' returned a non-zero code: 1"
            )
        elif project_type == "python":
            yield {"type": "log", "log": {"type": "stdout", "text": "Step 4/6 : RUN pip install -r requirements.txt"}}
            time.sleep(1.0)
            err_log = (
                "Collecting psycopg2==2.9.9 (from -r requirements.txt (line 4))\n"
                "  Downloading psycopg2-2.9.9.tar.gz (384 kB)\n"
                "  Installing build dependencies ... error\n"
                "  error: subprocess-exited-with-error\n"
                "  \n"
                "  Error: pg_config executable not found.\n"
                "  pg_config is required to build psycopg2 from source. Please add the directory\n"
                "  containing pg_config to the PATH or specify the address of pg_config with the\n"
                "  configure option.\n"
                "  \n"
                "  SQLAlchemy and PostgreSQL support requires libpq-dev package on Debian/Ubuntu.\n"
                "  ----------------------------------------\n"
                "  ERROR: Failed building wheel for psycopg2\n"
                "ERROR: Service 'api' failed to build: The command '/bin/sh -c pip install -r requirements.txt' returned a non-zero code: 1"
            )
        else: # Go
            yield {"type": "log", "log": {"type": "stdout", "text": "Step 4/6 : RUN go build -o main ."}}
            time.sleep(1.0)
            err_log = (
                "./main.go:12:2: undefined: mux.NewRouter\n"
                "note: github.com/gorilla/mux was not found in go.mod. Run 'go get' to add it.\n"
                "ERROR: Service 'server' failed to build: The command '/bin/sh -c go build -o main .' returned a non-zero code: 2"
            )
            
        for line in err_log.split("\n"):
            yield {"type": "log", "log": {"type": "error", "text": line}}
            time.sleep(0.1)
            
        yield {"type": "log", "log": {"type": "error", "text": "Docker build failed."}}
        return False, err_log
        
    # Permanent failure on all attempts
    elif behavior == "permanent-fail":
        yield {"type": "log", "log": {"type": "stdout", "text": "Step 4/6 : RUN building application..."}}
        time.sleep(1.0)
        err_log = (
            "Configuration Error: Invalid port mapping specified.\n"
            "The application port is locked by another internal system process.\n"
            "Dockerfile syntax error: COPY requires at least two arguments.\n"
            "ERROR: Build exited with status 1."
        )
        for line in err_log.split("\n"):
            yield {"type": "log", "log": {"type": "error", "text": line}}
            time.sleep(0.1)
            
        yield {"type": "log", "log": {"type": "error", "text": "Docker build failed."}}
        return False, err_log
        
    # Success (Always Success OR Attempt 2/3 of Fail-and-Fix)
    else:
        # Run package installation successfully
        if project_type == "node":
            yield {"type": "log", "log": {"type": "stdout", "text": "Step 4/6 : RUN npm install --legacy-peer-deps"}}
            time.sleep(1.0)
            yield {"type": "log", "log": {"type": "stdout", "text": " ---> Added 246 packages in 4.21s"}}
        elif project_type == "python":
            yield {"type": "log", "log": {"type": "stdout", "text": "Step 4/6 : RUN apt-get update && apt-get install -y libpq-dev gcc && pip install -r requirements.txt"}}
            time.sleep(1.2)
            yield {"type": "log", "log": {"type": "stdout", "text": " ---> Installing native libraries... Done."}}
            yield {"type": "log", "log": {"type": "stdout", "text": " ---> Installing python packages... Done."}}
        else: # Go
            yield {"type": "log", "log": {"type": "stdout", "text": "Step 4/6 : RUN go mod download && go build -o main ."}}
            time.sleep(1.0)
            yield {"type": "log", "log": {"type": "stdout", "text": " ---> Compiled go binary successfully."}}
            
        # Final steps
        next_steps = [
            "Step 5/6 : COPY . .",
            " ---> Copying codebase...",
            "Step 6/6 : EXPOSE 3000" if project_type == "node" else "Step 6/6 : EXPOSE 8000" if project_type == "python" else "Step 6/6 : EXPOSE 8080",
            " ---> Running container configurations...",
            " ---> Exporting layers...",
            " ---> Successfully built image: dockerforge-simulated-tag"
        ]
        for step in next_steps:
            yield {"type": "log", "log": {"type": "stdout", "text": step}}
            time.sleep(0.3)
            
        yield {"type": "log", "log": {"type": "success", "text": "Docker build completed successfully."}}
        return True, "Build succeeded"

def run_simulated_docker_container(project_type: str) -> Generator[Dict[str, Any], None, bool]:
    """Simulates starting and pinging the built docker container."""
    port = 3000 if project_type == "node" else 8000 if project_type == "python" else 8080
    yield {"type": "log", "log": {"type": "info", "text": f"Running: docker run -d -p {port}:{port} --name dockerforge-container dockerforge-simulated-tag"}}
    time.sleep(1.0)
    
    yield {"type": "log", "log": {"type": "success", "text": "Container started: ID 9e4f5a1b3c7d"}}
    time.sleep(0.8)
    
    yield {"type": "log", "log": {"type": "info", "text": "Fetching container logs..."}}
    time.sleep(1.0)
    
    # Simulate bootup outputs
    if project_type == "node":
        boot_logs = [
            "[Container] > express-starter@1.0.0 start",
            "[Container] > node server.js",
            "[Container] ",
            f"[Container] Express Server started on PORT {port}",
            "[Container] Database connection pool initialized.",
            "[Container] Ready to serve traffic..."
        ]
    elif project_type == "python":
        boot_logs = [
            "[Container] INFO:     Started server process [1]",
            "[Container] INFO:     Waiting for application startup.",
            "[Container] INFO:     Application startup complete.",
            f"[Container] INFO:     Uvicorn running on http://0.0.0.0:{port} (Press CTRL+C to quit)"
        ]
    else: # Go
        boot_logs = [
            f"[Container] 2026/05/28 11:10:00 Starting server on port {port}",
            "[Container] 2026/05/28 11:10:01 Registered endpoints [/api/health /api/v1]",
            "[Container] 2026/05/28 11:10:01 Listening for incoming connections..."
        ]
        
    for line in boot_logs:
        yield {"type": "log", "log": {"type": "stdout", "text": line}}
        time.sleep(0.2)
        
    yield {"type": "log", "log": {"type": "info", "text": f"Testing connection on host port {port}..."}}
    time.sleep(1.0)
    
    yield {"type": "log", "log": {"type": "success", "text": f"Health check passed! HTTP GET http://127.0.0.1:{port}/ returned 200 OK"}}
    time.sleep(0.5)
    
    yield {"type": "log", "log": {"type": "info", "text": "Stopping and removing container dockerforge-container..."}}
    time.sleep(0.5)
    return True
