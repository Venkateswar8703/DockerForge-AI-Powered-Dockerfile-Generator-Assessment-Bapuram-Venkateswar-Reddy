import os
import uuid
import json
import asyncio
import threading
import logging
from typing import Dict
from fastapi import FastAPI, BackgroundTasks, HTTPException, Body
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent import clone_repo, scan_codebase, generate_dockerfile, correct_dockerfile
from docker_executor import (
    is_docker_installed,
    run_real_docker_build,
    run_real_docker_container,
    run_simulated_docker_build,
    run_simulated_docker_container
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="DockerForge API", version="1.0.0")

# CORS middleware for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global dictionary to track SSE message queues for tasks
task_queues: Dict[str, asyncio.Queue] = {}

class ForgeRequest(BaseModel):
    repo_url: str = Field(..., description="Public GitHub repository URL")
    api_key: str = Field("", description="Optional Gemini API key")
    execution_mode: str = Field("simulated", description="real or simulated")
    simulation_behavior: str = Field("fail-and-fix", description="fail-and-fix, always-success, or permanent-fail")

def run_agent_loop(
    task_id: str,
    repo_url: str,
    api_key: str,
    execution_mode: str,
    simulation_behavior: str,
    loop: asyncio.AbstractEventLoop
):
    """Executes the agent cloner, analyzer, generator, and build verification loop in a background thread."""
    queue = task_queues[task_id]
    
    def send_log(log_type: str, text: str):
        # Push message to queue thread-safely
        loop.call_soon_threadsafe(
            queue.put_nowait,
            {"type": "log", "log": {"time": "", "type": log_type, "text": text}}
        )

    def send_step(step_id: str, status: str):
        loop.call_soon_threadsafe(
            queue.put_nowait,
            {"type": "step", "step": {"id": step_id, "status": status}}
        )

    def send_result(status: str, dockerfile: str = "", docker_compose: str = ""):
        loop.call_soon_threadsafe(
            queue.put_nowait,
            {
                "type": "result",
                "status": status,
                "dockerfile": dockerfile,
                "docker_compose": docker_compose
            }
        )

    try:
        # Step 1: Clone repository
        send_step("clone", "active")
        send_log("agent", f"Starting git clone for {repo_url}...")
        
        success, repo_path = clone_repo(repo_url, task_id)
        if not success:
            send_log("error", f"Clone failed: {repo_path}")
            send_step("clone", "failed")
            send_result("failed")
            return
            
        send_log("success", f"Repository cloned successfully to {repo_path}")
        send_step("clone", "success")
        
        # Step 2: Analyze codebase
        send_step("analyze", "active")
        send_log("agent", "Analyzing codebase structure and configuration files...")
        analysis = scan_codebase(repo_path)
        
        proj_type = analysis["project_type"]
        files_found = len(analysis["file_structure"])
        send_log("info", f"Detected project type: {proj_type.upper()}")
        send_log("info", f"Scanned {files_found} files. Found configurations: {list(analysis['key_files'].keys())}")
        send_step("analyze", "success")
        
        # Step 3: Generate Dockerfile (Attempt 1)
        send_step("generate", "active")
        send_log("agent", "Generating Dockerfile and docker-compose.yml configurations...")
        
        agent_output = generate_dockerfile(analysis, api_key)
        dockerfile = agent_output.get("dockerfile", "")
        docker_compose = agent_output.get("docker_compose", "")
        rationale = agent_output.get("rationale", "")
        detected_port = agent_output.get("port", 8080)
        
        send_log("agent", f"Architecture Rationale: {rationale}")
        send_step("generate", "success")
        
        # Step 4-5: Build and correction loop
        send_step("build", "active")
        
        max_attempts = 3
        attempt = 1
        build_success = False
        last_error_log = ""
        
        has_docker = is_docker_installed()
        use_real = (execution_mode == "real") and has_docker
        
        if execution_mode == "real" and not has_docker:
            send_log("warn", "Real Docker mode requested but Docker is not installed or running. Falling back to Simulation Mode.")
            
        while attempt <= max_attempts:
            send_log("agent", f"Starting build verification (Attempt {attempt}/{max_attempts})...")
            
            if use_real:
                # Real docker build
                tag = f"dockerforge-temp-{task_id}"
                build_gen = run_real_docker_build(repo_path, dockerfile, tag)
                
                # Consume generator logs and forward to frontend queue
                try:
                    while True:
                        log_item = next(build_gen)
                        loop.call_soon_threadsafe(queue.put_nowait, log_item)
                except StopIteration as e:
                    build_success, last_error_log = e.value
            else:
                # Simulated docker build
                build_gen = run_simulated_docker_build(proj_type, simulation_behavior, attempt)
                try:
                    while True:
                        log_item = next(build_gen)
                        loop.call_soon_threadsafe(queue.put_nowait, log_item)
                except StopIteration as e:
                    build_success, last_error_log = e.value
                    
            if build_success:
                send_log("success", f"Build succeeded on Attempt {attempt}!")
                send_step("build", "success")
                break
            else:
                send_log("error", f"Build failed on Attempt {attempt}. Error logged.")
                if attempt >= max_attempts:
                    send_log("error", "Reached maximum build attempts (3). Agent stopping.")
                    send_step("build", "failed")
                    send_result("failed")
                    break
                    
                # Self-correction reasoning
                send_log("agent", f"Analyzing logs and correcting Dockerfile (Attempt {attempt} -> {attempt+1})...")
                correction = correct_dockerfile(dockerfile, last_error_log, analysis, api_key)
                
                dockerfile = correction.get("dockerfile", dockerfile)
                docker_compose = correction.get("docker_compose", docker_compose)
                correction_rationale = correction.get("rationale", "")
                
                send_log("agent", f"Correction Plan: {correction_rationale}")
                attempt += 1
                
        # Step 6: Verify container (Only if build was successful)
        if build_success:
            send_step("run", "active")
            send_log("agent", "Launching container to verify runtime startup...")
            
            run_success = False
            if use_real:
                container_name = f"dockerforge-run-{task_id}"
                host_port = 49152 # Choose high port range
                run_gen = run_real_docker_container(f"dockerforge-temp-{task_id}", container_name, host_port, detected_port)
                try:
                    while True:
                        log_item = next(run_gen)
                        loop.call_soon_threadsafe(queue.put_nowait, log_item)
                except StopIteration as e:
                    run_success = e.value
                    
                # Clean up built image
                subprocess.run(["docker", "rmi", f"dockerforge-temp-{task_id}"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            else:
                run_gen = run_simulated_docker_container(proj_type)
                try:
                    while True:
                        log_item = next(run_gen)
                        loop.call_soon_threadsafe(queue.put_nowait, log_item)
                except StopIteration as e:
                    run_success = e.value
                    
            if run_success:
                send_log("success", "Container startup and health verification succeeded!")
                send_step("run", "success")
                send_result("success", dockerfile, docker_compose)
            else:
                send_log("error", "Container verification failed.")
                send_step("run", "failed")
                send_result("failed")
                
        # Clean up temp repository files
        if os.path.exists(repo_path):
            shutil.rmtree(repo_path, ignore_errors=True)
            
    except Exception as e:
        logger.exception("Error in agent loop background thread:")
        send_log("error", f"Internal Agent Error: {str(e)}")
        send_result("failed")

@app.post("/api/forge")
async def forge_dockerfile(request: ForgeRequest, background_tasks: BackgroundTasks):
    """Launches the Dockerforge agentic run."""
    task_id = str(uuid.uuid4())
    task_queues[task_id] = asyncio.Queue()
    
    # Get current event loop
    loop = asyncio.get_running_loop()
    
    # Run in a background thread so the HTTP response is immediate
    thread = threading.Thread(
        target=run_agent_loop,
        args=(task_id, request.repo_url, request.api_key, request.execution_mode, request.simulation_behavior, loop)
    )
    thread.daemon = True
    thread.start()
    
    return {"task_id": task_id}

@app.get("/api/stream/{task_id}")
async def stream_task_logs(task_id: str):
    """Streams task logs and progress events as Server-Sent Events (SSE)."""
    if task_id not in task_queues:
        raise HTTPException(status_code=404, detail="Task ID not found")
        
    queue = task_queues[task_id]
    
    async def sse_generator():
        try:
            while True:
                # Wait for next item in queue
                item = await queue.get()
                yield f"data: {json.dumps(item)}\n\n"
                queue.task_done()
                
                # If this is the final result, clean up the queue
                if item["type"] == "result":
                    break
        except asyncio.CancelledError:
            logger.info(f"Client disconnected from SSE stream for task {task_id}")
        finally:
            # Clean up queue when client disconnects or completed
            if task_id in task_queues:
                del task_queues[task_id]

    return StreamingResponse(sse_generator(), media_type="text/event-stream")

# Mount React static files (only if frontend/dist folder exists)
frontend_dist = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"))
if os.path.exists(frontend_dist):
    logger.info(f"Mounting frontend dist directory from {frontend_dist}")
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
else:
    logger.warning(f"Frontend dist directory not found at {frontend_dist}. API runs in backend-only mode.")
    
    @app.get("/")
    def read_root():
        return {"status": "DockerForge API Running. Serve frontend separately."}
