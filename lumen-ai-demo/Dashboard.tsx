import React, { useState, useEffect, useRef } from 'react';

// --- Types ---
interface Span {
  id: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  cost: number;
  tenant: string;
  timestamp: string;
}

// --- Mock Data Generator ---
const MODELS = [
  { name: 'gpt-4o', in: 5.0, out: 15.0 },
  { name: 'claude-3-5-sonnet', in: 3.0, out: 15.0 },
  { name: 'deepseek-v3', in: 0.27, out: 0.40 },
];

const TENANTS = ['Acme Corp', 'Global Dynamics', 'Stark Ind'];

const generateSpan = (tenant: string): Span => {
  const model = MODELS[Math.floor(Math.random() * MODELS.length)];
  const inTokens = Math.floor(Math.random() * 2000) + 100;
  const outTokens = Math.floor(Math.random() * 1000) + 50;
  const cost = (inTokens * model.in / 1_000_000) + (outTokens * model.out / 1_000_000);
  
  return {
    id: Math.random().toString(36).substring(7),
    model: model.name,
    input_tokens: inTokens,
    output_tokens: outTokens,
    cost: cost,
    tenant: tenant,
    timestamp: new Date().toLocaleTimeString(),
  };
};

// --- Styles ---
const styles = {
  container: {
    backgroundColor: '#050505',
    color: '#fff',
    minHeight: '100vh',
    fontFamily: 'Inter, system-ui, sans-serif',
    padding: '40px',
    display: 'grid',
    gridTemplateColumns: '350px 1fr 350px',
    gap: '30px',
  },
  card: {
    backgroundColor: '#0a0a0a',
    border: '1px solid #1a1a1a',
    borderRadius: '12px',
    padding: '20px',
    display: 'flex',
    flexDirection: 'column' as const,
  },
  header: {
    fontSize: '0.8rem',
    textTransform: 'uppercase' as const,
    color: '#666',
    letterSpacing: '1px',
    marginBottom: '15px',
    display: 'flex',
    justifyContent: 'space-between',
  },
  traceLine: {
    fontSize: '0.85rem',
    color: '#00F5FF',
    fontFamily: 'monospace',
    marginBottom: '8px',
    opacity: 0.8,
  },
  costValue: {
    fontSize: '3rem',
    fontWeight: 'bold' as const,
    color: '#fff',
    margin: '10px 0',
    fontVariantNumeric: 'tabular-nums',
  },
  prismContainer: {
    display: 'flex',
    flexDirection: 'column' as const,
    alignItems: 'center',
    justifyContent: 'center',
    textAlign: 'center' as const,
  },
  prism: {
    width: '120px',
    height: '120px',
    background: 'linear-gradient(135deg, #00F5FF 0%, #9D4EDD 100%)',
    clipPath: 'polygon(50% 0%, 0% 100%, 100% 100%)',
    boxShadow: '0 0 50px rgba(0, 245, 255, 0.3)',
    marginBottom: '30px',
    animation: 'pulse 2s infinite ease-in-out',
  }
};

export default function LumenDashboard() {
  const [totalCost, setTotalCost] = useState(0);
  const [spans, setSpans] = useState<Span[]>([]);
  const [currentTenant, setCurrentTenant] = useState(TENANTS[0]);
  const [isSimulating, setIsSimulating] = useState(false);

  useEffect(() => {
    if (!isSimulating) return;

    const interval = setInterval(() => {
      const newSpan = generateSpan(currentTenant);
      setSpans(prev => [newSpan, ...prev].slice(0, 15));
      setTotalCost(prev => prev + newSpan.cost);
    }, 1200);

    return () => clearInterval(interval);
  }, [isSimulating, currentTenant]);

  return (
    <div style={styles.container}>
      {/* Left: Raw Traces */}
      <div style={styles.card}>
        <div style={styles.header}>Incoming OTel Traces</div>
        <div style={{ overflow: 'hidden' }}>
          {spans.map(s => (
            <div key={s.id} style={styles.traceLine}>
              {`> span_id=${s.id} model=${s.model}`}
            </div>
          ))}
          {spans.length === 0 && <div style={{color: '#333'}}>Waiting for agent...</div>}
        </div>
      </div>

      {/* Center: The Prism */}
      <div style={styles.prismContainer}>
        <div style={{...styles.prism, opacity: isSimulating ? 1 : 0.4}}></div>
        <h1 style={{ fontSize: '2rem', marginBottom: '10px' }}>LumenAI Processor</h1>
        <p style={{ color: '#666', maxWidth: '300px' }}>
          Real-time enrichment: Cost Computing + Tenant Isolation + Event Normalization.
        </p>
        <button 
          onClick={() => setIsSimulating(!isSimulating)}
          style={{
            marginTop: '30px',
            padding: '12px 30px',
            borderRadius: '100px',
            backgroundColor: isSimulating ? '#ff4d4d' : '#00F5FF',
            color: '#000',
            fontWeight: 'bold',
            border: 'none',
            cursor: 'pointer',
            transition: 'all 0.2s'
          }}
        >
          {isSimulating ? 'Stop Simulation' : 'Launch Agent Task'}
        </button>
      </div>

      {/* Right: FinOps Results */}
      <div style={styles.card}>
        <div style={styles.header}>
          FinOps Metrics
          <select 
            value={currentTenant} 
            onChange={(e) => setCurrentTenant(e.target.value)}
            style={{ backgroundColor: '#111', color: '#fff', border: 'none', fontSize: '0.7rem' }}
          >
            {TENANTS.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        
        <div style={{ color: '#666', fontSize: '0.8rem' }}>Total Cost ({currentTenant})</div>
        <div style={styles.costValue}>${totalCost.toFixed(6)}</div>
        
        <div style={{ marginTop: 'auto' }}>
          <div style={styles.header}>Active Model Usage</div>
          {MODELS.map(m => (
             <div key={m.name} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px', fontSize: '0.85rem' }}>
                <span style={{ color: '#9D4EDD' }}>{m.name}</span>
                <span>{spans.filter(s => s.model === m.name).length} hits</span>
             </div>
          ))}
        </div>
      </div>

      <style>{`
        @keyframes pulse {
          0% { transform: scale(1); filter: brightness(1); }
          50% { transform: scale(1.05); filter: brightness(1.3); }
          100% { transform: scale(1); filter: brightness(1); }
        }
      `}</style>
    </div>
  );
}
