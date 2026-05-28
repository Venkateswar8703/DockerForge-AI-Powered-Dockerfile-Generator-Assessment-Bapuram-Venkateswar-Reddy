import React, { useState, useEffect, useRef } from 'react';
import { 
  Play, 
  Terminal, 
  Code, 
  Copy, 
  Download, 
  Check, 
  AlertCircle, 
  GitBranch, 
  Cpu, 
  RefreshCw, 
  Sliders, 
  Key,
  HelpCircle
} from 'lucide-react';

interface LogLine {
  time: string;
  type: 'info' | 'success' | 'error' | 'warn' | 'stdout' | 'agent';
  text: string;
}

interface AgentStep {
  id: string;
  title: string;
  desc: string;
  status: 'pending' | 'active' | 'success' | 'failed';
}

const DEFAULT_STEPS: AgentStep[] = [
  { id: 'clone', title: 'Cloning Repository', desc: 'Cloning public repository from GitHub', status: 'pending' },
  { id: 'analyze', title: 'Analyzing Codebase', desc: 'Scanning directories and package files', status: 'pending' },
  { id: 'generate', title: 'Generating Dockerfile', desc: 'Reasoning about configuration and structure', status: 'pending' },
  { id: 'build', title: 'Docker Build Check', desc: 'Building image and diagnosing compilation output', status: 'pending' },
  { id: 'run', title: 'Container Verification', desc: 'Running and pinging health check endpoints', status: 'pending' },
];

