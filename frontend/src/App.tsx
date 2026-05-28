import React, { useState, useEffect, useRef, useCallback } from 'react';
import { 
  Play, 
  Copy, 
  Download, 
  Check, 
  AlertCircle, 
  GitBranch, 
  Cpu, 
  RefreshCw, 
  Sliders, 
  Key,
  HelpCircle,
  Trash2,
  Clock,
  Box,
  Layers,
  Activity
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

const DOCKERFILE_KEYWORDS = ['FROM', 'RUN', 'COPY', 'ADD', 'WORKDIR', 'EXPOSE', 'CMD', 'ENTRYPOINT', 'ENV', 'ARG', 'LABEL', 'VOLUME', 'USER', 'HEALTHCHECK', 'SHELL', 'STOPSIGNAL', 'ONBUILD', 'MAINTAINER', 'AS'];

function highlightDockerfile(code: string) {
  return code.split('\n').map((line, idx) => {
    let content: React.JSX.Element;
    const trimmed = line.trim();
    
    if (trimmed.startsWith('#')) {
      content = <span className="syntax-comment">{line}</span>;
    } else {
      const parts: React.JSX.Element[] = [];
      let remaining = line;
      let matched = false;
      
      for (const kw of DOCKERFILE_KEYWORDS) {
        if (trimmed.startsWith(kw + ' ') || trimmed === kw) {
          const kwIndex = line.indexOf(kw);
          if (kwIndex >= 0) {
            parts.push(<span key="pre">{line.substring(0, kwIndex)}</span>);
            parts.push(<span key="kw" className="syntax-keyword">{kw}</span>);
            remaining = line.substring(kwIndex + kw.length);
            matched = true;
            break;
          }
        }
      }
      
      if (matched) {
        // Highlight strings in quotes and flags
        const tokens = remaining.split(/("[^"]*"|'[^']*'|--[a-zA-Z0-9-]+)/g);
        tokens.forEach((token, ti) => {
          if (token.startsWith('"') || token.startsWith("'")) {
            parts.push(<span key={`s${ti}`} className="syntax-string">{token}</span>);
          } else if (token.startsWith('--')) {
            parts.push(<span key={`f${ti}`} className="syntax-flag">{token}</span>);
          } else {
            parts.push(<span key={`t${ti}`}>{token}</span>);
          }
        });
        content = <>{parts}</>;
      } else {
        content = <span>{line}</span>;
      }
    }
    
    return (
      <div key={idx} className="code-line">
        <span className="line-number">{idx + 1}</span>
        <span className="line-content">{content}</span>
      </div>
    );
  });
}

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
  
  // Stats
  const [startTime, setStartTime] = useState<number | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [buildAttempts, setBuildAttempts] = useState(0);
  const [projectType, setProjectType] = useState<string>('-');

  const terminalEndRef = useRef<HTMLDivElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  // Auto scroll terminal to bottom
  useEffect(() => {
    if (terminalEndRef.current) {
      terminalEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs]);

  // Elapsed time ticker
  useEffect(() => {
    if (!isRunning || !startTime) return;
    const interval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startTime) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, [isRunning, startTime]);

  const addLog = useCallback((type: LogLine['type'], text: string) => {
    const time = new Date().toLocaleTimeString();
    setLogs(prev => [...prev, { time, type, text }]);
    
    // Track build attempts from log messages
    if (text.includes('Starting build verification (Attempt')) {
      const match = text.match(/Attempt (\d+)/);
      if (match) setBuildAttempts(parseInt(match[1]));
    }
    // Track project type
    if (text.includes('Detected project type:')) {
      const match = text.match(/type: (\w+)/);
      if (match) setProjectType(match[1]);
    }
  }, []);

  const updateStep = useCallback((id: string, status: AgentStep['status']) => {
    setSteps(prev => prev.map(step => {
      if (step.id === id) {
        return { ...step, status };
      }
      if (status === 'active' && prev.indexOf(step) < prev.findIndex(s => s.id === id)) {
        if (step.status !== 'success') {
          return { ...step, status: 'success' };
        }
      }
      return step;
    }));
  }, []);

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
    setBuildAttempts(0);
    setProjectType('-');
    setStartTime(Date.now());
    setElapsed(0);
    setLogs([
      { time: new Date().toLocaleTimeString(), type: 'info', text: `Initiating connection... Mode: ${executionMode.toUpperCase()}` },
      { time: new Date().toLocaleTimeString(), type: 'agent', text: `Targeting: ${repoUrl}` }
    ]);

    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    try {
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

    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      addLog('error', `Initialization Error: ${message}`);
      setRunStatus('failed');
      setIsRunning(false);
    }
  };

  const formatElapsed = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
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
          {isRunning && (
            <span style={{ color: 'var(--color-info)', fontFamily: 'var(--font-mono)', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
              <Clock size={14} /> {formatElapsed(elapsed)}
            </span>
          )}
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
                  onChange={(e) => setSimulationBehavior(e.target.value as 'fail-and-fix' | 'always-success' | 'permanent-fail')}
                  disabled={isRunning}
                >
                  <option value="fail-and-fix">Self-Correction Loop (Fail &amp; Fix)</option>
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

            <hr className="section-divider" />

            {/* Stats Summary */}
            <div className="form-group">
              <label className="form-label">Run Statistics</label>
              <div className="stats-grid">
                <div className="stat-card">
                  <span className="stat-label">Project Type</span>
                  <span className="stat-value info">{projectType}</span>
                </div>
                <div className="stat-card">
                  <span className="stat-label">Build Attempts</span>
                  <span className={`stat-value ${buildAttempts > 1 ? 'error' : buildAttempts === 1 ? 'info' : ''}`}>{buildAttempts || '-'}</span>
                </div>
                <div className="stat-card">
                  <span className="stat-label">Status</span>
                  <span className={`stat-value ${runStatus === 'success' ? 'success' : runStatus === 'failed' ? 'error' : 'info'}`}>{runStatus.toUpperCase()}</span>
                </div>
                <div className="stat-card">
                  <span className="stat-label">Duration</span>
                  <span className="stat-value">{elapsed > 0 ? formatElapsed(elapsed) : '-'}</span>
                </div>
              </div>
            </div>

            <hr className="section-divider" />

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
              <div className="terminal-chrome">
                <div className="terminal-dots">
                  <div className="terminal-dot red" />
                  <div className="terminal-dot yellow" />
                  <div className="terminal-dot green" />
                </div>
                <span className="terminal-title">dockerforge — agent logs</span>
                <button 
                  className="action-btn" 
                  title="Clear logs" 
                  onClick={() => setLogs([{ time: new Date().toLocaleTimeString(), type: 'info', text: 'Logs cleared.' }])}
                  style={{ marginLeft: 'auto' }}
                >
                  <Trash2 size={12} />
                </button>
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
                    <pre className="code-pre">{highlightDockerfile(dockerfile)}</pre>
                  ) : (
                    <div className="empty-state">
                      <Box size={40} />
                      <p>Dockerfile will appear here once forged by the Agent</p>
                    </div>
                  )
                ) : (
                  dockerCompose ? (
                    <pre className="code-pre"><code>{dockerCompose}</code></pre>
                  ) : (
                    <div className="empty-state">
                      <Layers size={40} />
                      <p>docker-compose.yml will appear here if generated</p>
                    </div>
                  )
                )}
              </div>
            </div>
          </div>
          <div className="footer">
            <Activity size={14} style={{ display: 'inline', verticalAlign: 'middle', marginRight: '0.35rem' }} />
            DockerForge — Built with FastAPI, React, and Google Gemini Agentic Reasoning Loop
          </div>
        </div>
      </main>
    </div>
  );
}
