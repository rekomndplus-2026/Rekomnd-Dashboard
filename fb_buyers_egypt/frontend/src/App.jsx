import React, { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios';
import {
  Rocket, RefreshCw, Trash2, CheckCircle, XCircle,
  Settings, LayoutDashboard, ShieldCheck, ShieldAlert, ShieldOff,
  AlertCircle, Clock, Loader2, Download, LogIn, AlertTriangle, Globe,
} from 'lucide-react';
import './index.css';

const API_BASE = import.meta.env.DEV ? 'http://localhost:8000/api' : '/api';

// ── Toast Notification System ─────────────────────────────────────────────
function Toast({ toasts, removeToast }) {
  return (
    <div className="toast-container">
      {toasts.map(t => (
        <div key={t.id} className={`toast toast-${t.type}`}>
          <span className="toast-icon">
            {t.type === 'success' && <CheckCircle size={16} />}
            {t.type === 'error'   && <XCircle size={16} />}
            {t.type === 'info'    && <AlertCircle size={16} />}
          </span>
          <span>{t.message}</span>
          <button className="toast-close" onClick={() => removeToast(t.id)}>✕</button>
        </div>
      ))}
    </div>
  );
}

// ── Session Status Card ────────────────────────────────────────────────────
function SessionCard({ sessionInfo, isRefreshing, isLoggingIn, onRefresh, onLogin }) {
  const status = sessionInfo?.status;

  let icon, label, cardClass, showLoginBtn = false;

  if (isLoggingIn) {
    icon = <Loader2 size={18} className="spin" />;
    label = 'Chrome is open — log in to Facebook…';
    cardClass = 'session-card session-refreshing';
  } else if (isRefreshing) {
    icon = <Loader2 size={18} className="spin" />;
    label = 'Refreshing session…';
    cardClass = 'session-card session-refreshing';
  } else if (status === 'ok') {
    icon = <ShieldCheck size={18} />;
    label = 'Session Active';
    cardClass = 'session-card session-ok';
  } else if (status === 'stale') {
    icon = <ShieldAlert size={18} />;
    label = 'Session Getting Stale';
    cardClass = 'session-card session-stale';
  } else if (status === 'expired' || status === 'missing') {
    icon = <ShieldOff size={18} />;
    label = status === 'expired' ? 'Session Expired' : 'No Session Found';
    cardClass = `session-card session-${status}`;
    showLoginBtn = true;
  } else if (status === 'warning') {
    icon = <AlertTriangle size={18} />;
    label = 'Session Warning';
    cardClass = 'session-card session-warning';
    showLoginBtn = true;
  } else {
    icon = <ShieldOff size={18} />;
    label = 'Checking…';
    cardClass = 'session-card session-refreshing';
  }

  return (
    <div className={cardClass}>
      <div className="session-header">
        {icon}
        <span className="session-label">{label}</span>
        {sessionInfo?.age && !isLoggingIn && (
          <span style={{ fontSize: '0.72rem', opacity: 0.7 }}>
            {sessionInfo.age} old
          </span>
        )}
      </div>

      {isLoggingIn ? (
        <div className="session-meta" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: '0.5rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <Globe size={12} />
            <span>Waiting for you to log in to Facebook in Chrome…</span>
          </div>
          <button 
            onClick={async () => {
              try {
                await axios.post('http://localhost:8000/api/actions/login/finish');
              } catch (e) {
                console.error(e);
              }
            }}
            style={{
              background: 'var(--accent-gold)', color: '#000', border: 'none', 
              padding: '0.3rem 0.6rem', borderRadius: '4px', fontSize: '0.8rem', 
              fontWeight: 600, cursor: 'pointer', width: '100%'
            }}
          >
            I'm Finished Logging In ✅
          </button>
        </div>
      ) : (
        <>
          {sessionInfo?.message && (
            <div className="session-meta">
              <AlertCircle size={12} />
              <span>{sessionInfo.message}</span>
            </div>
          )}
          {sessionInfo?.saved_at && (
            <div className="session-meta">
              <Clock size={12} />
              <span>Saved: {new Date(sessionInfo.saved_at).toLocaleString()}</span>
            </div>
          )}
        </>
      )}

      {/* Login button — shown when session is missing/expired */}
      {showLoginBtn && !isLoggingIn && (
        <button
          className="btn-refresh session-login-cta"
          onClick={onLogin}
          disabled={isRefreshing || isLoggingIn}
        >
          <LogIn size={14} /> Login to Facebook
        </button>
      )}

      {/* Refresh button */}
      {!isLoggingIn && (
        <button
          className="btn-refresh"
          onClick={onRefresh}
          disabled={isRefreshing || isLoggingIn}
        >
          <RefreshCw size={13} className={isRefreshing ? 'spin' : ''} />
          {isRefreshing ? 'Refreshing…' : 'Refresh Session'}
        </button>
      )}
    </div>
  );
}

// ── Grade Badge ────────────────────────────────────────────────────────────
function GradeBadge({ grade }) {
  if (!grade) return <span style={{ color: 'var(--text-dim)' }}>—</span>;
  const colors = {
    '🔥 HOT':   { bg: 'rgba(231,76,60,0.15)',  color: '#ff6b6b' },
    '🟢 WARM':  { bg: 'rgba(46,204,113,0.12)', color: '#2ecc71' },
    '🟡 COOL':  { bg: 'rgba(241,196,15,0.12)', color: '#f1c40f' },
    '⚪ COLD':  { bg: 'rgba(255,255,255,0.06)', color: '#7a8aaa' },
  };
  const c = colors[grade] || colors['⚪ COLD'];
  return (
    <span className="grade-badge" style={{ background: c.bg, color: c.color }}>
      {grade}
    </span>
  );
}

// ── Main App ───────────────────────────────────────────────────────────────
function App() {
  const [activeTab, setActiveTab] = useState('dashboard');

  // Data
  const [stats, setStats] = useState({});
  const [leads, setLeads] = useState([]);
  const [sessionInfo, setSessionInfo] = useState(null);
  const [groups, setGroups] = useState([]);
  const [logs, setLogs] = useState([]);
  const [isRunning, setIsRunning] = useState(false);

  // UI
  const [loading, setLoading] = useState(true);
  const [minScore, setMinScore] = useState(0);
  const [postUrl, setPostUrl] = useState('');
  const [newGroup, setNewGroup] = useState({ url: '', name: '', region: 'general', enabled: true });
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isLoggingIn, setIsLoggingIn] = useState(false);

  // Toast
  const [toasts, setToasts] = useState([]);
  const toastId = useRef(0);

  const addToast = useCallback((message, type = 'info') => {
    const id = ++toastId.current;
    setToasts(prev => [...prev, { id, message, type }]);
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 5000);
  }, []);

  const removeToast = useCallback((id) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  // Fetch
  const fetchDashboardData = async () => {
    try {
      const [statsRes, leadsRes, sessionRes, statusRes] = await Promise.all([
        axios.get(`${API_BASE}/stats`),
        axios.get(`${API_BASE}/leads?limit=100&min_score=${minScore}`),
        axios.get(`${API_BASE}/session`),
        axios.get(`${API_BASE}/status`),
      ]);
      setStats(statsRes.data);
      setLeads(leadsRes.data);
      setSessionInfo(sessionRes.data);
      setIsRunning(statusRes.data.is_running);
    } catch (err) {
      console.error('Dashboard fetch error:', err);
    }
  };

  const fetchGroups = async () => {
    try {
      const res = await axios.get(`${API_BASE}/groups`);
      setGroups(res.data);
    } catch (err) { console.error(err); }
  };

  const fetchLogs = async () => {
    try {
      const [logRes, statusRes] = await Promise.all([
        axios.get(`${API_BASE}/logs`),
        axios.get(`${API_BASE}/status`),
      ]);
      setLogs(logRes.data.logs);
      setIsRunning(statusRes.data.is_running);
    } catch (err) { console.error(err); }
  };

  useEffect(() => {
    const loadAll = async () => {
      setLoading(true);
      await Promise.all([fetchDashboardData(), fetchGroups(), fetchLogs()]);
      setLoading(false);
    };
    loadAll();
    const interval = setInterval(() => { fetchLogs(); fetchDashboardData(); }, 5000);
    return () => clearInterval(interval);
  }, [minScore]);

  // ── Progress ─────────────────────────────────────────────────────────────
  let progress = 0, statusMsg = 'Engine is offline. Ready to start.';
  if (isRunning && logs.length > 0) {
    let cG = 0, tG = 1, cS = 0, tS = 40;
    for (const line of logs) {
      const gM = line.match(/Group (\d+)\/(\d+)/);
      if (gM) { cG = parseInt(gM[1]); tG = parseInt(gM[2]); }
      const sM = line.match(/Scroll (\d+)\/(\d+)/);
      if (sM) { cS = parseInt(sM[1]); tS = parseInt(sM[2]); }
      if (line.includes('Database ready'))       statusMsg = 'Starting Engine…';
      if (line.includes('Browser ready') || line.includes('Session warmup')) statusMsg = 'Warming up session…';
      if (line.includes('Group requires membership')) statusMsg = `Skipping Group ${cG}…`;
      if (line.includes('Interrupted by user') || line.includes('TargetClosedError')) statusMsg = 'Engine Stopped';
      
      // Post Scrape Progress
      if (line.includes('Scraping Post:')) { statusMsg = 'Loading specific post...'; progress = 10; }
      if (line.includes('Expanding comments...')) { statusMsg = 'Expanding comments...'; progress = 40; }
      if (line.includes('Extracting post and comments...')) { statusMsg = 'Parsing comments...'; progress = 70; }
      if (line.includes('POST SCRAPE COMPLETE')) { statusMsg = 'Post scrape complete!'; progress = 100; }
    }
    if (cG > 0 && statusMsg !== 'Engine Stopped') {
      statusMsg = `Mining Group ${cG} of ${tG} (Scroll ${cS}/${tS})`;
      progress = Math.min(100, ((cG - 1) / tG) * 100 + (cS / tS) * (1 / tG) * 100);
    }
  }

  // ── Actions ───────────────────────────────────────────────────────────────
  const handleAction = async (action) => {
    try {
      const res = await axios.post(`${API_BASE}/actions/${action}`);
      addToast(res.data?.message || `${action} triggered!`, 'success');
      setTimeout(fetchDashboardData, 1000);
    } catch (err) {
      addToast(err.response?.data?.detail || `Failed to ${action}`, 'error');
    }
  };

  const handleScrapePost = async (e) => {
    e.preventDefault();
    if (!postUrl) return;
    try {
      const res = await axios.post(`${API_BASE}/actions/scrape-post`, { url: postUrl });
      addToast(res.data?.message || 'Post scrape triggered!', 'success');
      setPostUrl('');
      setTimeout(fetchDashboardData, 1000);
    } catch (err) {
      addToast(err.response?.data?.detail || 'Failed to start post scrape', 'error');
    }
  };

  const handleLogin = async () => {
    setIsLoggingIn(true);
    addToast('Opening Chrome — log in to Facebook in the browser window that opens…', 'info');
    try {
      await axios.post(`${API_BASE}/actions/login`);
      // Poll login-status until Chrome flow completes
      const poll = setInterval(async () => {
        try {
          const res = await axios.get(`${API_BASE}/login-status`);
          const state = res.data;
          if (!state.running) {
            clearInterval(poll);
            setIsLoggingIn(false);
            if (state.success) {
              addToast(state.message || '✅ Login successful!', 'success');
              const s = await axios.get(`${API_BASE}/session`);
              setSessionInfo(s.data);
            } else {
              addToast(state.message || '❌ Login failed or was cancelled.', 'error');
            }
          }
        } catch {
          clearInterval(poll);
          setIsLoggingIn(false);
        }
      }, 3000);
    } catch (err) {
      setIsLoggingIn(false);
      addToast(err.response?.data?.detail || 'Failed to start login.', 'error');
    }
  };

  const handleRefreshSession = async () => {
    setIsRefreshing(true);
    addToast('Session refresh started. This may take a minute…', 'info');
    try {
      const res = await axios.post(`${API_BASE}/actions/refresh`);
      addToast(res.data?.message || 'Refresh triggered.', 'success');
      let attempts = 0;
      const poll = setInterval(async () => {
        attempts++;
        try {
          const s = await axios.get(`${API_BASE}/session`);
          setSessionInfo(s.data);
          if (s.data?.status === 'ok' || attempts >= 45) {
            clearInterval(poll);
            setIsRefreshing(false);
            addToast(s.data?.status === 'ok' ? '✅ Session refreshed!' : 'Check logs for status.', s.data?.status === 'ok' ? 'success' : 'info');
          }
        } catch {
          clearInterval(poll);
          setIsRefreshing(false);
        }
      }, 2000);
    } catch (err) {
      addToast(err.response?.data?.detail || 'Failed to start refresh.', 'error');
      setIsRefreshing(false);
    }
  };

  const handleAddGroup = async (e) => {
    e.preventDefault();
    try {
      await axios.post(`${API_BASE}/groups`, newGroup);
      setNewGroup({ url: '', name: '', region: 'general', enabled: true });
      fetchGroups();
      addToast('Group added!', 'success');
    } catch (err) {
      addToast(err.response?.data?.detail || 'Failed to add group', 'error');
    }
  };

  const handleDeleteGroup = async (url) => {
    if (!window.confirm('Delete this group?')) return;
    try {
      await axios.delete(`${API_BASE}/groups`, { data: { url } });
      fetchGroups();
      addToast('Group deleted.', 'info');
    } catch { addToast('Failed to delete group.', 'error'); }
  };

  const handleToggleGroup = async (group) => {
    try {
      await axios.put(`${API_BASE}/groups`, { ...group, enabled: !group.enabled });
      fetchGroups();
    } catch { addToast('Failed to update group.', 'error'); }
  };

  const handleUpdateLead = async (leadId, updateData) => {
    try {
      await axios.patch(`${API_BASE}/leads/${leadId}`, updateData);
      setLeads(leads.map(l => l.id === leadId ? { ...l, ...updateData } : l));
    } catch (err) {
      addToast('Failed to update lead', 'error');
    }
  };

  const handleDeleteLead = async (leadId) => {
    if (!window.confirm('Delete this lead permanently?')) return;
    try {
      await axios.delete(`${API_BASE}/leads/${leadId}`);
      setLeads(leads.filter(l => l.id !== leadId));
      addToast('Lead deleted.', 'info');
    } catch (err) {
      addToast('Failed to delete lead.', 'error');
    }
  };

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="app-container">
      <Toast toasts={toasts} removeToast={removeToast} />

      {/* ── Sidebar ─────────────────────────────────────────────────── */}
      <aside className="sidebar">

        {/* Brand */}
        <div>
          <div className="brand-logo">
            REKOMND<span className="plus">+</span>
          </div>
          <div className="brand-tagline">Lead Intelligence</div>
          <div className="gold-divider" style={{ marginTop: '0.75rem' }} />
        </div>

        {/* Nav */}
        <nav style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
          <button
            className={`nav-btn ${activeTab === 'dashboard' ? 'active' : ''}`}
            onClick={() => setActiveTab('dashboard')}
          >
            <LayoutDashboard size={18} /> Dashboard
          </button>
          <button
            className={`nav-btn ${activeTab === 'settings' ? 'active' : ''}`}
            onClick={() => setActiveTab('settings')}
          >
            <Settings size={18} /> Group Settings
          </button>
        </nav>

        {/* Session Card */}
        <SessionCard
          sessionInfo={sessionInfo}
          isRefreshing={isRefreshing}
          isLoggingIn={isLoggingIn}
          onRefresh={handleRefreshSession}
          onLogin={handleLogin}
        />

        {/* Engine Controls */}
        <div style={{ marginTop: 'auto', display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
          <div className="gold-divider" />
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button
              className="btn btn-primary"
              onClick={() => handleAction('scrape')}
              disabled={isRunning}
              style={{ flex: 1 }}
            >
              {isRunning
                ? <><Loader2 size={18} className="spin" /> Running…</>
                : <><Rocket size={18} /> Start Scraping</>}
            </button>
            <button
              className="btn btn-danger"
              onClick={() => handleAction('stop')}
              disabled={!isRunning}
              style={{ width: 'auto', padding: '0.7rem 0.9rem' }}
              title="Stop Scraper"
            >
              <XCircle size={18} />
            </button>
          </div>

          <form onSubmit={handleScrapePost} style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem', marginTop: '0.5rem' }}>
            <div style={{ fontSize: '0.85rem', color: 'var(--accent-gold)', fontWeight: 600 }}>📌 Scrape with a Post</div>
            <input 
              type="url" 
              placeholder="Post URL..." 
              value={postUrl}
              onChange={e => setPostUrl(e.target.value)}
              className="form-input"
              style={{ fontSize: '0.8rem', padding: '0.5rem' }}
              required
            />
            <button
              type="submit"
              className="btn btn-primary"
              disabled={isRunning || !postUrl}
              style={{ background: 'var(--bg-card)', border: '1px solid var(--accent-gold)', color: 'var(--accent-gold)' }}
            >
              Scrape Post
            </button>
          </form>
        </div>
      </aside>

      {/* ── Main Content ─────────────────────────────────────────────── */}
      <main className="main-content">

        {/* ── Dashboard Tab ───────────────────────────────────────────── */}
        {activeTab === 'dashboard' && (
          <div>
            <h1 className="gradient-title">Lead Dashboard</h1>
            <p className="subtitle">Real-time buyer intelligence — Egypt Real Estate</p>

            {/* Session Alert Banner — shown when expired/missing */}
            {(sessionInfo?.status === 'expired' || sessionInfo?.status === 'missing') && !isLoggingIn && (
              <div style={{
                background: 'rgba(231,76,60,0.08)',
                border: '1px solid rgba(231,76,60,0.35)',
                borderRadius: '12px',
                padding: '1rem 1.25rem',
                marginBottom: '1.5rem',
                display: 'flex',
                alignItems: 'center',
                gap: '0.75rem',
              }}>
                <ShieldOff size={20} style={{ color: '#e74c3c', flexShrink: 0 }} />
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 700, color: '#ff6b6b', fontSize: '0.95rem' }}>
                    {sessionInfo.status === 'missing' ? '⚠️ No Facebook Session Yet' : '⚠️ Session Expired'}
                  </div>
                  <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem', marginTop: '2px' }}>
                    Click <strong style={{ color: 'var(--text-main)' }}>Login to Facebook</strong> in the sidebar — a Chrome window will open for you to log in.
                  </div>
                </div>
                <button
                  onClick={handleLogin}
                  disabled={isLoggingIn}
                  style={{
                    display: 'flex', alignItems: 'center', gap: '6px',
                    background: 'linear-gradient(135deg, var(--accent-gold), var(--accent-gold-2))',
                    border: 'none', color: '#0d1120', padding: '0.55rem 1.1rem',
                    borderRadius: '8px', cursor: 'pointer', fontWeight: 700,
                    fontSize: '0.85rem', fontFamily: 'Outfit, sans-serif', whiteSpace: 'nowrap',
                  }}
                >
                  <LogIn size={15} /> Login Now
                </button>
              </div>
            )}

            {/* Login in progress banner */}
            {isLoggingIn && (
              <div style={{
                background: 'rgba(61,127,255,0.08)',
                border: '1px solid rgba(61,127,255,0.3)',
                borderRadius: '12px',
                padding: '1rem 1.25rem',
                marginBottom: '1.5rem',
                display: 'flex',
                alignItems: 'center',
                gap: '0.75rem',
              }}>
                <Loader2 size={20} className="spin" style={{ color: 'var(--accent-blue)', flexShrink: 0 }} />
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 700, color: 'var(--text-main)', fontSize: '0.95rem' }}>
                    Chrome is open — please log in to Facebook
                  </div>
                  <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem', marginTop: '2px' }}>
                    Log in to your Facebook account in the Chrome window, wait for your feed to load, then come back here.
                  </div>
                </div>
                <button
                  onClick={async () => {
                    try {
                      await axios.post('http://localhost:8000/api/actions/login/finish');
                    } catch (e) {
                      console.error(e);
                    }
                  }}
                  style={{
                    display: 'flex', alignItems: 'center', gap: '6px',
                    background: 'var(--accent-green)',
                    border: 'none', color: '#0d1120', padding: '0.55rem 1.1rem',
                    borderRadius: '8px', cursor: 'pointer', fontWeight: 700,
                    fontSize: '0.85rem', fontFamily: 'Outfit, sans-serif', whiteSpace: 'nowrap',
                  }}
                >
                  <CheckCircle size={15} /> Finished
                </button>
              </div>
            )}

            {/* Metrics */}
            <div className="metrics-grid">
              <div className="glass-card">
                <p className="metric-value">{stats.total_leads ?? 0}</p>
                <p className="metric-label">Total Leads</p>
              </div>
              <div className="glass-card card-hot">
                <p className="metric-value">{stats.hot_leads ?? 0}</p>
                <p className="metric-label">🔥 Hot Leads</p>
              </div>
              <div className="glass-card card-phone">
                <p className="metric-value">{stats.with_phone ?? 0}</p>
                <p className="metric-label">With Phone</p>
              </div>
              <div className="glass-card card-contacted">
                <p className="metric-value">{stats.contacted ?? 0}</p>
                <p className="metric-label">Contacted</p>
              </div>
            </div>

            {/* Progress */}
            <div className="progress-container">
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                <Rocket size={18} style={{ color: 'var(--accent-gold)' }} />
                <span style={{ fontWeight: 600, color: 'var(--text-main)' }}>Engine:</span>
                <span style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>{statusMsg}</span>
                <span style={{ marginLeft: 'auto', fontSize: '0.85rem', color: 'var(--accent-gold)', fontWeight: 600 }}>
                  {Math.round(progress)}%
                </span>
              </div>
              <div className="progress-bar-bg">
                <div className="progress-bar-fill" style={{ width: `${progress}%` }} />
              </div>
            </div>

            {/* Lead Table Controls */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '1.5rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
              <h3 style={{ color: 'var(--text-main)', fontWeight: 700 }}>Lead Database</h3>
              <div style={{
                display: 'flex', alignItems: 'center', gap: '0.75rem',
                background: 'var(--bg-card)', padding: '0.4rem 1rem', borderRadius: '8px',
                border: '1px solid var(--border-light)',
              }}>
                <label style={{ fontSize: '0.85rem', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                  Min Score: <strong style={{ color: 'var(--accent-gold)' }}>{minScore}</strong>
                </label>
                <input
                  type="range" min="0" max="100" value={minScore}
                  onChange={e => setMinScore(Number(e.target.value))}
                  style={{ accentColor: 'var(--accent-gold)', cursor: 'pointer', width: '120px' }}
                />
              </div>
              <a
                href={`${API_BASE}/export?min_score=${minScore}`}
                download
                style={{
                  display: 'flex', alignItems: 'center', gap: '6px',
                  background: 'linear-gradient(135deg, var(--accent-gold) 0%, var(--accent-gold-2) 100%)',
                  color: '#0d1120', padding: '0.5rem 1rem', borderRadius: '8px',
                  textDecoration: 'none', fontSize: '0.88rem', fontWeight: 700,
                  marginLeft: 'auto',
                }}
              >
                <Download size={15} /> Export Excel
              </a>
            </div>

            {/* Leads Table */}
            <div className="table-container">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Name & Phone</th>
                    <th>Score / Grade</th>
                    <th>Intent & Type</th>
                    <th>Budget</th>
                    <th>Source & Link</th>
                    <th>Likes</th>
                    <th>Details</th>
                    <th>Notes</th>
                    <th style={{ width: '60px' }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {leads.map(lead => (
                    <tr key={lead.id}>
                      <td style={{ maxWidth: '140px', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        <div style={{ fontWeight: 600, color: 'var(--text-main)', whiteSpace: 'nowrap' }}>
                          {lead.buyer_name || <span style={{ color: 'var(--text-dim)' }}>Unknown</span>}
                        </div>
                        <div style={{ color: lead.phone_numbers ? 'var(--accent-gold)' : 'var(--text-dim)', fontFamily: 'monospace', fontSize: '0.85rem', marginTop: '2px' }}>
                          {lead.phone_numbers || '—'}
                        </div>
                      </td>
                      <td>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <span style={{ width: '24px', fontWeight: 700, color: 'var(--text-main)' }}>{lead.lead_score}</span>
                            <div className="score-bar-bg">
                              <div className="score-bar-fill" style={{ width: `${lead.lead_score}%` }} />
                            </div>
                          </div>
                          <GradeBadge grade={lead.lead_grade} />
                        </div>
                      </td>
                      <td style={{ color: 'var(--text-muted)', fontSize: '0.88rem' }}>
                        <span style={{ textTransform: 'capitalize' }}>{lead.intent || '—'}</span>
                        {lead.property_type && lead.property_type !== 'unknown' && (
                          <div style={{ color: 'var(--text-dim)', fontSize: '0.8rem', marginTop: '2px' }}>
                            Type: {lead.property_type}
                          </div>
                        )}
                      </td>
                      <td style={{ color: 'var(--text-muted)', fontSize: '0.88rem' }}>
                        {lead.budget_max ? (
                          <span style={{ color: 'var(--accent-gold)', fontWeight: 600 }}>
                            {Number(lead.budget_max).toLocaleString()} EGP
                          </span>
                        ) : '—'}
                      </td>
                      <td style={{ color: 'var(--text-muted)', fontSize: '0.85rem', maxWidth: '120px' }}>
                        <div style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          {lead.group_name || 'Facebook Group'}
                        </div>
                        {lead.post_url && (
                          <a href={lead.post_url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-blue)', textDecoration: 'none', display: 'inline-block', marginTop: '2px', fontSize: '0.8rem' }}>
                            View Post ↗
                          </a>
                        )}
                      </td>
                      <td style={{ color: 'var(--text-main)', fontSize: '0.88rem', fontWeight: 600 }}>
                        {lead.reactions || 0}
                      </td>
                      <td style={{ maxWidth: '220px', color: 'var(--text-muted)', fontSize: '0.83rem' }}>
                        <div style={{ display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' }} title={lead.raw_text}>
                          {lead.raw_text || '—'}
                        </div>
                      </td>
                      <td style={{ width: '160px' }}>
                        <input 
                          type="text" 
                          placeholder="Add a note..." 
                          value={lead.contact_notes || ''}
                          onChange={(e) => {
                            const newLeads = [...leads];
                            const idx = newLeads.findIndex(l => l.id === lead.id);
                            newLeads[idx].contact_notes = e.target.value;
                            setLeads(newLeads);
                          }}
                          onBlur={(e) => handleUpdateLead(lead.id, { contact_notes: e.target.value })}
                          style={{ 
                            background: 'rgba(255,255,255,0.05)', border: '1px solid var(--border-light)',
                            color: 'var(--text-main)', padding: '6px 8px', borderRadius: '6px', fontSize: '0.8rem',
                            width: '100%', outline: 'none'
                          }}
                        />
                      </td>
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                          <button
                            onClick={() => handleUpdateLead(lead.id, { is_contacted: !lead.is_contacted })}
                            style={{ 
                              background: 'none', border: 'none', cursor: 'pointer', padding: 0,
                              color: lead.is_contacted ? 'var(--accent-green)' : 'var(--text-dim)',
                              transition: 'color 0.2s'
                            }}
                            title="Mark as contacted"
                          >
                            <CheckCircle size={18} />
                          </button>
                          <button
                            onClick={() => handleDeleteLead(lead.id)}
                            style={{ 
                              background: 'none', border: 'none', cursor: 'pointer', padding: 0,
                              color: 'rgba(231,76,60,0.6)', transition: 'color 0.2s' 
                            }}
                            onMouseEnter={e => e.currentTarget.style.color = 'rgba(231,76,60,1)'}
                            onMouseLeave={e => e.currentTarget.style.color = 'rgba(231,76,60,0.6)'}
                            title="Delete Lead"
                          >
                            <Trash2 size={16} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {leads.length === 0 && (
                    <tr>
                      <td colSpan="7" style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-dim)' }}>
                        {loading ? 'Loading leads…' : 'No leads found.'}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* ── Settings Tab ─────────────────────────────────────────────── */}
        {activeTab === 'settings' && (
          <div>
            <h1 className="gradient-title">Group Settings</h1>
            <p className="subtitle">Configure which Facebook groups the engine should mine for buyers.</p>

            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '2rem' }}>

              {/* Groups Table */}
              <div className="glass-card" style={{ flex: '1 1 500px', padding: 0, overflow: 'auto' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Status</th>
                      <th>Group</th>
                      <th>Region</th>
                      <th style={{ textAlign: 'right' }}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {groups.map((g, i) => (
                      <tr key={i}>
                        <td style={{ width: '52px' }}>
                          <button
                            onClick={() => handleToggleGroup(g)}
                            style={{ background: 'none', border: 'none', cursor: 'pointer', color: g.enabled ? 'var(--accent-green)' : 'var(--text-dim)', padding: 0 }}
                          >
                            {g.enabled ? <CheckCircle size={19} /> : <XCircle size={19} />}
                          </button>
                        </td>
                        <td>
                          <div style={{ fontWeight: 600, fontSize: '0.9rem' }}>{g.name}</div>
                          <a href={g.url} target="_blank" rel="noreferrer" style={{ fontSize: '0.75rem', color: 'var(--accent-gold)', opacity: 0.8, textDecoration: 'none' }}>
                            {g.url.length > 55 ? g.url.slice(0, 55) + '…' : g.url}
                          </a>
                        </td>
                        <td style={{ textTransform: 'capitalize', color: 'var(--text-muted)', fontSize: '0.88rem' }}>{g.region}</td>
                        <td style={{ textAlign: 'right' }}>
                          <button
                            onClick={() => handleDeleteGroup(g.url)}
                            style={{ background: 'rgba(231,76,60,0.1)', border: '1px solid rgba(231,76,60,0.25)', color: '#ff6b6b', padding: '0.35rem 0.6rem', borderRadius: '7px', cursor: 'pointer' }}
                          >
                            <Trash2 size={14} />
                          </button>
                        </td>
                      </tr>
                    ))}
                    {groups.length === 0 && (
                      <tr><td colSpan="4" style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-dim)' }}>No groups configured.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>

              {/* Add Group Form */}
              <div className="glass-card" style={{ flex: '0 0 300px' }}>
                <h3 style={{ marginBottom: '1.25rem', color: 'var(--accent-gold)' }}>➕ Add Group</h3>
                <form onSubmit={handleAddGroup}>
                  <div className="form-group">
                    <label className="form-label">Group URL</label>
                    <input required type="url" className="form-input" placeholder="https://facebook.com/groups/…"
                      value={newGroup.url} onChange={e => setNewGroup({ ...newGroup, url: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Group Name</label>
                    <input required type="text" className="form-input" placeholder="e.g. Cairo Real Estate"
                      value={newGroup.name} onChange={e => setNewGroup({ ...newGroup, name: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Region</label>
                    <select className="form-select" value={newGroup.region} onChange={e => setNewGroup({ ...newGroup, region: e.target.value })}>
                      <option value="general">General</option>
                      <option value="cairo">Cairo</option>
                      <option value="new_cairo">New Cairo</option>
                      <option value="new_capital">New Capital</option>
                      <option value="west_cairo">West Cairo / 6 Oct</option>
                      <option value="alexandria">Alexandria</option>
                      <option value="north_coast">North Coast</option>
                      <option value="red_sea">Red Sea</option>
                      <option value="custom">Custom</option>
                    </select>
                  </div>
                  <button type="submit" className="btn btn-primary" style={{ marginTop: '0.75rem' }}>
                    Add Group
                  </button>
                </form>
              </div>

            </div>
          </div>
        )}

      </main>
    </div>
  );
}

export default App;
