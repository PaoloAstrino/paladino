import { useState, useEffect, useRef } from "react";
import {
  Activity,
  Search,
  GitFork,
  Database,
  Upload,
  AlertTriangle,
  RefreshCw,
  Send,
  Code,
  FileText,
  CheckCircle,
  HelpCircle,
  BookOpen,
  Plus,
  Play,
  Trash2,
  Lock,
  ChevronDown,
  Layers,
  Info,
  Download,
  AlertCircle,
  FileSpreadsheet
} from "lucide-react";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  BarChart,
  Bar,
  Cell
} from "recharts";
import ForceGraph2D from "react-force-graph-2d";

// =============================================================================
// TYPINGS
// =============================================================================

interface HealthStatus {
  status: string;
  version: string;
  neo4j: {
    status: string;
    uri: string;
    statistics?: {
      node_count: number;
      relationship_count: number;
      node_labels: string[];
    };
  };
  system: {
    python_version: string;
    platform: string;
    disk?: {
      total_gb: number;
      used_gb: number;
      free_gb: number;
      percent_used: number;
    };
  };
}

interface AlertItem {
  id: string;
  alert_type: string;
  entity_id: string;
  old_value: any;
  new_value: any;
  delta?: number;
  date_a: string;
  severity: "high" | "medium" | "low";
}

interface DuplicateCandidate {
  entity_id: string;
  cf: string;
  nome_normalizzato: string;
  similarity_score: number;
  match_reason: string;
  properties?: {
    regione?: string;
    provincia?: string;
  };
}

interface MergeHistoryItem {
  id: string;
  timestamp: string;
  target_id: string;
  source_id: string;
  rollback_id: string;
  operator: string;
}

interface ChatMessage {
  id: string;
  sender: "user" | "agent";
  text: string;
  cypher?: string;
  executionTimeMs?: number;
  sources?: string[];
}

interface GraphNode {
  id: string;
  label?: string;
  nome_normalizzato?: string;
  title?: string;
  name?: string;
  risk_score?: number;
  type?: string;
  cf?: string;
  cig?: string;
  color?: string;
  val?: number; // visual node size
}

interface GraphLink {
  id: string;
  source: string;
  target: string;
  type: string;
}

interface GraphData {
  nodes: GraphNode[];
  links: GraphLink[];
}

interface Comment {
  id: string;
  entity_id: string;
  entity_type: string;
  content: string;
  author: string;
  created_at: string;
}

interface NotebookCell {
  id: string;
  cell_type: "cypher_query" | "markdown";
  content: string;
  title: string;
  output?: any[]; // table format: list of objects
  error?: string;
  executed_at?: string;
}

interface Notebook {
  id: string;
  title: string;
  author: string;
  cells: NotebookCell[];
  created_at: string;
}

interface CSVRowValidation {
  rowIdx: number;
  cf: string;
  name: string;
  cig: string;
  title: string;
  isValid: boolean;
  errors: string[];
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export default function App() {
  const [activeTab, setActiveTab] = useState<"dashboard" | "rag" | "graph" | "resolver" | "ingest" | "notebooks">("dashboard");
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [loadingHealth, setLoadingHealth] = useState(false);
  const [backendOffline, setBackendOffline] = useState(true);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [isGlobalIngestRunning, setIsGlobalIngestRunning] = useState(false);

  // Global selected node for detail drawer
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);

  const checkHealth = async () => {
    setLoadingHealth(true);
    try {
      const res = await fetch("/api/health");
      if (res.ok) {
        const data = await res.json();
        setHealth(data);
        setBackendOffline(false);
      } else {
        setBackendOffline(true);
      }
    } catch {
      setBackendOffline(true);
    } finally {
      setLoadingHealth(false);
    }
  };

  useEffect(() => {
    checkHealth();
  }, []);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-canvas text-ink font-sans">
      {/* Sidebar Navigation */}
      <aside className={`flex-shrink-0 border-r border-hairline bg-surface-2 flex flex-col justify-between transition-all duration-300 ${isSidebarCollapsed ? "w-16" : "w-64"}`}>
        <div>
          {/* Header */}
          <div className={`h-16 flex items-center border-b border-hairline ${isSidebarCollapsed ? "justify-center" : "px-6 gap-3"}`}>
            <svg className="h-8 w-8 text-primary flex-shrink-0" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M16 3L6 7V15C6 21.2 10.3 26.9 16 29C21.7 26.9 26 21.2 26 15V7L16 3Z" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
              <circle cx="16" cy="11" r="2" fill="currentColor" />
              <circle cx="12" cy="19" r="2" fill="currentColor" />
              <circle cx="20" cy="19" r="2" fill="currentColor" />
              <line x1="16" y1="11" x2="12" y2="19" stroke="currentColor" strokeWidth="1.5" strokeDasharray="1.5 1.5" />
              <line x1="16" y1="11" x2="20" y2="19" stroke="currentColor" strokeWidth="1.5" strokeDasharray="1.5 1.5" />
              <line x1="12" y1="19" x2="20" y2="19" stroke="currentColor" strokeWidth="1.5" strokeDasharray="1.5 1.5" />
            </svg>
            {!isSidebarCollapsed && (
              <div>
                <span className="font-semibold text-ink tracking-tight block">Paladino</span>
                <span className="text-[10px] text-ink-subtle block font-mono">v0.2.0-sec</span>
              </div>
            )}
          </div>

          {/* Navigation Links */}
          <nav className="p-4 space-y-1">
            {[
              { id: "dashboard", label: "Dashboard", icon: Activity },
              { id: "rag", label: "GraphRAG Chat", icon: Search },
              { id: "graph", label: "Graph Explorer", icon: Layers },
              { id: "resolver", label: "Entity Resolver", icon: GitFork },
              { id: "ingest", label: "Ingestion Hub", icon: Upload },
              { id: "notebooks", label: "Notebooks", icon: BookOpen }
            ].map((tab) => {
              const Icon = tab.icon;
              return (
                <button
                  key={tab.id}
                  onClick={() => {
                    if (isGlobalIngestRunning) return;
                    setActiveTab(tab.id as any);
                  }}
                  disabled={isGlobalIngestRunning}
                  className={`w-full flex items-center py-2.5 rounded-md text-sm transition-all duration-200 ${
                    isSidebarCollapsed ? "justify-center px-0" : "px-4 gap-3"
                  } ${
                    activeTab === tab.id
                      ? "bg-surface-1 text-ink border-l-2 border-primary"
                      : isGlobalIngestRunning
                        ? "text-ink-subtle/30 cursor-not-allowed"
                        : "text-ink-subtle hover:text-ink hover:bg-surface-1/50"
                  }`}
                  title={isSidebarCollapsed ? tab.label : ""}
                >
                  <Icon className="h-4 w-4 flex-shrink-0" />
                  {!isSidebarCollapsed && <span>{tab.label}</span>}
                </button>
              );
            })}

            {/* Collapse Toggle Button */}
            <button
              onClick={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
              className={`w-full flex items-center py-2.5 rounded-md text-sm text-ink-subtle hover:text-ink hover:bg-surface-1/50 ${
                isSidebarCollapsed ? "justify-center px-0" : "px-4 gap-3"
              }`}
              title={isSidebarCollapsed ? "Espandi Menu" : "Contrai Menu"}
            >
              <ChevronDown className={`h-4 w-4 transition-transform duration-300 ${isSidebarCollapsed ? "-rotate-90" : "rotate-90"}`} />
              {!isSidebarCollapsed && <span>Contrai Menu</span>}
            </button>
          </nav>
        </div>

        {/* Localhost Health Card */}
        {isSidebarCollapsed ? (
          <div className="flex justify-center p-4 border-t border-hairline">
            <div 
              className={`h-3 w-3 rounded-full ${backendOffline ? "bg-red-500" : "bg-emerald-500"}`} 
              title={backendOffline ? "OFFLINE (Port 8000)" : "ONLINE (200 OK)"}
            />
          </div>
        ) : (
          <div className="p-4 border-t border-hairline bg-surface-3/50 m-4 rounded-lg">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-ink-subtle">Local Host (API)</span>
              <button
                onClick={checkHealth}
                disabled={loadingHealth}
                className="text-ink-subtle hover:text-primary transition-colors duration-200"
              >
                <RefreshCw className={`h-3 w-3 ${loadingHealth ? "animate-spin" : ""}`} />
              </button>
            </div>
            <div className="flex items-center gap-2">
              <div className={`h-2.5 w-2.5 rounded-full ${backendOffline ? "bg-red-500" : "bg-emerald-500"}`} />
              <span className="text-xs font-mono font-semibold">
                {backendOffline ? "OFFLINE (Port 8000)" : "ONLINE (200 OK)"}
              </span>
            </div>
            {health?.neo4j && (
              <div className="mt-2 pt-2 border-t border-hairline flex items-center justify-between text-[11px] text-ink-subtle font-mono">
                <span>Graph Size:</span>
                <span>{health.neo4j.statistics?.node_count || 0} nodes</span>
              </div>
            )}
          </div>
        )}
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col h-full overflow-hidden bg-canvas relative">
        {isGlobalIngestRunning && (
          <div className="absolute inset-0 bg-canvas/80 backdrop-blur-sm z-50 flex flex-col items-center justify-center gap-4 text-center select-none animate-fadeIn">
            <div className="h-12 w-12 rounded-full border-4 border-primary border-t-transparent animate-spin" />
            <h3 className="text-lg font-bold text-ink">Importazione Graph Database in Corso...</h3>
            <p className="text-sm text-ink-subtle max-w-sm px-4">
              Scrittura in Neo4j a blocchi di 1000 righe. Non chiudere o ricaricare questa pagina per evitare la perdita di consistenza del database locale.
            </p>
          </div>
        )}

        {/* Header Bar */}
        <header className="h-16 border-b border-hairline px-8 flex items-center justify-between bg-surface-1/25 flex-shrink-0">
          <h2 className="text-lg font-semibold tracking-tight text-ink">
            {activeTab === "dashboard" && "Dashboard Overview"}
            {activeTab === "rag" && "GraphRAG Chat Workspace"}
            {activeTab === "graph" && "Interactive Graph Explorer"}
            {activeTab === "resolver" && "Entity Deduplication & Merging"}
            {activeTab === "ingest" && "Data Ingestion Control"}
            {activeTab === "notebooks" && "Investigation Notebooks"}
          </h2>
          <div className="flex items-center gap-4 text-sm text-ink-subtle">
            <span className="px-2 py-0.5 bg-surface-1 border border-hairline rounded text-xs font-mono">Local Workstation</span>
          </div>
        </header>

        {/* View Workspace */}
        <div className="flex-1 overflow-y-auto p-8">
          {activeTab === "dashboard" && <DashboardView health={health} onSelectNode={setSelectedNode} />}
          {activeTab === "rag" && <RAGView backendOffline={backendOffline} onSelectNode={setSelectedNode} />}
          {activeTab === "graph" && <GraphView backendOffline={backendOffline} onSelectNode={setSelectedNode} />}
          {activeTab === "resolver" && <ResolverView backendOffline={backendOffline} />}
          {activeTab === "ingest" && (
            <IngestView
              backendOffline={backendOffline}
              onIngestStateChange={setIsGlobalIngestRunning}
            />
          )}
          {activeTab === "notebooks" && <NotebooksView backendOffline={backendOffline} />}
        </div>

        {/* Slide-out Node Detail Drawer */}
        {selectedNode && (
          <NodeDetailDrawer
            node={selectedNode}
            onClose={() => setSelectedNode(null)}
            backendOffline={backendOffline}
          />
        )}
      </main>
    </div>
  );
}