export default function App() {
  const [repoUrl, setRepoUrl] = useState('https://github.com/heroku/node-js-getting-started');
  const [apiKey, setApiKey] = useState('');
  const [executionMode, setExecutionMode] = useState<'real' | 'simulated'>('simulated');
  const [simulationBehavior, setSimulationBehavior] = useState<'fail-and-fix' | 'always-success' | 'permanent-fail'>('fail-and-fix');
  
  const [logs, setLogs] = useState<LogLine[]>([
    { time: new Date().toLocaleTimeString(), type: 'info', text: 'DockerForge System initialized. Ready to forge Dockerfiles.' }
  ]);
  const [steps, setSteps] = useState<AgentStep[]>(DEFAULT_STEPS);
  const [isRunning, setIsRunning] = useState(false);
  const [runStatus, setRunStatus] = useState<'idle' | 'running' | 'success' | 'failed'>('idle');

  const [dockerfile, setDockerfile] = useState<string>('');
  const [dockerCompose, setDockerCompose] = useState<string>('');
  const [activeTab, setActiveTab] = useState<'dockerfile' | 'docker-compose'>('dockerfile');
  const [copied, setCopied] = useState(false);

  const terminalEndRef = useRef<HTMLDivElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  // Auto scroll terminal to bottom
  useEffect(() => {
    if (terminalEndRef.current) {
      terminalEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs]);

  const addLog = (type: LogLine['type'], text: string) => {
    const time = new Date().toLocaleTimeString();
    setLogs(prev => [...prev, { time, type, text }]);
  };

  const updateStep = (id: string, status: AgentStep['status']) => {
    setSteps(prev => prev.map(step => {
      if (step.id === id) {
        return { ...step, status };
      }
      // If we start a step, make sure preceding steps are marked success if they are pending/active
      if (status === 'active' && prev.indexOf(step) < prev.findIndex(s => s.id === id)) {
        if (step.status !== 'success') {
          return { ...step, status: 'success' };
        }
      }
      return step;
    }));
  };

  const handleCopy = () => {
    const content = activeTab === 'dockerfile' ? dockerfile : dockerCompose;
    if (!content) return;
    navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    const content = activeTab === 'dockerfile' ? dockerfile : dockerCompose;
    if (!content) return;
    const filename = activeTab === 'dockerfile' ? 'Dockerfile' : 'docker-compose.yml';
    const blob = new Blob([content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleStart = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!repoUrl.trim()) return;

    // Reset UI
    setIsRunning(true);
    setRunStatus('running');
    setDockerfile('');
    setDockerCompose('');
    setSteps(DEFAULT_STEPS.map(s => ({ ...s, status: 'pending' })));
    setLogs([
      { time: new Date().toLocaleTimeString(), type: 'info', text: `Initiating connection... Mode: ${executionMode.toUpperCase()}` },
      { time: new Date().toLocaleTimeString(), type: 'agent', text: `Targeting: ${repoUrl}` }
    ]);

    // Close any previous stream
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    try {
      // Step 1: Request backend to start process and return task ID
      const response = await fetch('/api/forge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          repo_url: repoUrl,
          api_key: apiKey,
          execution_mode: executionMode,
          simulation_behavior: simulationBehavior
        })
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to start DockerForge process.');
      }

      const { task_id } = await response.json();
      addLog('info', `Backend session task created: ${task_id}`);

      // Step 2: Establish SSE connection to stream logs and outputs
      const eventSource = new EventSource(`/api/stream/${task_id}`);
      eventSourceRef.current = eventSource;

      eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);
        
        if (data.type === 'log') {
          addLog(data.log.type, data.log.text);
        } 
        else if (data.type === 'step') {
          updateStep(data.step.id, data.step.status);
        }
        else if (data.type === 'result') {
          if (data.status === 'success') {
            setDockerfile(data.dockerfile || '');
            setDockerCompose(data.docker_compose || '');
            setRunStatus('success');
            // Mark all steps completed successfully
            setSteps(prev => prev.map(s => ({ ...s, status: 'success' })));
          } else {
            setRunStatus('failed');
          }
          setIsRunning(false);
          eventSource.close();
        }
      };

      eventSource.onerror = () => {
        addLog('error', 'Connection lost or server closed stream.');
        setRunStatus('failed');
        setIsRunning(false);
        eventSource.close();
      };

    } catch (err: any) {
      addLog('error', `Initialization Error: ${err.message}`);
      setRunStatus('failed');
      setIsRunning(false);
    }
  };

  return (
    <div className="app-container">
      <header>
        <div className="logo">
          <Cpu className="logo-icon" size={24} />
          Docker<span>Forge</span>
        </div>
        <div className="header-meta">
          <div className="status-badge-container">
            {runStatus === 'idle' && <span className="status-badge idle">System Idle</span>}
            {runStatus === 'running' && <span className="status-badge running">Forging Image...</span>}
            {runStatus === 'success' && <span className="status-badge success">Success</span>}
            {runStatus === 'failed' && <span className="status-badge failed">Build Failed</span>}
          </div>
          <span style={{ color: 'var(--text-dimmed)' }}>|</span>
          <span style={{ color: 'var(--text-muted)' }}>Gemini Agentic Builder</span>
        </div>
      </header>

      <main className="main-content">
        {/* Left Control Panel */}
        <div className="glass-panel">
          <div className="panel-header">
            <span className="panel-title">
              <Sliders size={18} /> Configuration
            </span>
          </div>
          <form className="panel-body" onSubmit={handleStart}>
            <div className="form-group">
              <label className="form-label">GitHub Repository URL</label>
              <div className="input-wrapper">
                <GitBranch className="input-icon" size={16} />
                <input
                  type="url"
                  className="form-input"
                  placeholder="https://github.com/user/repo"
                  value={repoUrl}
                  onChange={(e) => setRepoUrl(e.target.value)}
                  disabled={isRunning}
                  required
                />
              </div>
            </div>

            <div className="form-group">
              <label className="form-label">Gemini API Key (Optional)</label>
              <div className="input-wrapper">
                <Key className="input-icon" size={16} />
                <input
                  type="password"
                  className="form-input"
                  placeholder="Leave empty to use server default"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  disabled={isRunning}
                />
              </div>
            </div>

            <div className="form-group">
              <label className="form-label">Execution Mode</label>
              <div className="toggle-group">
                <button
                  type="button"
                  className={`toggle-btn ${executionMode === 'simulated' ? 'active' : ''}`}
                  onClick={() => setExecutionMode('simulated')}
                  disabled={isRunning}
                >
                  Simulation
                </button>
                <button
                  type="button"
                  className={`toggle-btn ${executionMode === 'real' ? 'active' : ''}`}
                  onClick={() => setExecutionMode('real')}
                  disabled={isRunning}
                >
                  Real Docker
                </button>
              </div>
            </div>

            {executionMode === 'simulated' && (
              <div className="form-group">
                <label className="form-label">Simulation Flow</label>
                <select
                  className="form-select"
                  value={simulationBehavior}
                  onChange={(e) => setSimulationBehavior(e.target.value as any)}
                  disabled={isRunning}
                >
                  <option value="fail-and-fix">Self-Correction Loop (Fail & Fix)</option>
                  <option value="always-success">Build Directly (Success)</option>
                  <option value="permanent-fail">Critical Issues (Max Fails)</option>
                </select>
              </div>
            )}

            <button type="submit" className="btn-primary" disabled={isRunning}>
              {isRunning ? (
                <>
                  <RefreshCw className="pulse-icon" size={16} /> Forging...
                </>
              ) : (
                <>
                  <Play size={16} /> Start Agent Loop
                </>
              )}
            </button>

            <hr style={{ borderColor: 'var(--border-color)', margin: '0.5rem 0' }} />

            {/* Agent Steps Timeline */}
            <div className="form-group">
              <label className="form-label">Agent Process Timeline</label>
              <div className="agent-step-list">
                {steps.map((step) => (
                  <div 
                    key={step.id} 
                    className={`step-card ${step.status === 'active' ? 'active' : ''} ${step.status === 'success' ? 'success' : ''}`}
                  >
                    <div className="step-icon">
                      {step.status === 'pending' && <HelpCircle size={16} style={{ color: 'var(--text-dimmed)' }} />}
                      {step.status === 'active' && <RefreshCw size={16} className="pulse-icon" style={{ color: 'var(--accent-primary)' }} />}
                      {step.status === 'success' && <Check size={16} style={{ color: 'var(--color-success)' }} />}
                      {step.status === 'failed' && <AlertCircle size={16} style={{ color: 'var(--color-error)' }} />}
                    </div>
                    <div className="step-details">
                      <span className="step-title">{step.title}</span>
                      <span className="step-desc">{step.desc}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </form>
        </div>

        {/* Right Output Panels */}
        <div className="workspace-grid">
          <div className="output-panels">
            {/* Terminal Live logs */}
            <div className="glass-panel">
              <div className="panel-header">
                <span className="panel-title">
                  <Terminal size={18} /> Agent Thoughts & Build Logs
                </span>
              </div>
              <div className="terminal-wrapper">
                {logs.map((log, idx) => (
                  <div key={idx} className={`terminal-line ${log.type}`}>
                    <span className="terminal-time">[{log.time}]</span>
                    <span>
                      {log.type === 'agent' && <strong style={{ color: '#c084fc' }}>[Agent] </strong>}
                      {log.text}
                    </span>
                  </div>
                ))}
                {isRunning && (
                  <div className="terminal-line">
                    <span className="terminal-time">[{new Date().toLocaleTimeString()}]</span>
                    <span className="terminal-cursor"></span>
                  </div>
                )}
                <div ref={terminalEndRef} />
              </div>
            </div>

            {/* Generated Code Viewer */}
            <div className="glass-panel code-viewer-panel">
              <div className="tab-header">
                <button
                  className={`tab-btn ${activeTab === 'dockerfile' ? 'active' : ''}`}
                  onClick={() => setActiveTab('dockerfile')}
                >
                  Dockerfile
                </button>
                <button
                  className={`tab-btn ${activeTab === 'docker-compose' ? 'active' : ''}`}
                  onClick={() => setActiveTab('docker-compose')}
                >
                  docker-compose.yml
                </button>

                {(dockerfile || dockerCompose) && (
                  <div className="tab-actions">
                    <button className="action-btn" title="Copy code" onClick={handleCopy}>
                      {copied ? <Check size={14} style={{ color: 'var(--color-success)' }} /> : <Copy size={14} />}
                    </button>
                    <button className="action-btn" title="Download file" onClick={handleDownload}>
                      <Download size={14} />
                    </button>
                  </div>
                )}
              </div>
              <div className="code-wrapper">
                {activeTab === 'dockerfile' ? (
                  dockerfile ? (
                    <pre className="code-pre"><code>{dockerfile}</code></pre>
                  ) : (
                    <div className="empty-state">
                      <Code size={40} />
                      <p>Dockerfile will appear here once forged by the Agent</p>
                    </div>
                  )
                ) : (
                  dockerCompose ? (
                    <pre className="code-pre"><code>{dockerCompose}</code></pre>
                  ) : (
                    <div className="empty-state">
                      <Code size={40} />
                      <p>docker-compose.yml will appear here if requested/generated</p>
                    </div>
                  )
                )}
              </div>
            </div>
          </div>
          <div className="footer">
            DockerForge — Built with FastAPI, React, and Google Gemini Agentic Reasoning Loop
          </div>
        </div>
      </main>
    </div>
  );
}