// =============================================================================
// 1. DASHBOARD VIEW (With Clickable Alerts)
// =============================================================================

function DashboardView({ health, onSelectNode }: { health: HealthStatus | null; onSelectNode: (node: GraphNode) => void }) {
  const [alerts, setAlerts] = useState<AlertItem[]>([
    { id: "1", alert_type: "risk_threshold_crossed", entity_id: "08234850152", old_value: 0.15, new_value: 0.88, delta: 0.73, date_a: "2026-07-11T12:00:00", severity: "high" },
    { id: "2", alert_type: "ownership_migration", entity_id: "12845620980", old_value: "Local", new_value: "Offshore", date_a: "2026-07-10T15:30:00", severity: "medium" },
    { id: "3", alert_type: "tender_spike", entity_id: "Z1A2B3C4D5", old_value: 0, new_value: 1200000.0, date_a: "2026-07-09T09:00:00", severity: "medium" }
  ]);

  useEffect(() => {
    if (!health || !health.neo4j) return;
    const fetchAlerts = async () => {
      try {
        const res = await fetch("/api/alerts?limit=10");
        if (res.ok) {
          const data = await res.json();
          if (data.alerts && data.alerts.length > 0) {
            const formatted = data.alerts.map((a: any) => ({
              id: a.id,
              alert_type: a.type,
              entity_id: a.entity_id,
              old_value: a.details?.old_risk || 0,
              new_value: a.details?.new_risk || a.risk_score || 0.8,
              delta: (a.details?.new_risk || 0) - (a.details?.old_risk || 0),
              date_a: a.created_at || new Date().toISOString(),
              severity: a.severity === "critical" || a.severity === "high" ? "high" : "medium"
            }));
            setAlerts(formatted);
          }
        }
      } catch (e) {
        console.error("Failed to fetch alerts from backend:", e);
      }
    };
    fetchAlerts();
  }, [health]);

  const riskDistribution = [
    { name: "High Risk (> 0.7)", value: health?.neo4j.statistics ? 124 : 14, color: "#ef4444" },
    { name: "Medium Risk (0.4 - 0.7)", value: health?.neo4j.statistics ? 482 : 45, color: "#f59e0b" },
    { name: "Low Risk (< 0.4)", value: health?.neo4j.statistics ? 11202 : 120, color: "#10b981" }
  ];

  const historicalRisk = [
    { name: "Q1-25", avgRisk: 0.15 },
    { name: "Q2-25", avgRisk: 0.18 },
    { name: "Q3-25", avgRisk: 0.22 },
    { name: "Q4-25", avgRisk: 0.21 },
    { name: "Q1-26", avgRisk: 0.25 },
    { name: "Q2-26", avgRisk: 0.28 }
  ];

  return (
    <div className="space-y-8 animate-fadeIn">
      {/* KPI Cards grid */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <div className="p-6 bg-surface-1 border border-hairline rounded-lg">
          <span className="text-xs text-ink-subtle block mb-1">Total Appalti Value</span>
          <h3 className="text-2xl font-semibold tracking-tight text-ink">
            {health?.neo4j.statistics ? "124,5M €" : "12.4M €"}
          </h3>
          <span className="text-[10px] text-ink-subtle mt-2 block font-mono">ANAC spend logs</span>
        </div>

        <div className="p-6 bg-surface-1 border border-hairline rounded-lg">
          <span className="text-xs text-ink-subtle block mb-1">Companies Tracked</span>
          <h3 className="text-2xl font-semibold tracking-tight text-ink">
            {health?.neo4j.statistics?.node_count || 179}
          </h3>
          <span className="text-[10px] text-ink-subtle mt-2 block font-mono">Company registry</span>
        </div>

        <div className="p-6 bg-surface-1 border border-hairline rounded-lg">
          <span className="text-xs text-ink-subtle block mb-1">Relationships</span>
          <h3 className="text-2xl font-semibold tracking-tight text-ink">
            {health?.neo4j.statistics?.relationship_count || 452}
          </h3>
          <span className="text-[10px] text-ink-subtle mt-2 block font-mono">Wins / Shareholders</span>
        </div>

        <div className="p-6 bg-surface-1 border border-hairline rounded-lg">
          <span className="text-xs text-ink-subtle block mb-1">Local Disk Space</span>
          <h3 className="text-2xl font-semibold tracking-tight text-ink">
            {health?.system.disk ? `${health.system.disk.free_gb} GB Free` : "245 GB Free"}
          </h3>
          <span className="text-[10px] text-ink-subtle mt-2 block font-mono">
            {health?.system.disk ? `${health.system.disk.percent_used}% utilized` : "12% utilized"}
          </span>
        </div>
      </div>

      {/* Visual Analytics Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        <div className="p-6 bg-surface-1 border border-hairline rounded-lg">
          <h4 className="text-sm font-semibold mb-4 text-ink flex items-center gap-2">
            <Activity className="h-4 w-4 text-primary" /> Risk Profile Distribution
          </h4>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={riskDistribution}>
                <XAxis dataKey="name" stroke="#8a8f98" fontSize={11} tickLine={false} />
                <YAxis stroke="#8a8f98" fontSize={11} tickLine={false} />
                <Tooltip
                  contentStyle={{ backgroundColor: "#0f1011", borderColor: "#23252a", color: "#f7f8f8" }}
                />
                <Bar dataKey="value" fill="#5e6ad2" radius={[4, 4, 0, 0]}>
                  {riskDistribution.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="p-6 bg-surface-1 border border-hairline rounded-lg">
          <h4 className="text-sm font-semibold mb-4 text-ink flex items-center gap-2">
            <Database className="h-4 w-4 text-primary" /> Average System Risk Trend (By Quarter)
          </h4>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={historicalRisk}>
                <XAxis dataKey="name" stroke="#8a8f98" fontSize={11} tickLine={false} />
                <YAxis stroke="#8a8f98" fontSize={11} tickLine={false} />
                <Tooltip
                  contentStyle={{ backgroundColor: "#0f1011", borderColor: "#23252a", color: "#f7f8f8" }}
                />
                <defs>
                  <linearGradient id="riskGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#5e6ad2" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="#5e6ad2" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <Area type="monotone" dataKey="avgRisk" stroke="#5e6ad2" strokeWidth={2} fillOpacity={1} fill="url(#riskGrad)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Connection health */}
        <div className="lg:col-span-1 space-y-6">
          <div className="p-6 bg-surface-1 border border-hairline rounded-lg">
            <h4 className="text-sm font-semibold mb-4 text-ink flex items-center gap-2">
              <Database className="h-4 w-4 text-primary" /> Database Services
            </h4>
            <div className="space-y-3 text-sm">
              <div className="flex justify-between pb-2 border-b border-hairline/50">
                <span className="text-ink-subtle">Neo4j Status</span>
                <span className={`font-semibold ${health?.neo4j.status === "connected" ? "text-emerald-500" : "text-amber-500"}`}>
                  {health?.neo4j.status === "connected" ? "Connected" : "Simulated/Docker Down"}
                </span>
              </div>
              <div className="flex justify-between pb-2 border-b border-hairline/50 font-mono text-xs">
                <span className="text-ink-subtle">Bolt URI</span>
                <span>{health?.neo4j.uri || "bolt://localhost:7687"}</span>
              </div>
              <div className="flex justify-between pb-2 border-b border-hairline/50">
                <span className="text-ink-subtle">Python version</span>
                <span>{health?.system.python_version || "3.11+"}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-ink-subtle">Platform OS</span>
                <span className="capitalize">{health?.system.platform || "Windows Local"}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Clickable alerts feed */}
        <div className="lg:col-span-2 space-y-6">
          <div className="p-6 bg-surface-1 border border-hairline rounded-lg">
            <h4 className="text-sm font-semibold mb-4 text-ink flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-500" /> Active Risk Alerts (Fai click per ispezionare)
            </h4>
            <div className="space-y-3">
              {alerts.map((alert) => (
                <button
                  key={alert.id}
                  onClick={() => onSelectNode({
                    id: alert.entity_id,
                    nome_normalizzato: alert.alert_type === "tender_spike" ? "Bando Anomalo" : "Azienda Rilevata",
                    type: alert.alert_type === "tender_spike" ? "Tender" : "Company",
                    cf: alert.alert_type !== "tender_spike" ? alert.entity_id : undefined,
                    cig: alert.alert_type === "tender_spike" ? alert.entity_id : undefined,
                    risk_score: alert.new_value
                  })}
                  className="w-full text-left p-4 bg-surface-2 border border-hairline hover:border-primary/50 hover:bg-surface-3/30 rounded flex items-start justify-between transition-all duration-200"
                >
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`h-2 w-2 rounded-full ${alert.severity === "high" ? "bg-red-500" : "bg-amber-500"}`} />
                      <span className="text-xs font-mono font-semibold uppercase text-ink">
                        {alert.alert_type.replace(/_/g, " ")}
                      </span>
                    </div>
                    <p className="text-xs text-ink-subtle font-mono">
                      Target Entity ID: <span className="text-ink font-semibold">{alert.entity_id}</span>
                    </p>
                    {alert.delta && (
                      <p className="text-xs text-ink-subtle mt-1">
                        Shift: <span className="text-red-400 font-mono font-semibold">+{Math.round(alert.delta * 100)}% risk</span>
                      </p>
                    )}
                  </div>
                  <span className="text-[10px] text-ink-subtle font-mono">{new Date(alert.date_a).toLocaleDateString()}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// 2. RAG VIEW
// =============================================================================

function RAGView({ backendOffline, onSelectNode }: { backendOffline: boolean; onSelectNode: (node: GraphNode) => void }) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "1",
      sender: "agent",
      text: "Ciao! Sono Paladino GraphRAG Agent. Chiedimi qualsiasi cosa riguardante i contratti pubblici, le aziende o gli azionisti nel grafo."
    }
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [inspecting, setInspecting] = useState<ChatMessage | null>(null);

  const sendMessage = async () => {
    if (!input.trim() || loading) return;
    const userMsg: ChatMessage = { id: Date.now().toString(), sender: "user", text: input };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    if (backendOffline) {
      setTimeout(() => {
        const reply: ChatMessage = {
          id: (Date.now() + 1).toString(),
          sender: "agent",
          text: "Ho cercato nel Knowledge Graph locale. L'azienda 'ACME SRL' ha vinto l'appalto CIG 'Z123456789' con un livello di confidenza derivata pari al 92%. L'analisi evidenzia una potenziale connessione implicita (regione comune e azionista condiviso) con un'azienda offshore.",
          cypher: "MATCH (c:Company {cf: '02394850119'})-[:WINS]->(t:Tender)\nRETURN c.nome_normalizzato, t.title, t.cig LIMIT 10",
          executionTimeMs: 84,
          sources: ["ANAC", "Registro Imprese", "MergeRollback Note"]
        };
        setMessages((prev) => [...prev, reply]);
        setLoading(false);
      }, 1000);
      return;
    }

    try {
      const res = await fetch("/api/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: input, limit: 10 })
      });
      if (res.ok) {
        const data = await res.json();
        const reply: ChatMessage = {
          id: (Date.now() + 1).toString(),
          sender: "agent",
          text: data.results && data.results.length > 0 
            ? `Ho completato l'interrogazione GraphRAG. Trovati ${data.count} record collegati. Ecco un estratto:` + "\n\n" + JSON.stringify(data.results.slice(0, 3), null, 2)
            : "Nessun record collegato trovato per la query.",
          cypher: data.cypher || "MATCH (n) RETURN n LIMIT 10",
          executionTimeMs: 45
        };
        setMessages((prev) => [...prev, reply]);
      } else {
        throw new Error();
      }
    } catch {
      setMessages((prev) => [
        ...prev,
        { id: Date.now().toString(), sender: "agent", text: "Errore durante il recupero dei dati dal server locale." }
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-[calc(100vh-140px)] gap-6 animate-fadeIn">
      <div className="flex-1 flex flex-col bg-surface-1 border border-hairline rounded-lg overflow-hidden">
        <div className="flex-1 p-6 overflow-y-auto space-y-4">
          {messages.map((msg) => (
            <div key={msg.id} className={`flex ${msg.sender === "user" ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[70%] p-4 rounded-lg text-sm relative group ${
                  msg.sender === "user"
                    ? "bg-primary text-on-primary rounded-br-none"
                    : "bg-surface-2 border border-hairline text-ink rounded-bl-none"
                }`}
              >
                <p className="whitespace-pre-wrap leading-relaxed">{msg.text}</p>
                {msg.sender === "agent" && (
                  <div className="mt-3 pt-2 border-t border-hairline/25 flex items-center justify-between text-[10px] text-ink-subtle">
                    <span className="font-mono">Fonte: GraphRAG Agent</span>
                    <button
                      onClick={() => onSelectNode({ id: "c_101", nome_normalizzato: "ACME SRL", type: "Company", cf: "02394850119", risk_score: 0.74 })}
                      className="text-primary hover:underline flex items-center gap-1 font-semibold"
                    >
                      Dettaglio ACME SRL <ChevronDown className="h-3 w-3 -rotate-90" />
                    </button>
                  </div>
                )}
                {msg.cypher && (
                  <button
                    onClick={() => setInspecting(msg)}
                    className="absolute right-2 top-2 p-1.5 rounded bg-surface-1 border border-hairline text-ink-subtle hover:text-ink opacity-0 group-hover:opacity-100 transition-all duration-200"
                    title="Inspect Cypher"
                  >
                    <Code className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
            </div>
          ))}
          {loading && (
            <div className="flex justify-start">
              <div className="bg-surface-2 border border-hairline p-4 rounded-lg rounded-bl-none text-ink flex items-center gap-2.5">
                <span className="h-1.5 w-1.5 bg-primary rounded-full animate-pulse" />
                <span className="h-1.5 w-1.5 bg-primary rounded-full animate-pulse delay-75" />
                <span className="h-1.5 w-1.5 bg-primary rounded-full animate-pulse delay-150" />
              </div>
            </div>
          )}
        </div>

        <div className="p-4 border-t border-hairline bg-surface-2/20 flex gap-3">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && sendMessage()}
            placeholder="Chiedi qualcosa (es. 'Mostra le aziende con alto rischio in Lombardia')"
            className="flex-1 px-4 py-2.5 rounded bg-surface-1 border border-hairline text-sm text-ink placeholder-ink-subtle/60 focus:outline-none focus:border-primary transition-all duration-200"
          />
          <button
            onClick={sendMessage}
            disabled={loading}
            className="px-4 py-2.5 rounded bg-primary text-on-primary text-sm font-semibold hover:bg-primary-hover active:bg-primary-focus disabled:opacity-50 flex items-center justify-center gap-2 transition-all duration-200 shadow-md shadow-primary/20"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="w-80 flex flex-col bg-surface-1 border border-hairline rounded-lg p-6">
        <h4 className="text-sm font-semibold mb-4 text-ink flex items-center gap-2">
          <Code className="h-4 w-4 text-primary" /> Query Inspector
        </h4>
        {inspecting ? (
          <div className="space-y-6 flex-1 flex flex-col justify-between overflow-hidden">
            <div className="space-y-4 overflow-y-auto pr-1">
              <div>
                <span className="text-[10px] text-ink-subtle uppercase block mb-1 font-mono">Generated Cypher</span>
                <pre className="p-3 bg-canvas border border-hairline rounded text-xs font-mono text-emerald-400 overflow-x-auto whitespace-pre-wrap leading-normal">
                  {inspecting.cypher}
                </pre>
              </div>
              {inspecting.executionTimeMs && (
                <div className="flex justify-between items-center text-xs">
                  <span className="text-ink-subtle">Execution Time:</span>
                  <span className="font-mono font-semibold text-ink">{inspecting.executionTimeMs} ms</span>
                </div>
              )}
              {inspecting.sources && (
                <div>
                  <span className="text-[10px] text-ink-subtle uppercase block mb-1 font-mono">Sources Queried</span>
                  <div className="flex flex-wrap gap-1.5">
                    {inspecting.sources.map((s, idx) => (
                      <span key={idx} className="px-2 py-0.5 bg-surface-2 border border-hairline rounded text-[11px] font-mono text-ink-muted">
                        {s}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
            <button
              onClick={() => setInspecting(null)}
              className="w-full py-2 bg-surface-2 border border-hairline hover:bg-surface-3 text-xs rounded text-ink transition-colors duration-200"
            >
              Clear Inspector
            </button>
          </div>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-center text-ink-subtle">
            <HelpCircle className="h-8 w-8 mb-2 opacity-40" />
            <p className="text-xs max-w-[200px]">Invia una domanda e fai clic sul tasto codice per ispezionare il grafo qui.</p>
          </div>
        )}
      </div>
    </div>
  );
}

// =============================================================================
// 3. GRAPH EXPLORER VIEW (Using ForceGraph2D)
// =============================================================================

function GraphView({ backendOffline, onSelectNode }: { backendOffline: boolean; onSelectNode: (node: GraphNode) => void }) {
  const [searchId, setSearchId] = useState("");
  const [loading, setLoading] = useState(false);

  const [graphData, setGraphData] = useState<GraphData>({
    nodes: [
      { id: "c_101", label: "Company", nome_normalizzato: "ACME SRL", cf: "02394850119", risk_score: 0.74, color: "#ef4444", val: 12 },
      { id: "t_201", label: "Tender", title: "Appalto Manutenzione Strade", cig: "Z123456789", risk_score: 0.2, color: "#5e6ad2", val: 8 },
      { id: "p_301", label: "Person", name: "Mario Rossi", cf: "RSSMRA70A01F205F", risk_score: 0.45, color: "#f59e0b", val: 6 },
      { id: "c_103", label: "Company", nome_normalizzato: "Offshore Holdings Ltd", cf: "999888777", risk_score: 0.95, color: "#ef4444", val: 14 }
    ],
    links: [
      { id: "e1", source: "c_101", target: "t_201", type: "WINS" },
      { id: "e2", source: "p_301", target: "c_101", type: "SHAREHOLDER" },
      { id: "e3", source: "p_301", target: "c_103", type: "SHAREHOLDER" }
    ]
  });

  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 600, height: 400 });

  useEffect(() => {
    if (!containerRef.current) return;
    const resizeObserver = new ResizeObserver((entries) => {
      for (let entry of entries) {
        const { width, height } = entry.contentRect;
        setDimensions({ width, height: Math.max(height, 350) });
      }
    });
    resizeObserver.observe(containerRef.current);
    return () => resizeObserver.disconnect();
  }, []);

  const handleSearch = async () => {
    if (!searchId.trim()) return;
    setLoading(true);

    if (backendOffline) {
      setTimeout(() => {
        const newNodeId = `c_${Date.now()}`;
        const newNodes = [
          ...graphData.nodes,
          { id: newNodeId, label: "Company", nome_normalizzato: `Azienda Correlata ${searchId.substring(0, 3)}`, cf: `CF${Date.now()}`, risk_score: 0.35, color: "#10b981", val: 10 }
        ];
        const newLinks = [
          ...graphData.links,
          { id: `e_${Date.now()}`, source: "c_101", target: newNodeId, type: "PARTNERSHIP" }
        ];
        setGraphData({ nodes: newNodes, links: newLinks });
        setLoading(false);
      }, 1000);
      return;
    }

    try {
      const res = await fetch(`/api/graph/entity/${searchId}?depth=2&style_by_risk=true`);
      if (res.ok) {
        const data = await res.json();
        const formattedLinks = data.edges.map((e: any) => ({
          id: e.id,
          source: e.source,
          target: e.target,
          type: e.type
        }));
        const formattedNodes = data.nodes.map((n: any) => ({
          ...n,
          val: n.size || 10
        }));
        setGraphData({ nodes: formattedNodes, links: formattedLinks });
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="h-[calc(100vh-140px)] flex flex-col bg-surface-1 border border-hairline rounded-lg overflow-hidden animate-fadeIn">
      {/* Graph Filters/Search bar */}
      <div className="p-4 border-b border-hairline bg-surface-2/30 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3 w-full sm:w-96">
          <input
            type="text"
            value={searchId}
            onChange={(e) => setSearchId(e.target.value)}
            placeholder="Espandi nodo per ID (es. c_101)"
            className="flex-1 px-3 py-1.5 bg-surface-1 border border-hairline text-xs rounded text-ink focus:outline-none focus:border-primary"
          />
          <button
            onClick={handleSearch}
            disabled={loading}
            className="px-3 py-1.5 bg-primary hover:bg-primary-hover active:bg-primary-focus rounded text-on-primary text-xs font-semibold flex-shrink-0"
          >
            {loading ? "Espansione..." : "Cerca & Espandi"}
          </button>
        </div>
        <div className="flex flex-wrap gap-4 text-xs font-mono">
          <div className="flex items-center gap-1.5">
            <span className="h-3 w-3 rounded-full bg-red-500" /> <span>Alto Rischio</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="h-3 w-3 rounded-full bg-amber-500" /> <span>Medio Rischio</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="h-3 w-3 rounded-full bg-[#5e6ad2]" /> <span>Bandi/Appalti</span>
          </div>
        </div>
      </div>

      {/* Force-directed Canvas container */}
      <div ref={containerRef} className="flex-1 relative bg-canvas/30 w-full h-full min-h-[350px]">
        <ForceGraph2D
          graphData={graphData}
          nodeLabel={(n: any) => n.nome_normalizzato || n.name || n.title || n.id}
          nodeColor={(n: any) => n.color}
          nodeVal={(n: any) => n.val || 8}
          linkColor={() => "#34343a"}
          linkDirectionalArrowLength={4}
          linkDirectionalArrowRelPos={1}
          onNodeClick={(node: any) => onSelectNode(node)}
          width={dimensions.width}
          height={dimensions.height}
        />
        <div className="absolute bottom-4 left-4 p-3 bg-surface-1 border border-hairline rounded text-xs text-ink-subtle max-w-[calc(100%-2rem)]">
          💡 Fai click su un nodo per visualizzare le relazioni e i dettagli dell'investigazione.
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// 4. ENTITY RESOLVER VIEW (With Merge History & Rollback)
// =============================================================================

function ResolverView({ backendOffline }: { backendOffline: boolean }) {
  const [candidates, setCandidates] = useState<DuplicateCandidate[]>([
    { entity_id: "c_101", cf: "02394850119", nome_normalizzato: "ACME SRL", similarity_score: 0.94, match_reason: "fuzzy_name_match", properties: { regione: "Lombardia" } },
    { entity_id: "c_102", cf: "02394850119", nome_normalizzato: "ACME S.R.L.", similarity_score: 0.94, match_reason: "exact_cf_match", properties: { regione: "Lombardia" } }
  ]);
  const [searchEntityId, setSearchEntityId] = useState("c_101");
  const [targetId, setTargetId] = useState("c_101");
  const [sourceIds, setSourceIds] = useState<string[]>(["c_102"]);
  const [processing, setProcessing] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  // Local storage based history tracker
  const [merges, setMerges] = useState<MergeHistoryItem[]>([]);

  const fetchDuplicates = async () => {
    if (!searchEntityId.trim() || backendOffline) return;
    setProcessing(true);
    setMessage(null);
    try {
      const res = await fetch("/api/companies/duplicates", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entity_id: searchEntityId.trim(), limit: 10, min_similarity: 0.75 })
      });
      if (res.ok) {
        const data = await res.json();
        if (data && data.length > 1) {
          setCandidates(data);
          setTargetId(data[0].entity_id);
          setSourceIds(data.slice(1).map((c: any) => c.entity_id));
        } else {
          setMessage({ type: "error", text: "Nessun duplicato candidato trovato per questo ID." });
        }
      } else {
        const err = await res.json();
        setMessage({ type: "error", text: `Errore: ${err.detail || "Impossibile recuperare duplicati."}` });
      }
    } catch {
      setMessage({ type: "error", text: "Errore di connessione con il servizio duplicati." });
    } finally {
      setProcessing(false);
    }
  };

  useEffect(() => {
    const fetchHistory = async () => {
      if (backendOffline) {
        const saved = localStorage.getItem("paladino_merges");
        if (saved) setMerges(JSON.parse(saved));
        return;
      }
      try {
        const res = await fetch("/api/companies/merge/history?limit=20");
        if (res.ok) {
          const data = await res.json();
          if (data.merges) {
            setMerges(data.merges);
          }
        }
      } catch (e) {
        console.error("Failed to load merge history:", e);
      }
    };
    fetchHistory();
  }, [backendOffline]);

  const executeMerge = async () => {
    setProcessing(true);
    setMessage(null);

    const rollbackId = `merge_${Date.now()}`;
    const newHistory: MergeHistoryItem = {
      id: Date.now().toString(),
      timestamp: new Date().toLocaleString(),
      target_id: targetId,
      source_id: sourceIds[0],
      rollback_id: rollbackId,
      operator: "Admin Local"
    };

    if (backendOffline) {
      setTimeout(() => {
        setMessage({
          type: "success",
          text: `Unione completata correttamente (Simulazione). Rollback snapshot registrato con ID: ${rollbackId}`
        });
        const updated = [newHistory, ...merges];
        setMerges(updated);
        localStorage.setItem("paladino_merges", JSON.stringify(updated));
        setProcessing(false);
      }, 1200);
      return;
    }

    try {
      const res = await fetch("/api/companies/merge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_ids: sourceIds,
          target_id: targetId,
          dry_run: false
        })
      });
      if (res.ok) {
        const data = await res.json();
        setMessage({
          type: "success",
          text: `Merge completato! Nodi fusi: ${data.merged_count}, Relazioni riassegnate: ${data.relationships_updated}. Rollback ID: ${data.rollback_id}`
        });
        const updated = [{ ...newHistory, rollback_id: data.rollback_id }, ...merges];
        setMerges(updated);
        localStorage.setItem("paladino_merges", JSON.stringify(updated));
      } else {
        const err = await res.json();
        setMessage({ type: "error", text: `Errore: ${err.detail || "Merge fallito"}` });
      }
    } catch {
      setMessage({ type: "error", text: "Errore di rete durante il merge." });
    } finally {
      setProcessing(false);
    }
  };

  const rollbackMerge = async (historyId: string, rollbackId: string) => {
    setMessage(null);
    if (backendOffline) {
      setMessage({
        type: "success",
        text: `Ripristino simulato completato per il snapshot: ${rollbackId}. Le entità e i commenti originari sono stati ripristinati.`
      });
      const updated = merges.filter((m) => m.id !== historyId);
      setMerges(updated);
      localStorage.setItem("paladino_merges", JSON.stringify(updated));
      return;
    }

    try {
      const res = await fetch(`/api/companies/merge/rollback?rollback_id=${rollbackId}`, {
        method: "POST"
      });
      if (res.ok) {
        setMessage({
          type: "success",
          text: `Rollback completato con successo sul database Neo4j. Snapshots ripristinati correttamente.`
        });
        const updated = merges.filter((m) => m.id !== historyId);
        setMerges(updated);
        localStorage.setItem("paladino_merges", JSON.stringify(updated));
      } else {
        const err = await res.json();
        setMessage({ type: "error", text: `Ripristino fallito: ${err.detail}` });
      }
    } catch {
      setMessage({ type: "error", text: "Errore di connessione." });
    }
  };

  return (
    <div className="space-y-8 animate-fadeIn">
      {message && (
        <div className={`p-4 rounded-md border text-sm flex items-center gap-3 ${
          message.type === "success" 
            ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400" 
            : "bg-red-500/10 border-red-500/30 text-red-400"
        }`}>
          <CheckCircle className="h-5 w-5 flex-shrink-0" />
          <p>{message.text}</p>
        </div>
      )}

      {/* Duplicate Candidates Search Control */}
      <div className="p-6 bg-surface-1 border border-hairline rounded-lg flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h4 className="text-sm font-semibold text-ink">Trova Duplicati nel Grafo</h4>
          <p className="text-xs text-ink-subtle mt-0.5">Inserisci l'ID di un'azienda per scovare possibili duplicati da fondere tramite l'algoritmo fuzzy.</p>
        </div>
        <div className="flex gap-2 w-full sm:w-auto">
          <input
            type="text"
            value={searchEntityId}
            onChange={(e) => setSearchEntityId(e.target.value)}
            placeholder="es. c_101 o c_102"
            className="flex-1 sm:w-64 px-3 py-1.5 bg-surface-2 border border-hairline text-xs rounded text-ink focus:outline-none focus:border-primary font-mono"
          />
          <button
            onClick={fetchDuplicates}
            disabled={processing}
            className="px-3.5 py-1.5 bg-primary hover:bg-primary-hover active:bg-primary-focus rounded text-on-primary text-xs font-semibold flex-shrink-0 transition-colors"
          >
            Cerca
          </button>
        </div>
      </div>

      {/* Candidates comparison */}
      {candidates.length >= 2 ? (
        <div className="space-y-8">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            <div className="p-6 bg-surface-1 border border-hairline rounded-lg relative">
              <span className="absolute top-4 right-4 px-2 py-0.5 bg-primary/20 border border-primary/30 rounded text-[10px] uppercase font-semibold text-primary">
                Surviving Entity
              </span>
              <h4 className="text-sm font-semibold mb-6 text-ink">Entity A (Target)</h4>
              <div className="space-y-4">
                <div>
                  <span className="text-[10px] text-ink-subtle uppercase font-mono block">Nome Normalizzato</span>
                  <span className="text-sm font-semibold text-ink">{candidates[0].nome_normalizzato}</span>
                </div>
                <div>
                  <span className="text-[10px] text-ink-subtle uppercase font-mono block">Codice Fiscale (CF)</span>
                  <span className="text-sm font-mono font-semibold text-ink">{candidates[0].cf}</span>
                </div>
                <div>
                  <span className="text-[10px] text-ink-subtle uppercase font-mono block">Regione</span>
                  <span className="text-sm text-ink">{candidates[0].properties?.regione || "Lombardia"}</span>
                </div>
              </div>
            </div>

            <div className="p-6 bg-surface-1 border border-hairline rounded-lg relative">
              <span className="absolute top-4 right-4 px-2 py-0.5 bg-amber-500/20 border border-amber-500/30 rounded text-[10px] uppercase font-semibold text-amber-500">
                Merged Entity
              </span>
              <h4 className="text-sm font-semibold mb-6 text-ink">Entity B (Source)</h4>
              <div className="space-y-4">
                <div>
                  <span className="text-[10px] text-ink-subtle uppercase font-mono block">Nome Normalizzato</span>
                  <span className="text-sm font-semibold text-ink">{candidates[1].nome_normalizzato}</span>
                </div>
                <div>
                  <span className="text-[10px] text-ink-subtle uppercase font-mono block">Codice Fiscale (CF)</span>
                  <span className="text-sm font-mono font-semibold text-ink">{candidates[1].cf}</span>
                </div>
                <div>
                  <span className="text-[10px] text-ink-subtle uppercase font-mono block">Regione</span>
                  <span className="text-sm text-ink">{candidates[1].properties?.regione || "Lombardia"}</span>
                </div>
              </div>
            </div>
          </div>

          <div className="p-6 bg-surface-1 border border-hairline rounded-lg flex items-center justify-between">
            <div>
              <h5 className="text-sm font-semibold mb-1 text-ink">Risolvi e unisci i duplicati</h5>
              <p className="text-xs text-ink-subtle">
                Sarà registrata una traccia di rollback nei nodi `:MergeRollback` in caso si debba ripristinare in futuro.
              </p>
            </div>
            <button
              onClick={executeMerge}
              disabled={processing}
              className="px-5 py-2.5 bg-primary text-on-primary hover:bg-primary-hover active:bg-primary-focus rounded font-semibold text-sm transition-all duration-200 shadow-md shadow-primary/20 disabled:opacity-50"
            >
              {processing ? "Unione in corso..." : "Esegui Merge Nodi"}
            </button>
          </div>
        </div>
      ) : (
        <div className="p-8 bg-surface-1 border border-hairline rounded-lg text-center text-ink-subtle text-xs">
          Cerca un ID azienda per caricare e confrontare i duplicati trovati dall'algoritmo.
        </div>
      )}

      {/* Fusioni Recenti / Rollback Table */}
      <div className="p-6 bg-surface-1 border border-hairline rounded-lg">
        <h4 className="text-sm font-semibold mb-4 text-ink flex items-center gap-2">
          <GitFork className="h-4 w-4 text-primary" /> Registro Fusioni Recenti
        </h4>
        {merges.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs font-mono">
              <thead>
                <tr className="border-b border-hairline text-ink-subtle">
                  <th className="py-2">Data/Ora</th>
                  <th className="py-2">Target ID</th>
                  <th className="py-2">Source ID</th>
                  <th className="py-2">Rollback ID</th>
                  <th className="py-2 text-right">Azione</th>
                </tr>
              </thead>
              <tbody>
                {merges.map((merge) => (
                  <tr key={merge.id} className="border-b border-hairline/50 hover:bg-surface-2/20">
                    <td className="py-2.5 text-ink">{merge.timestamp}</td>
                    <td className="py-2.5 text-primary">{merge.target_id}</td>
                    <td className="py-2.5 text-amber-500">{merge.source_id}</td>
                    <td className="py-2.5 text-ink-subtle">{merge.rollback_id}</td>
                    <td className="py-2.5 text-right">
                      <button
                        onClick={() => rollbackMerge(merge.id, merge.rollback_id)}
                        className="px-2.5 py-1 bg-surface-2 hover:bg-red-950/20 hover:text-red-400 hover:border-red-500/30 border border-hairline text-[11px] font-semibold text-ink-muted rounded transition-all"
                      >
                        Rollback
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="text-center py-6 text-ink-subtle text-xs">
            Nessuna fusione registrata in questa sessione locale.
          </div>
        )}
      </div>
    </div>
  );
}

// =============================================================================
// 5. INGESTION HUB (With CSV Validator Grid & Bulk Ingestion)
// =============================================================================

function IngestView({ backendOffline, onIngestStateChange }: { backendOffline: boolean; onIngestStateChange: (running: boolean) => void }) {
  const [source, setSource] = useState("");
  const [ingesting, setIngesting] = useState(false);
  const [result, setResult] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);

  // CSV Dynamic Ontology States
  const [validations, setValidations] = useState<CSVRowValidation[]>([]);
  const [csvHeaders, setCsvHeaders] = useState<string[]>([]);
  const [primaryKey, setPrimaryKey] = useState("");
  const [csvPreviewRows, setCsvPreviewRows] = useState<any[]>([]);
  const [targetType, setTargetType] = useState<"company" | "tender" | "person" | "custom">("company");
  const [customLabel, setCustomLabel] = useState("BankAccount");
  const [datasetVersion, setDatasetVersion] = useState("v1.0.0");
  const [ingestSourceParam, setIngestSourceParam] = useState("BULK_IMPORT");
  const [confidence, setConfidence] = useState(1.0);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Sync ingestion state with global UI overlay lock
  useEffect(() => {
    onIngestStateChange(ingesting);
  }, [ingesting, onIngestStateChange]);

  const handleIngest = async () => {
    if (!source.trim() || ingesting) return;
    setIngesting(true);
    setResult(null);
    setError(null);

    if (backendOffline) {
      setTimeout(() => {
        setResult({
          source: source,
          entities_extracted: 8,
          entities_matched: 5,
          entities_created: 3,
          relationships_created: 12,
          implicit_connections_found: 2,
          warnings: ["Simulazione completata. Nessun warning registrato."]
        });
        setIngesting(false);
      }, 1200);
      return;
    }

    try {
      const res = await fetch("/api/ingest/unstructured", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: source, resolve_connections: true })
      });
      if (res.ok) {
        const data = await res.json();
        setResult(data);
      } else {
        const err = await res.json();
        setError(err.detail || "Ingest fallito.");
      }
    } catch {
      setError("Errore di comunicazione col backend.");
    } finally {
      setIngesting(false);
    }
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setError(null);
    setResult(null);

    // Limit file size to 10MB to protect memory
    if (file.size > 10 * 1024 * 1024) {
      setError("File troppo grande per il caricamento diretto via browser (>10MB). Per dataset massivi (fino a decine di GB), copia il file nella cartella 'import/' di Neo4j e avvia l'importazione in streaming a blocchi dalla scheda 'Notebooks' usando il comando LOAD CSV.");
      return;
    }

    const reader = new FileReader();
    reader.onload = (event) => {
      const text = event.target?.result as string;
      const lines = text.split("\n").filter(l => l.trim()).length;

      // Limit row count to 10k to prevent database timeouts
      if (lines > 10001) {
        setError(`Il file contiene ${lines.toLocaleString()} righe, superando il limite di sicurezza del browser (10.000 righe). Per importare milioni di righe (decined di GB) stabilmente, copia il file nella cartella 'import/' del database e avvia il caricamento in streaming dalla scheda 'Notebooks' usando il comando LOAD CSV.`);
        return;
      }

      parseCSV(text);
    };
    reader.readAsText(file);
  };

  const parseCSV = (text: string) => {
    const lines = text.split("\n").map(l => l.trim()).filter(Boolean);
    if (lines.length < 2) return;

    let separator = ",";
    if (lines[0].includes(";")) separator = ";";

    const headers = lines[0].split(separator).map(h => h.trim().replace(/^"|"$/g, ""));
    setCsvHeaders(headers);

    const rows: any[] = [];
    const parsedValidations: CSVRowValidation[] = [];

    // Determine initial primary key
    let pk = headers[0];
    if (targetType === "company" || targetType === "person") {
      pk = headers.includes("cf") ? "cf" : headers[0];
    } else if (targetType === "tender") {
      pk = headers.includes("cig") ? "cig" : headers[0];
    }
    setPrimaryKey(pk);

    for (let i = 1; i < lines.length; i++) {
      const cols = lines[i].split(separator).map(c => c.trim().replace(/^"|"$/g, ""));
      const rowDict: any = {};
      headers.forEach((h, idx) => {
        rowDict[h] = cols[idx] || "";
      });
      rows.push(rowDict);

      const errors: string[] = [];
      const cf = rowDict["cf"] || "";
      const cig = rowDict["cig"] || "";
      const name = rowDict["name"] || rowDict["title"] || "";
      const title = rowDict["title"] || rowDict["name"] || "";

      if (targetType === "company" || targetType === "person") {
        if (!cf) {
          errors.push("Codice Fiscale mancante");
        } else if (cf.length !== 11 && cf.length !== 16) {
          errors.push(`CF non valido: lunghezza errata (${cf.length})`);
        }
      } else if (targetType === "tender") {
        if (!cig) {
          errors.push("CIG mancante");
        } else if (cig.length !== 10) {
          errors.push(`CIG non valido: lunghezza errata (${cig.length})`);
        }
      } else {
        const pkValue = rowDict[pk] || "";
        if (!pkValue) {
          errors.push(`Chiave primaria '${pk}' mancante o vuota`);
        }
      }

      parsedValidations.push({
        rowIdx: i,
        cf,
        name: name || title,
        cig,
        title: title || name,
        isValid: errors.length === 0,
        errors
      });
    }

    setCsvPreviewRows(rows);
    setValidations(parsedValidations);
  };

  const revalidateCSV = (newPk: string) => {
    if (csvPreviewRows.length === 0) return;
    const updated = validations.map((v) => {
      const rowDict = csvPreviewRows[v.rowIdx - 1];
      const errors: string[] = [];
      const cf = rowDict["cf"] || "";
      const cig = rowDict["cig"] || "";

      if (targetType === "company" || targetType === "person") {
        if (!cf) errors.push("Codice Fiscale mancante");
        else if (cf.length !== 11 && cf.length !== 16) errors.push(`CF non valido: lunghezza (${cf.length})`);
      } else if (targetType === "tender") {
        if (!cig) errors.push("CIG mancante");
        else if (cig.length !== 10) errors.push(`CIG non valido: lunghezza (${cig.length})`);
      } else {
        const pkValue = rowDict[newPk] || "";
        if (!pkValue) errors.push(`Chiave primaria '${newPk}' mancante o vuota`);
      }
      return {
        ...v,
        isValid: errors.length === 0,
        errors
      };
    });
    setValidations(updated);
  };

  const executeBulkIngest = async () => {
    const validRows = validations.filter(v => v.isValid).map(v => csvPreviewRows[v.rowIdx - 1]);
    if (validRows.length === 0) return;

    setIngesting(true);
    setError(null);
    setResult(null);

    const actualLabel = targetType === "custom" ? customLabel : targetType;

    if (backendOffline) {
      setTimeout(() => {
        setResult({
          entities_extracted: validRows.length,
          entities_matched: Math.round(validRows.length * 0.6),
          entities_created: Math.round(validRows.length * 0.4),
          relationships_created: validRows.length * 2,
          implicit_connections_found: 0,
          warnings: [`Importazione di ${actualLabel} completata in simulazione. Chiave primaria utilizzata: '${primaryKey}'`]
        });
        setIngesting(false);
        setValidations([]);
        setCsvHeaders([]);
      }, 1500);
      return;
    }

    try {
      // Re-package parsed data as a CSV Blob
      const csvHeaderString = csvHeaders.join(",");
      const csvRowStrings = validRows.map((rowDict) =>
        csvHeaders.map((h) => JSON.stringify(rowDict[h] || "")).join(",")
      );
      const csvContent = [csvHeaderString, ...csvRowStrings].join("\n");
      const blob = new Blob([csvContent], { type: "text/csv" });

      const formData = new FormData();
      formData.append("file", blob, "upload.csv");
      formData.append("target", actualLabel);
      formData.append("dry_run", "false");
      formData.append("max_rows", "1000");
      if (targetType === "custom") {
        formData.append("primary_key", primaryKey);
      }

      const res = await fetch("/api/ingest/bulk", {
        method: "POST",
        body: formData
      });

      if (res.ok) {
        const data = await res.json();
        setResult({
          entities_extracted: data.processed_count,
          entities_matched: data.merged_count || 0,
          entities_created: data.created_count || 0,
          relationships_created: (data.created_count || 0) * 2,
          implicit_connections_found: 0,
          warnings: data.errors
        });
        setValidations([]);
        setCsvHeaders([]);
      } else {
        const err = await res.json();
        setError(err.detail || "Bulk import fallito.");
      }
    } catch {
      setError("Errore di connessione.");
    } finally {
      setIngesting(false);
    }
  };

  const loadSampleCSV = () => {
    let csvContent = "";
    if (targetType === "company") {
      csvContent = "cf,name\n02394850119,ACME SRL\n12345,INVALID CF\n08234850152,BETA COOP";
    } else if (targetType === "tender") {
      csvContent = "cig,title\nZ123456789,Appalto Strade\n9999,INVALID CIG\nA01B02C03D,Servizi IT";
    } else if (targetType === "person") {
      csvContent = "cf,name\nRSSMRA70A01F205F,Mario Rossi\n123,INVALID PERSON CF\nBRNLCU80B02F205E,Luca Bruno";
    } else {
      csvContent = "iban,titolare,saldo\nIT12A0123456789012345678901,ACME SRL,124000.0\n,EMPTY IBAN,0.0\nIT99X0987654321098765432109,Mario Rossi,4500.0";
    }
    parseCSV(csvContent);
  };

  const handleTargetChange = (val: any) => {
    setTargetType(val);
    setValidations([]);
    setCsvHeaders([]);
    setCsvPreviewRows([]);
  };

  return (
    <div className="space-y-8 animate-fadeIn">
      {/* Unstructured Ingest */}
      <div className="p-6 bg-surface-1 border border-hairline rounded-lg">
        <h4 className="text-sm font-semibold mb-4 text-ink flex items-center gap-2">
          <FileText className="h-4 w-4 text-primary" /> Caricamento Documenti Singoli
        </h4>
        <p className="text-xs text-ink-subtle mb-4">
          Fornisci un percorso locale o un link web. I dati estratti verranno strutturati in entità e inseriti nel grafo.
        </p>
        <div className="flex gap-4">
          <input
            type="text"
            value={source}
            onChange={(e) => setSource(e.target.value)}
            placeholder="es. D:\Desktop\paladino\data\campioni\delibera.pdf o https://www.anac.it/... "
            className="flex-1 px-4 py-2.5 rounded bg-surface-2 border border-hairline text-sm text-ink placeholder-ink-subtle/50 focus:outline-none focus:border-primary transition-all duration-200"
          />
          <button
            onClick={handleIngest}
            disabled={ingesting}
            className="px-5 py-2.5 bg-primary text-on-primary hover:bg-primary-hover active:bg-primary-focus rounded font-semibold text-sm transition-all duration-200 shadow-md shadow-primary/20"
          >
            {ingesting ? "Elaborazione..." : "Esegui Ingest"}
          </button>
        </div>
      </div>

      {/* CSV Bulk Ingestion */}
      <div className="p-6 bg-surface-1 border border-hairline rounded-lg space-y-6">
        <div className="flex justify-between items-start">
          <div>
            <h4 className="text-sm font-semibold text-ink flex items-center gap-2">
              <FileSpreadsheet className="h-4 w-4 text-primary" /> Importazione Massiva CSV / Excel
            </h4>
            <p className="text-xs text-ink-subtle mt-1">
              Trascina o carica un file CSV per validare la correttezza dei campi prima del caricamento in batch su Neo4j.
            </p>
          </div>
          <button
            onClick={loadSampleCSV}
            className="px-3 py-1.5 bg-surface-2 border border-hairline hover:bg-surface-3 text-xs text-ink-muted rounded font-semibold"
          >
            Carica Esempio Muck
          </button>
        </div>

        {/* Configuration settings */}
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-6 gap-4">
          <div>
            <label className="text-[10px] text-ink-subtle uppercase font-mono block mb-1">Target Node</label>
            <select
              value={targetType}
              onChange={(e) => handleTargetChange(e.target.value as any)}
              className="w-full p-2 bg-surface-2 border border-hairline text-xs rounded text-ink"
            >
              <option value="company">Company</option>
              <option value="tender">Tender</option>
              <option value="person">Person</option>
              <option value="custom">Custom Label...</option>
            </select>
          </div>

          {targetType === "custom" && (
            <div>
              <label className="text-[10px] text-ink-subtle uppercase font-mono block mb-1">Nome Etichetta</label>
              <input
                type="text"
                value={customLabel}
                onChange={(e) => setCustomLabel(e.target.value)}
                placeholder="es. BankAccount"
                className="w-full p-2 bg-surface-2 border border-hairline text-xs rounded text-ink font-mono"
              />
            </div>
          )}

          {csvHeaders.length > 0 && (
            <div>
              <label className="text-[10px] text-ink-subtle uppercase font-mono block mb-1">Chiave Primaria</label>
              <select
                value={primaryKey}
                onChange={(e) => {
                  setPrimaryKey(e.target.value);
                  revalidateCSV(e.target.value);
                }}
                className="w-full p-2 bg-surface-2 border border-hairline text-xs rounded text-ink font-mono"
              >
                {csvHeaders.map(h => (
                  <option key={h} value={h}>{h}</option>
                ))}
              </select>
            </div>
          )}

          <div>
            <label className="text-[10px] text-ink-subtle uppercase font-mono block mb-1">Sorgente</label>
            <input
              type="text"
              value={ingestSourceParam}
              onChange={(e) => setIngestSourceParam(e.target.value)}
              className="w-full p-2 bg-surface-2 border border-hairline text-xs rounded text-ink font-mono"
            />
          </div>
          <div>
            <label className="text-[10px] text-ink-subtle uppercase font-mono block mb-1">Versione Dataset</label>
            <input
              type="text"
              value={datasetVersion}
              onChange={(e) => setDatasetVersion(e.target.value)}
              className="w-full p-2 bg-surface-2 border border-hairline text-xs rounded text-ink font-mono"
            />
          </div>
          <div>
            <label className="text-[10px] text-ink-subtle uppercase font-mono block mb-1">Confidenza Spend</label>
            <input
              type="number"
              step="0.1"
              max="1.0"
              value={confidence}
              onChange={(e) => setConfidence(parseFloat(e.target.value))}
              className="w-full p-2 bg-surface-2 border border-hairline text-xs rounded text-ink font-mono"
            />
          </div>
          <div className="flex items-end">
            <button
              onClick={() => fileInputRef.current?.click()}
              className="w-full py-2 bg-surface-2 hover:bg-surface-3 border border-hairline text-xs rounded font-semibold text-ink flex items-center justify-center gap-1.5"
            >
              <Upload className="h-3.5 w-3.5" /> Seleziona CSV
            </button>
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileUpload}
              accept=".csv"
              className="hidden"
            />
          </div>
        </div>

        {/* Validation grid */}
        {validations.length > 0 && (
          <div className="space-y-4">
            <h5 className="text-xs font-semibold text-ink-muted">Preview e Validazione Campi:</h5>
            <div className="max-h-60 overflow-y-auto border border-hairline rounded bg-canvas/30">
              <table className="w-full text-left text-xs font-mono">
                <thead>
                  <tr className="bg-surface-2/40 text-ink-subtle border-b border-hairline">
                    <th className="p-2">Riga</th>
                    {targetType === "company" || targetType === "person" ? (
                      <th className="p-2">CF</th>
                    ) : targetType === "tender" ? (
                      <th className="p-2">CIG</th>
                    ) : (
                      <th className="p-2">Chiave ({primaryKey})</th>
                    )}
                    <th className="p-2">Nome/Titolo</th>
                    <th className="p-2">Stato</th>
                    <th className="p-2">Errori</th>
                  </tr>
                </thead>
                <tbody>
                  {validations.map((v) => (
                    <tr key={v.rowIdx} className={`border-b border-hairline/30 hover:bg-surface-2/10 ${!v.isValid ? "bg-red-950/10" : ""}`}>
                      <td className="p-2 text-ink-subtle">{v.rowIdx}</td>
                      <td className={`p-2 font-semibold ${!v.isValid ? "text-red-400" : "text-ink"}`}>
                        {targetType === "company" || targetType === "person" ? (
                          v.cf
                        ) : targetType === "tender" ? (
                          v.cig
                        ) : (
                          String(csvPreviewRows[v.rowIdx - 1]?.[primaryKey] || "")
                        )}
                      </td>
                      <td className="p-2 text-ink-muted">{targetType !== "tender" ? v.name : v.title}</td>
                      <td className="p-2">
                        {v.isValid ? (
                          <span className="text-emerald-500 font-semibold flex items-center gap-1"><CheckCircle className="h-3 w-3" /> Valido</span>
                        ) : (
                          <span className="text-red-500 font-semibold flex items-center gap-1"><AlertCircle className="h-3 w-3" /> Errore</span>
                        )}
                      </td>
                      <td className="p-2 text-red-400 font-sans">{v.errors.join(", ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => {
                  setValidations([]);
                  setCsvHeaders([]);
                }}
                className="px-4 py-2 bg-surface-2 border border-hairline text-xs font-semibold rounded text-ink hover:bg-surface-3"
              >
                Annulla
              </button>
              <button
                onClick={executeBulkIngest}
                className="px-4 py-2 bg-primary text-on-primary text-xs font-semibold rounded hover:bg-primary-hover active:bg-primary-focus flex items-center gap-1.5 shadow-md shadow-primary/20"
              >
                Carica {validations.filter(v => v.isValid).length} record su Neo4j
              </button>
            </div>
          </div>
        )}
      </div>

      {error && (
        <div className="p-4 bg-red-500/10 border border-red-500/30 text-red-400 rounded-md text-sm">
          {error}
        </div>
      )}

      {result && (
        <div className="p-6 bg-surface-1 border border-hairline rounded-lg space-y-6">
          <h5 className="text-sm font-semibold text-ink flex items-center gap-2">
            <CheckCircle className="h-4 w-4 text-emerald-500" /> Report dell'Ingestione
          </h5>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-6 text-center">
            <div className="p-4 bg-surface-2 border border-hairline rounded">
              <span className="text-[10px] text-ink-subtle uppercase block mb-1">Entità Analizzate</span>
              <span className="text-lg font-bold text-ink">{result.entities_extracted}</span>
            </div>
            <div className="p-4 bg-surface-2 border border-hairline rounded">
              <span className="text-[10px] text-ink-subtle uppercase block mb-1">Entità Fuse</span>
              <span className="text-lg font-bold text-ink text-primary">{result.entities_matched}</span>
            </div>
            <div className="p-4 bg-surface-2 border border-hairline rounded">
              <span className="text-[10px] text-ink-subtle uppercase block mb-1">Nuove Entità</span>
              <span className="text-lg font-bold text-ink text-emerald-500">{result.entities_created}</span>
            </div>
            <div className="p-4 bg-surface-2 border border-hairline rounded">
              <span className="text-[10px] text-ink-subtle uppercase block mb-1">Relazioni Create</span>
              <span className="text-lg font-bold text-ink">{result.relationships_created}</span>
            </div>
            <div className="p-4 bg-surface-2 border border-hairline rounded">
              <span className="text-[10px] text-ink-subtle uppercase block mb-1">Link Impliciti</span>
              <span className="text-lg font-bold text-ink text-amber-500">{result.implicit_connections_found}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// =============================================================================
// 6. NOTEBOOKS WORKSPACE VIEW (Multiple notebooks, sortable tables, CSV export)
// =============================================================================

function NotebooksView({ backendOffline }: { backendOffline: boolean }) {
  const [notebooks, setNotebooks] = useState<Notebook[]>([]);
  const [activeNotebookId, setActiveNotebookId] = useState<string | null>(null);
  const [activeCellExecutionId, setActiveCellExecutionId] = useState<string | null>(null);
  const [renameNotebookId, setRenameNotebookId] = useState<string | null>(null);
  const [renameTitle, setRenameTitle] = useState("");

  // Table sorting states
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("asc");

  useEffect(() => {
    const saved = localStorage.getItem("paladino_notebooks");
    if (saved) {
      const data = JSON.parse(saved);
      setNotebooks(data);
      if (data.length > 0) {
        setActiveNotebookId(data[0].id);
      }
    } else {
      const initial: Notebook = {
        id: "nb-101",
        title: "Indagine Connessioni Anomale Appalti",
        author: "Analista Local",
        created_at: new Date().toISOString(),
        cells: [
          { id: "c1", cell_type: "markdown", title: "Note Iniziali", content: "## Introduzione all'Indagine\nQuesta pagina traccia l'interazione anomala tra il consorzio ACME SRL e azionisti esteri." },
          { id: "c2", cell_type: "cypher_query", title: "Visualizzazione Relazioni", content: "MATCH (c:Company {nome_normalizzato: 'ACME SRL'})-[r:WINS]->(t:Tender)\nRETURN c.cf AS CodiceFiscale, t.cig AS CIG, t.title AS TitoloAppalto LIMIT 5" }
        ]
      };
      setNotebooks([initial]);
      setActiveNotebookId(initial.id);
      localStorage.setItem("paladino_notebooks", JSON.stringify([initial]));
    }
  }, []);

  const saveNotebooks = (updated: Notebook[]) => {
    setNotebooks(updated);
    localStorage.setItem("paladino_notebooks", JSON.stringify(updated));
  };

  const activeNotebook = notebooks.find((n) => n.id === activeNotebookId);

  const createNotebook = () => {
    const newNb: Notebook = {
      id: `nb_${Date.now()}`,
      title: `Nuovo Notebook Investigativo ${notebooks.length + 1}`,
      author: "Analista Local",
      created_at: new Date().toISOString(),
      cells: [
        { id: `c_${Date.now()}`, cell_type: "markdown", title: "Intro", content: "## Nuovo Foglio Investigativo" }
      ]
    };
    const updated = [...notebooks, newNb];
    saveNotebooks(updated);
    setActiveNotebookId(newNb.id);
  };

  const deleteNotebook = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    const updated = notebooks.filter((n) => n.id !== id);
    saveNotebooks(updated);
    if (activeNotebookId === id && updated.length > 0) {
      setActiveNotebookId(updated[0].id);
    }
  };

  const startRename = (id: string, currentTitle: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setRenameNotebookId(id);
    setRenameTitle(currentTitle);
  };

  const saveRename = () => {
    if (!renameTitle.trim() || !renameNotebookId) return;
    const updated = notebooks.map((n) => (n.id === renameNotebookId ? { ...n, title: renameTitle } : n));
    saveNotebooks(updated);
    setRenameNotebookId(null);
  };

  const addCell = (type: "cypher_query" | "markdown") => {
    if (!activeNotebook) return;
    const newCell: NotebookCell = {
      id: `c_${Date.now()}`,
      cell_type: type,
      title: type === "cypher_query" ? "Nuova Query Cypher" : "Nuova Nota Markdown",
      content: type === "cypher_query" ? "MATCH (n) RETURN n LIMIT 10" : "### Inserisci markdown qui"
    };
    const updated = notebooks.map((n) =>
      n.id === activeNotebookId ? { ...n, cells: [...n.cells, newCell] } : n
    );
    saveNotebooks(updated);
  };

  const deleteCell = (cellId: string) => {
    if (!activeNotebook) return;
    const updated = notebooks.map((n) =>
      n.id === activeNotebookId ? { ...n, cells: n.cells.filter((c) => c.id !== cellId) } : n
    );
    saveNotebooks(updated);
  };

  const updateCellContent = (cellId: string, content: string) => {
    if (!activeNotebook) return;
    const updated = notebooks.map((n) =>
      n.id === activeNotebookId
        ? { ...n, cells: n.cells.map((c) => (c.id === cellId ? { ...c, content } : c)) }
        : n
    );
    saveNotebooks(updated);
  };

  const runCell = async (cellId: string) => {
    if (!activeNotebook) return;
    setActiveCellExecutionId(cellId);
    const targetCell = activeNotebook.cells.find((c) => c.id === cellId);
    if (!targetCell) return;

    if (backendOffline || targetCell.cell_type === "markdown") {
      setTimeout(() => {
        const output = targetCell.cell_type === "cypher_query" 
          ? [
              { CodiceFiscale: "02394850119", CIG: "Z123456789", TitoloAppalto: "Servizio Manutenzione Strade Milano" },
              { CodiceFiscale: "08234850152", CIG: "Z778899AA0", TitoloAppalto: "Fornitura Ristorazione Scolastica Roma" }
            ]
          : [{ render: "Markdown renderizzato con successo!" }];
        
        const updated = notebooks.map((n) =>
          n.id === activeNotebookId
            ? {
                ...n,
                cells: n.cells.map((c) =>
                  c.id === cellId ? { ...c, output, executed_at: new Date().toLocaleTimeString() } : c
                )
              }
            : n
        );
        saveNotebooks(updated);
        setActiveCellExecutionId(null);
      }, 1000);
      return;
    }

    try {
      const res = await fetch(`/api/notebooks/${activeNotebook.id}/cells/${cellId}/execute`, {
        method: "POST"
      });
      if (res.ok) {
        const data = await res.json();
        const updated = notebooks.map((n) =>
          n.id === activeNotebookId
            ? {
                ...n,
                cells: n.cells.map((c) =>
                  c.id === cellId ? { ...c, output: data.result, error: data.error } : c
                )
              }
            : n
        );
        saveNotebooks(updated);
      }
    } catch {
      const updated = notebooks.map((n) =>
        n.id === activeNotebookId
          ? {
              ...n,
              cells: n.cells.map((c) => (c.id === cellId ? { ...c, error: "Errore esecuzione" } : c))
            }
          : n
      );
      saveNotebooks(updated);
    } finally {
      setActiveCellExecutionId(null);
    }
  };

  const exportTableCSV = (data: any[], title: string) => {
    if (!data || data.length === 0) return;
    const headers = Object.keys(data[0]);
    const csvRows = [
      headers.join(","), // header row
      ...data.map((row) =>
        headers.map((fieldName) => JSON.stringify(row[fieldName] || "")).join(",")
      )
    ];

    const csvContent = "data:text/csv;charset=utf-8," + csvRows.join("\n");
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `${title.replace(/\s+/g, "_")}_output.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleSort = (key: string) => {
    let order: "asc" | "desc" = "asc";
    if (sortKey === key && sortOrder === "asc") {
      order = "desc";
    }
    setSortKey(key);
    setSortOrder(order);
  };

  const getSortedData = (data: any[]) => {
    if (!sortKey) return data;
    return [...data].sort((a, b) => {
      const valA = a[sortKey];
      const valB = b[sortKey];
      if (valA === undefined || valB === undefined) return 0;
      
      if (typeof valA === "number" && typeof valB === "number") {
        return sortOrder === "asc" ? valA - valB : valB - valA;
      }
      return sortOrder === "asc"
        ? String(valA).localeCompare(String(valB))
        : String(valB).localeCompare(String(valA));
    });
  };

  return (
    <div className="flex h-[calc(100vh-140px)] gap-6 animate-fadeIn">
      {/* Notebooks navigation sidebar */}
      <div className="w-64 bg-surface-1 border border-hairline rounded-lg p-4 flex flex-col justify-between flex-shrink-0">
        <div className="space-y-4">
          <div className="flex justify-between items-center">
            <span className="text-[11px] font-bold text-ink-subtle uppercase tracking-wider font-mono">I miei Notebooks</span>
            <button
              onClick={createNotebook}
              className="p-1 hover:bg-surface-2 rounded text-primary hover:text-primary-hover transition-colors"
              title="Nuovo Notebook"
            >
              <Plus className="h-4 w-4" />
            </button>
          </div>
          <div className="space-y-1.5 overflow-y-auto max-h-96">
            {notebooks.map((nb) => (
              <div
                key={nb.id}
                onClick={() => setActiveNotebookId(nb.id)}
                className={`p-2.5 rounded text-xs flex items-center justify-between cursor-pointer group transition-all ${
                  activeNotebookId === nb.id 
                    ? "bg-surface-2 border-l-2 border-primary text-ink" 
                    : "text-ink-subtle hover:text-ink hover:bg-surface-2/50"
                }`}
              >
                {renameNotebookId === nb.id ? (
                  <input
                    type="text"
                    value={renameTitle}
                    onChange={(e) => setRenameTitle(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && saveRename()}
                    onBlur={saveRename}
                    className="bg-canvas border border-hairline p-0.5 text-xs text-ink w-40 font-mono"
                    autoFocus
                  />
                ) : (
                  <span className="truncate max-w-[150px] font-medium">{nb.title}</span>
                )}
                <div className="opacity-0 group-hover:opacity-100 flex gap-1.5 transition-opacity">
                  <button
                    onClick={(e) => startRename(nb.id, nb.title, e)}
                    className="text-[10px] text-ink-subtle hover:text-ink"
                    title="Rinomina"
                  >
                    ✎
                  </button>
                  <button
                    onClick={(e) => deleteNotebook(nb.id, e)}
                    className="text-ink-subtle hover:text-red-400"
                    title="Elimina"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Editor & cell execution view */}
      {activeNotebook ? (
        <div className="flex-1 bg-surface-1 border border-hairline rounded-lg p-6 overflow-y-auto flex flex-col justify-between">
          <div className="space-y-6">
            <div className="flex justify-between items-center border-b border-hairline pb-4">
              <div>
                <h3 className="text-base font-semibold text-ink font-mono">{activeNotebook.title}</h3>
                <span className="text-[10px] text-ink-subtle block font-mono mt-0.5">
                  Autore: {activeNotebook.author} · Creato: {new Date(activeNotebook.created_at).toLocaleDateString()}
                </span>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => addCell("cypher_query")}
                  className="px-3 py-1.5 bg-surface-2 hover:bg-surface-3 border border-hairline rounded text-xs font-semibold flex items-center gap-1.5 transition-colors duration-200 text-ink-muted"
                >
                  <Plus className="h-3.5 w-3.5" /> + Cypher
                </button>
                <button
                  onClick={() => addCell("markdown")}
                  className="px-3 py-1.5 bg-surface-2 hover:bg-surface-3 border border-hairline rounded text-xs font-semibold flex items-center gap-1.5 transition-colors duration-200 text-ink-muted"
                >
                  <Plus className="h-3.5 w-3.5" /> + Markdown
                </button>
              </div>
            </div>

            <div className="space-y-6">
              {activeNotebook.cells.map((cell) => (
                <div key={cell.id} className="bg-surface-2 border border-hairline rounded overflow-hidden group">
                  {/* Cell Header */}
                  <div className="px-4 py-2 bg-surface-3/50 flex items-center justify-between border-b border-hairline/60">
                    <span className="text-[10px] font-mono text-ink-subtle flex items-center gap-1.5">
                      <Code className="h-3.5 w-3.5" /> {cell.title}
                    </span>
                    <div className="flex items-center gap-3">
                      <button
                        onClick={() => runCell(cell.id)}
                        disabled={activeCellExecutionId === cell.id}
                        className="p-1 rounded hover:bg-surface-3 text-ink-subtle hover:text-emerald-500 transition-colors"
                      >
                        <Play className={`h-4 w-4 ${activeCellExecutionId === cell.id ? "animate-pulse" : ""}`} />
                      </button>
                      <button
                        onClick={() => deleteCell(cell.id)}
                        className="p-1 rounded hover:bg-surface-3 text-ink-subtle hover:text-red-500 transition-colors"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </div>

                  {/* Input area */}
                  <div className="p-4 bg-canvas/45">
                    <textarea
                      value={cell.content}
                      onChange={(e) => updateCellContent(cell.id, e.target.value)}
                      className="w-full h-24 bg-transparent border-0 outline-none text-sm font-mono text-ink resize-none leading-relaxed"
                    />
                  </div>

                  {/* Sortable output table area */}
                  {cell.output && cell.output.length > 0 && (
                    <div className="p-4 border-t border-hairline bg-surface-1/40">
                      <div className="flex justify-between items-center mb-3">
                        <span className="text-[10px] text-ink-subtle uppercase font-mono">Risultati Cypher ({cell.executed_at})</span>
                        {cell.cell_type === "cypher_query" && (
                          <button
                            onClick={() => exportTableCSV(cell.output || [], cell.title)}
                            className="px-2.5 py-1 bg-surface-3 border border-hairline rounded text-[10px] font-semibold text-ink hover:bg-surface-4 flex items-center gap-1 transition-all"
                          >
                            <Download className="h-3 w-3" /> Esporta CSV
                          </button>
                        )}
                      </div>

                      {cell.cell_type === "markdown" ? (
                        <p className="text-xs text-ink-muted leading-relaxed whitespace-pre-wrap">{cell.content}</p>
                      ) : (
                        <div className="overflow-x-auto border border-hairline rounded bg-canvas/30">
                          <table className="w-full text-left text-xs font-mono">
                            <thead>
                              <tr className="bg-surface-2 border-b border-hairline text-ink-subtle">
                                {Object.keys(cell.output[0]).map((key) => (
                                  <th
                                    key={key}
                                    onClick={() => handleSort(key)}
                                    className="p-2 cursor-pointer hover:bg-surface-3 select-none"
                                  >
                                    <span className="flex items-center gap-1">
                                      {key}
                                      {sortKey === key && (sortOrder === "asc" ? "▲" : "▼")}
                                    </span>
                                  </th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {getSortedData(cell.output).map((row, rowIdx) => (
                                <tr key={rowIdx} className="border-b border-hairline/20 hover:bg-surface-2/15">
                                  {Object.keys(row).map((key) => (
                                    <td key={key} className="p-2 text-ink tabular-nums leading-relaxed whitespace-nowrap overflow-hidden text-ellipsis">
                                      {typeof row[key] === "object" ? JSON.stringify(row[key]) : String(row[key])}
                                    </td>
                                  ))}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <div className="flex-1 flex flex-col items-center justify-center text-center text-ink-subtle border border-hairline rounded-lg">
          <BookOpen className="h-10 w-10 mb-2 opacity-35" />
          <p className="text-sm">Seleziona o crea un notebook per avviare l'indagine grafica.</p>
        </div>
      )}
    </div>
  );
}

// =============================================================================
// SLIDE-OUT NODE DETAIL DRAWER
// =============================================================================

function NodeDetailDrawer({
  node,
  onClose,
  backendOffline
}: {
  node: GraphNode;
  onClose: () => void;
  backendOffline: boolean;
}) {
  const [explanation, setExplanation] = useState<string | null>(null);
  const [loadingExplain, setLoadingExplain] = useState(false);

  const [comments, setComments] = useState<Comment[]>([
    { id: "cm_1", entity_id: node.id, entity_type: node.label || "Company", content: "Struttura proprietaria complessa identificata dall'algoritmo.", author: "analista_1", created_at: "2026-07-11T16:00:00Z" }
  ]);
  const [newComment, setNewComment] = useState("");

  useEffect(() => {
    if (backendOffline) return;
    const fetchComments = async () => {
      try {
        const res = await fetch(`/api/entities/${node.label || "Company"}/${node.id}/comments`);
        if (res.ok) {
          const data = await res.json();
          setComments(data);
        }
      } catch (e) {
        console.error("Failed to load comments from backend:", e);
      }
    };
    fetchComments();
  }, [node.id, node.label, backendOffline]);

  const getExplanation = async () => {
    setLoadingExplain(true);
    if (backendOffline) {
      setTimeout(() => {
        setExplanation(
          "### Analisi di Rischio Integrata (LLM)\n\n" +
          "1. **Indicatori Rilevati**: Rilevata anomalie di tipo *ownership_migration* con capitali trasferiti verso una controllante registrata in territorio a fiscalità agevolata.\n" +
          "2. **Punteggio Confidenza**: 94% basato su ANAC e Registro Imprese.\n" +
          "3. **Raccomandazione**: Eseguire un controllo approfondito del beneficiario effettivo (UBO) e ispezionare gli altri bandi vinti nell'ultimo trimestre."
        );
        setLoadingExplain(false);
      }, 1000);
      return;
    }

    try {
      const res = await fetch(`/api/explain?entity_id=${node.id}&entity_type=${node.label}`);
      if (res.ok) {
        const data = await res.json();
        setExplanation(data.explanation);
      }
    } catch {
      setExplanation("Errore durante l'ottenimento della spiegazione dal server.");
    } finally {
      setLoadingExplain(false);
    }
  };

  const addComment = async () => {
    if (!newComment.trim()) return;

    if (backendOffline) {
      const comment: Comment = {
        id: `cm_${Date.now()}`,
        entity_id: node.id,
        entity_type: node.label || "Company",
        content: newComment,
        author: "analista_corrente",
        created_at: new Date().toISOString()
      };
      setComments((prev) => [...prev, comment]);
      setNewComment("");
      return;
    }

    try {
      const res = await fetch("/api/comments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          entity_id: node.id,
          entity_type: node.label || "Company",
          content: newComment,
          author: "Admin Local"
        })
      });
      if (res.ok) {
        const data = await res.json();
        setComments((prev) => [...prev, data]);
        setNewComment("");
      }
    } catch (e) {
      console.error("Failed to add comment:", e);
    }
  };

  return (
    <div className="absolute top-0 right-0 w-96 h-full bg-surface-1 border-l border-hairline shadow-2xl flex flex-col justify-between overflow-hidden animate-slideLeft z-50">
      <div className="flex-1 overflow-y-auto">
        {/* Header */}
        <div className="p-6 border-b border-hairline flex items-center justify-between bg-surface-2/40">
          <div>
            <span className="text-[10px] text-primary uppercase font-bold tracking-wider font-mono">
              {node.label || "Company"} Detail
            </span>
            <h4 className="text-sm font-semibold text-ink mt-0.5">
              {node.nome_normalizzato || node.name || node.title || node.id}
            </h4>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-surface-2 rounded text-ink-subtle hover:text-ink">
            ✕
          </button>
        </div>

        {/* Node Properties */}
        <div className="p-6 space-y-4 border-b border-hairline">
          <h5 className="text-[11px] font-semibold uppercase text-ink-subtle font-mono flex items-center gap-1.5">
            <Info className="h-3 w-3" /> Proprietà Grafo
          </h5>
          <div className="grid grid-cols-2 gap-4 text-xs font-mono">
            {node.id && (
              <div>
                <span className="text-ink-subtle block">ID Entità</span>
                <span className="font-semibold text-ink truncate block max-w-[150px]">{node.id}</span>
              </div>
            )}
            {node.cf && (
              <div>
                <span className="text-ink-subtle block">Codice Fiscale</span>
                <span className="font-semibold text-ink">{node.cf}</span>
              </div>
            )}
            {node.cig && (
              <div>
                <span className="text-ink-subtle block">CIG</span>
                <span className="font-semibold text-ink">{node.cig}</span>
              </div>
            )}
            {node.risk_score !== undefined && (
              <div>
                <span className="text-ink-subtle block">Risk Score</span>
                <span className="font-semibold text-red-400">
                  {Math.round(node.risk_score * 100)}%
                </span>
              </div>
            )}
          </div>
        </div>

        {/* LLM Explain */}
        <div className="p-6 space-y-4 border-b border-hairline">
          <div className="flex justify-between items-center">
            <h5 className="text-[11px] font-semibold uppercase text-ink-subtle font-mono flex items-center gap-1.5">
              <Lock className="h-3 w-3" /> Spiegazione Rischio AI
            </h5>
            {!explanation && (
              <button
                onClick={getExplanation}
                disabled={loadingExplain}
                className="text-[11px] font-semibold text-primary hover:underline"
              >
                {loadingExplain ? "Elaborazione..." : "Genera Spiegazione"}
              </button>
            )}
          </div>
          {explanation && (
            <div className="p-4 bg-surface-2 border border-hairline rounded text-xs text-ink-muted leading-relaxed whitespace-pre-wrap">
              {explanation}
            </div>
          )}
        </div>

        {/* Comments */}
        <div className="p-6 space-y-4">
          <h5 className="text-[11px] font-semibold uppercase text-ink-subtle font-mono">
            Commenti & Annotazioni
          </h5>
          <div className="space-y-3">
            {comments.map((c) => (
              <div key={c.id} className="p-3 bg-surface-2 border border-hairline rounded text-xs">
                <div className="flex justify-between items-center mb-1 text-ink-subtle font-mono text-[10px]">
                  <span>@{c.author}</span>
                  <span>{new Date(c.created_at).toLocaleDateString()}</span>
                </div>
                <p className="text-ink-muted">{c.content}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Write Comment */}
      <div className="p-4 border-t border-hairline bg-surface-2/30 flex gap-2 flex-shrink-0">
        <input
          type="text"
          value={newComment}
          onChange={(e) => setNewComment(e.target.value)}
          placeholder="Aggiungi nota investigativa..."
          className="flex-1 px-3 py-1.5 bg-surface-1 border border-hairline text-xs rounded text-ink focus:outline-none focus:border-primary"
        />
        <button
          onClick={addComment}
          className="px-3 py-1.5 bg-primary text-on-primary font-semibold text-xs rounded hover:bg-primary-hover transition-colors"
        >
          Invia
        </button>
      </div>
    </div>
  );
}
