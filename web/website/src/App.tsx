import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import {
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Check,
  ChevronRight,
  CircleAlert,
  Clipboard,
  Code2,
  Cpu,
  ExternalLink,
  Gauge,
  Globe2,
  HardDrive,
  KeyRound,
  Menu,
  Network,
  Play,
  Radar,
  RefreshCw,
  Search,
  ServerCog,
  ShieldCheck,
  Sparkles,
  Terminal,
  WalletCards,
  X,
  Zap,
  type LucideIcon,
} from 'lucide-react'

import {
  getFaucetStatus,
  getNetworkSummary,
  isDemoMode,
  issueFaucetChallenge,
  searchEndpoints,
  submitFaucetClaim,
  type EndpointSearchResponse,
  type EndpointSummary,
  type FaucetChallenge,
  type FaucetClaimResult,
  type FaucetStatus,
  type NetworkMetric,
  type NetworkSummary,
} from './api'

type Route = 'home' | 'how' | 'network' | 'run' | 'build' | 'docs' | 'faucet'
type Navigate = (route: Route) => void

const routeLabels: Record<Route, string> = {
  home: 'Home',
  how: 'How it works',
  network: 'Network',
  run: 'Run a node',
  build: 'Build',
  docs: 'Docs',
  faucet: 'Faucet',
}

const routeFromLocation = (): Route => {
  const raw = window.location.hash.slice(1) || window.location.pathname.replace(/^\//, '')
  const normalized = raw.replace(/^app\//, '')
  if (normalized === 'how-it-works' || normalized === 'how') return 'how'
  if (normalized === 'network' || normalized === 'explorer') return 'network'
  if (normalized === 'run-a-node' || normalized === 'run') return 'run'
  if (normalized === 'build') return 'build'
  if (normalized === 'docs') return 'docs'
  if (normalized === 'faucet') return 'faucet'
  return 'home'
}

function useWebsiteData() {
  const [summary, setSummary] = useState<NetworkSummary | null>(null)
  const [endpoints, setEndpoints] = useState<EndpointSearchResponse | null>(null)
  const [faucet, setFaucet] = useState<FaucetStatus | null>(null)
  const [summaryState, setSummaryState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [endpointState, setEndpointState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [faucetState, setFaucetState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [errors, setErrors] = useState<Record<'summary' | 'endpoints' | 'faucet', string | null>>({ summary: null, endpoints: null, faucet: null })
  function clearError(source: 'summary' | 'endpoints' | 'faucet') {
    setErrors((current) => current[source] === null ? current : { ...current, [source]: null })
  }
  function reportError(source: 'summary' | 'endpoints' | 'faucet', message: string) {
    setErrors((current) => ({ ...current, [source]: message }))
  }

  async function refreshSummary() {
    setSummaryState('loading')
    clearError('summary')
    try {
      setSummary(await getNetworkSummary())
      setSummaryState('ready')
      clearError('summary')
    } catch (reason) {
      setSummaryState('error')
      reportError('summary', reason instanceof Error ? reason.message : 'Network summary is unavailable')
    }
  }

  async function refreshEndpoints() {
    setEndpointState('loading')
    clearError('endpoints')
    try {
      setEndpoints(await searchEndpoints())
      setEndpointState('ready')
      clearError('endpoints')
    } catch (reason) {
      setEndpointState('error')
      reportError('endpoints', reason instanceof Error ? reason.message : 'Endpoint discovery is unavailable')
    }
  }

  async function refreshFaucet() {
    setFaucetState('loading')
    clearError('faucet')
    try {
      setFaucet(await getFaucetStatus())
      setFaucetState('ready')
      clearError('faucet')
    } catch (reason) {
      setFaucetState('error')
      reportError('faucet', reason instanceof Error ? reason.message : 'Faucet status is unavailable')
    }
  }

  useEffect(() => {
    void refreshSummary()
    void refreshEndpoints()
    void refreshFaucet()
  }, [])

  const error = Object.values(errors).find((message): message is string => Boolean(message)) ?? null
  return { summary, endpoints, faucet, summaryState, endpointState, faucetState, error, refreshSummary, refreshEndpoints, refreshFaucet }
}

function App() {
  const [route, setRoute] = useState<Route>(routeFromLocation)
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const website = useWebsiteData()

  useEffect(() => {
    const syncRoute = () => setRoute(routeFromLocation())
    window.addEventListener('popstate', syncRoute)
    window.addEventListener('hashchange', syncRoute)
    return () => {
      window.removeEventListener('popstate', syncRoute)
      window.removeEventListener('hashchange', syncRoute)
    }
  }, [])

  const navigate: Navigate = (nextRoute) => {
    const nextPath = nextRoute === 'home' ? '/' : nextRoute === 'faucet' ? '/app/faucet' : `/${nextRoute === 'how' ? 'how-it-works' : nextRoute === 'run' ? 'run-a-node' : nextRoute}`
    window.history.pushState({}, '', nextPath)
    setRoute(nextRoute)
    setMobileMenuOpen(false)
    window.scrollTo({ top: 0, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' })
  }

  return (
    <div className="site-shell">
      <SiteHeader route={route} navigate={navigate} mobileMenuOpen={mobileMenuOpen} setMobileMenuOpen={setMobileMenuOpen} />
      {isDemoMode() ? <div className="preview-ribbon"><Sparkles size={14} /><span>Preview data is illustrative — connect the Website API before publishing network metrics.</span></div> : null}
      {website.error && !isDemoMode() ? <div className="site-error" role="status"><CircleAlert size={15} /> Some live data is unavailable. Missing metrics remain unreported.</div> : null}
      <main>
        {route === 'home' ? <HomePage navigate={navigate} summary={website.summary} summaryState={website.summaryState} /> : null}
        {route === 'how' ? <HowItWorksPage navigate={navigate} /> : null}
        {route === 'network' ? <NetworkPage summary={website.summary} endpoints={website.endpoints} summaryState={website.summaryState} endpointState={website.endpointState} onRefresh={() => { void website.refreshSummary(); void website.refreshEndpoints() }} /> : null}
        {route === 'run' ? <RunNodePage navigate={navigate} /> : null}
        {route === 'build' ? <BuildPage navigate={navigate} /> : null}
        {route === 'docs' ? <DocsPage navigate={navigate} /> : null}
        {route === 'faucet' ? <FaucetPage faucet={website.faucet} state={website.faucetState} onRefresh={() => void website.refreshFaucet()} /> : null}
      </main>
      <SiteFooter navigate={navigate} />
    </div>
  )
}

function BrandMark() {
  return <span className="brand-mark" aria-hidden="true"><svg viewBox="0 0 52 52" fill="none"><path d="M26 3 46 14.5v23L26 49 6 37.5v-23L26 3Z" stroke="currentColor" strokeWidth="2.8" /><path d="m26 14 10.4 6v12L26 38l-10.4-6V20L26 14Z" fill="currentColor" fillOpacity=".12" stroke="currentColor" strokeWidth="2" /><path d="M26 3v11m0 24v11M6 14.5l9.6 5.5m20.8 12L46 37.5M46 14.5l-9.6 5.5m-20.8 12L6 37.5" stroke="currentColor" strokeWidth="1.5" opacity=".65" /></svg></span>
}

function SiteHeader({ route, navigate, mobileMenuOpen, setMobileMenuOpen }: { route: Route; navigate: Navigate; mobileMenuOpen: boolean; setMobileMenuOpen: (open: boolean) => void }) {
  const navRoutes: Route[] = ['how', 'network', 'run', 'build', 'docs']
  return <header className="site-header">
    <div className="site-header-inner">
      <button className="brand" type="button" onClick={() => navigate('home')} aria-label="AiDN home"><BrandMark /><span>AiDN</span></button>
      <nav className="desktop-nav" aria-label="Primary navigation">{navRoutes.map((item) => <button key={item} className={route === item ? 'nav-link active' : 'nav-link'} type="button" onClick={() => navigate(item)}>{routeLabels[item]}</button>)}</nav>
      <div className="header-actions"><button className="faucet-link" type="button" onClick={() => navigate('faucet')}><WalletCards size={15} /> Get Q</button><button className="header-node-cta" type="button" onClick={() => navigate('run')}>Run a node <ArrowUpRight size={15} /></button><button className="menu-button" type="button" aria-label={mobileMenuOpen ? 'Close navigation' : 'Open navigation'} aria-expanded={mobileMenuOpen} onClick={() => setMobileMenuOpen(!mobileMenuOpen)}>{mobileMenuOpen ? <X size={20} /> : <Menu size={20} />}</button></div>
    </div>
    {mobileMenuOpen ? <nav className="mobile-nav" aria-label="Mobile navigation">{[...navRoutes, 'faucet' as Route].map((item) => <button key={item} className={route === item ? 'mobile-nav-link active' : 'mobile-nav-link'} type="button" onClick={() => navigate(item)}>{routeLabels[item]}<ChevronRight size={16} /></button>)}</nav> : null}
  </header>
}

function StatusBar({ summary, state }: { summary: NetworkSummary | null; state: 'loading' | 'ready' | 'error' }) {
  const label = state === 'loading' ? 'Checking network' : state === 'ready' && summary?.status === 'operational' ? 'Network operational' : state === 'ready' ? `Network ${summary?.status ?? 'unavailable'}` : 'Network status unavailable'
  return <div className="status-bar"><span className={state === 'ready' && summary?.status === 'operational' ? 'status-dot good' : 'status-dot'} /><span>{label}</span><span className="status-separator" /><span className="status-detail">{summary?.observedAt ? `Observed ${formatObserved(summary.observedAt)}` : 'Live status comes from the Website API'}</span>{isDemoMode() ? <span className="status-preview">Preview</span> : null}</div>
}

function HomePage({ navigate, summary, summaryState }: { navigate: Navigate; summary: NetworkSummary | null; summaryState: 'loading' | 'ready' | 'error' }) {
  return <>
    <section className="hero-section page-width"><div className="hero-copy"><p className="hero-kicker"><span className="kicker-line" /> Open network for AI compute</p><h1>AI compute,<br /><em>shared.</em></h1><p className="hero-lede">Connect your hardware, use compute across the network, and let AI agents choose the resources they need.</p><div className="hero-actions"><button className="button button-primary" type="button" onClick={() => navigate('run')}>Run a node <ArrowRight size={17} /></button><button className="button button-quiet" type="button" onClick={() => navigate('network')}>Explore AiDN <Globe2 size={16} /></button></div><p className="hero-note"><span className="note-mark">↳</span> Local first. Network when you need more.</p></div><TopologyMap /></section>
    <div className="page-width"><StatusBar summary={summary} state={summaryState} /></div>
    <section className="section page-width principle-section"><div className="section-heading"><p className="section-kicker">The network model</p><h2>Your hardware stays yours.<br /><span>Its idle capacity can become someone else’s next step.</span></h2></div><div className="principle-grid"><div className="principle-visual"><div className="principle-node local"><Cpu size={18} /><span>Your compute</span><strong>Local node</strong></div><div className="principle-route"><span /><span /><span /></div><div className="principle-core"><BrandMark /><span>AiDN<br />network</span></div><div className="principle-route reverse"><span /><span /><span /></div><div className="principle-node network"><Network size={18} /><span>Other compute</span><strong>Best endpoint</strong></div></div><div className="principle-copy"><p>When a task fits locally, it stays local. When your GPU is busy or the model lives elsewhere, an agent can discover a suitable endpoint, compare its constraints, and route the request through the network.</p><button className="text-link" type="button" onClick={() => navigate('how')}>See how it works <ArrowUpRight size={15} /></button></div></div></section>
    <section className="section page-width why-section"><div className="section-heading compact"><p className="section-kicker">Why AiDN</p><h2>One network, three useful moves.</h2></div><div className="why-list"><WhyItem icon={Gauge} title="Use" copy="Need more compute? Find a validated endpoint with the model, context, latency, and price your task can accept." action="Explore the network" onClick={() => navigate('network')} /><WhyItem icon={HardDrive} title="Share" copy="Have a GPU sitting idle? Install Hypervisor, choose a provider, and make capacity available on your terms." action="Run a node" onClick={() => navigate('run')} /><WhyItem icon={Code2} title="Build" copy="Give an autonomous agent a network it can discover, compare, and use without hard-coding one provider." action="Build with AiDN" onClick={() => navigate('build')} /></div></section>
    <section className="section page-width local-first-section"><div className="local-first-copy"><p className="section-kicker">Local first</p><h2>Start at the edge.<br /><span>Reach further only when the task asks.</span></h2><p>AiDN is designed around a practical decision: use the resource already under your control, then extend into the network when local capacity, model availability, or policy says to.</p></div><div className="decision-flow"><FlowRow label="Task arrives" value="Agent or user request" state="start" /><FlowRow label="Local resource available?" value="Use local execution" state="yes" /><FlowRow label="Not enough locally" value="Discover best endpoint" state="network" /></div></section>
    <section className="closing-band"><div className="page-width closing-band-inner"><div><p className="section-kicker">Make compute useful</p><h2>Bring a node online.<br />Or bring a task to the network.</h2></div><div className="closing-actions"><button className="button button-primary" type="button" onClick={() => navigate('run')}>Install Hypervisor <ArrowRight size={17} /></button><button className="text-link light" type="button" onClick={() => navigate('faucet')}>Get starter Q <ArrowUpRight size={15} /></button></div></div></section>
  </>
}

function TopologyMap() {
  return <div className="topology-map" aria-label="Illustration of an agent request moving from local compute through the AiDN network to an endpoint"><div className="map-header"><span className="mono-label">REQUEST ROUTE</span><span className="map-live"><span className="status-dot good" /> running example</span></div><div className="map-stage"><svg className="map-lines" viewBox="0 0 600 370" preserveAspectRatio="none" aria-hidden="true"><path d="M100 270 C180 270 192 106 287 106 S390 270 500 270" /><path d="M100 270 C190 270 218 205 287 205 S395 270 500 270" className="faint" /><circle cx="287" cy="106" r="4" /><circle cx="287" cy="205" r="4" /></svg><div className="map-node node-agent"><span className="node-icon orange"><Sparkles size={17} /></span><span className="mono-label">CALLER</span><strong>Agent</strong><small>request / infer</small></div><div className="map-node node-local"><span className="node-icon cyan"><Cpu size={17} /></span><span className="mono-label">LOCAL</span><strong>RTX 4090</strong><small>available · 24 GB</small></div><div className="map-node node-network"><span className="node-icon blue"><Network size={17} /></span><span className="mono-label">NETWORK</span><strong>AiDN</strong><small>discovery + policy</small></div><div className="map-node node-endpoint"><span className="node-icon green"><Zap size={17} /></span><span className="mono-label">ENDPOINT</span><strong>Qwen3.8</strong><small>validated · 32k context</small></div><div className="route-pulse first" /><div className="route-pulse second" /></div><div className="map-footer"><span><i className="legend-dot cyan" /> local check</span><span><i className="legend-dot blue" /> discovery</span><span><i className="legend-dot green" /> execution</span><span className="map-q">Q accounting <ArrowUpRight size={13} /></span></div></div>
}

function WhyItem({ icon: Icon, title, copy, action, onClick }: { icon: LucideIcon; title: string; copy: string; action: string; onClick: () => void }) {
  return <article className="why-item"><div className="why-icon"><Icon size={17} /></div><div className="why-content"><h3>{title}</h3><p>{copy}</p><button className="text-link" type="button" onClick={onClick}>{action} <ArrowUpRight size={14} /></button></div></article>
}

function FlowRow({ label, value, state }: { label: string; value: string; state: 'start' | 'yes' | 'network' }) {
  return <div className={`flow-row ${state}`}><span className="flow-state">{state === 'start' ? '01' : state === 'yes' ? '02' : '03'}</span><span className="flow-label">{label}</span><strong>{value}</strong><ChevronRight size={15} /></div>
}

function HowItWorksPage({ navigate }: { navigate: Navigate }) {
  const steps = [
    { icon: Terminal, title: 'Connect', copy: 'Install the Hypervisor. It discovers host resources and keeps the node’s local control boundary explicit.', action: 'loopback by default' },
    { icon: ServerCog, title: 'Deploy', copy: 'Choose a Provider, materialize a model, and compose a Bundle with the runtime and endpoint policy it needs.', action: 'provider + model + policy' },
    { icon: ShieldCheck, title: 'Publish', copy: 'Validate the exact Endpoint configuration, then publish the offer only when its network-facing evidence is ready.', action: 'validation before reach' },
    { icon: Radar, title: 'Use', copy: 'Agents and people discover suitable Endpoints, compare constraints, and execute through the resource that fits.', action: 'discover → compare → execute' },
  ]
  return <PageIntro kicker="A working sequence" title={<>From hardware<br /><span>to useful compute.</span></>} detail="AiDN keeps the operational chain visible. Every step has a clear owner, a real state, and a hand-off you can inspect." action={<button className="button button-primary" type="button" onClick={() => navigate('run')}>Start with Hypervisor <ArrowRight size={17} /></button>}><section className="section page-width sequence-section"><div className="sequence-list">{steps.map(({ icon: Icon, title, copy, action }, index) => <article className="sequence-row" key={title}><span className="sequence-index">{String(index + 1).padStart(2, '0')}</span><div className="sequence-icon"><Icon size={19} /></div><div className="sequence-copy"><h2>{title}</h2><p>{copy}</p></div><span className="sequence-action">{action}</span></article>)}</div></section><section className="section page-width boundary-section"><div className="boundary-panel"><div className="boundary-top"><p className="section-kicker">The boundary that matters</p><span className="state-chip good">Explicit by design</span></div><h2>Local execution and network publication are related, not interchangeable.</h2><div className="boundary-columns"><div><span className="mono-label">LOCAL</span><p>Provider runtimes, model artifacts, and agent permissions stay inside the Hypervisor’s controlled boundary.</p></div><div><span className="mono-label">NETWORK</span><p>Published Endpoints expose only the validated offer and its declared policy. A new public behavior means a new revision.</p></div></div></div></section></PageIntro>
}

function RunNodePage({ navigate }: { navigate: Navigate }) {
  const [copied, setCopied] = useState(false)
  const reviewedRef = import.meta.env.VITE_AIDN_INSTALL_REF || 'operator-bootstrap-v0.1.0-rc1'
  const command = [
    "curl --proto '=https' --tlsv1.2 -fsSL",
    '  https://raw.githubusercontent.com/glinko/AiDN/' + reviewedRef + '/tools/aidn-operator-bootstrap-ubuntu.sh',
    '  | bash -s -- --ref ' + reviewedRef,
  ].join('\n')
  async function copyCommand() {
    await navigator.clipboard?.writeText(command)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 2200)
  }
  return <PageIntro kicker="Operator path" title={<>Turn your hardware<br /><span>into an AiDN node.</span></>} detail="The reviewed Ubuntu installer gets the control plane running. You then connect the network, install a Provider, materialize a model, and decide what to publish." action={<button className="button button-primary" type="button" onClick={copyCommand}>{copied ? <Check size={17} /> : <Clipboard size={17} />} {copied ? 'Copied' : 'Copy install command'}</button>}><section className="section page-width installer-section"><div className="installer-grid"><div className="install-command"><div className="panel-heading"><div><p className="section-kicker">Ubuntu · reviewed release</p><h2>One command to begin.</h2></div><span className="state-chip">{reviewedRef}</span></div><pre><code>{command}</code></pre><button className="command-copy" type="button" onClick={copyCommand}>{copied ? <Check size={15} /> : <Clipboard size={15} />} {copied ? 'Copied to clipboard' : 'Copy command'}</button><p className="install-footnote">The command is pinned to <code>{reviewedRef}</code>. Set <code>VITE_AIDN_INSTALL_REF</code> to the immutable release tag or commit approved for your deployment. Never install production nodes from <code>main</code>.</p></div><div className="requirements"><p className="section-kicker">Before you begin</p><h2>What the installer asks.</h2><div className="requirement-list"><Requirement icon={Cpu} title="Ubuntu 24.04+" detail="A supported Linux host with enough disk for the runtime and model you choose." /><Requirement icon={Network} title="Loopback first" detail="Dashboard and Provider runtimes default to loopback. LAN access is an explicit, trusted-network choice." /><Requirement icon={WalletCards} title="Your operator identity" detail="Pair your agent or create a Wallet when the interactive bootstrap reaches those steps." /></div></div></div></section><section className="section page-width path-section"><div className="section-heading compact"><p className="section-kicker">After install</p><h2>The node path is a sequence, not a mystery.</h2></div><div className="path-track">{['Connect to network', 'Install Provider', 'Deploy model', 'Create Bundle', 'Validate Endpoint', 'Publish'].map((label, index) => <div className="path-step" key={label}><span>{String(index + 1).padStart(2, '0')}</span><strong>{label}</strong>{index < 5 ? <ArrowRight size={14} /> : null}</div>)}</div><button className="text-link" type="button" onClick={() => navigate('docs')}>Read the operator docs <ArrowUpRight size={15} /></button></section></PageIntro>
}

function Requirement({ icon: Icon, title, detail }: { icon: LucideIcon; title: string; detail: string }) {
  return <div className="requirement"><span className="requirement-icon"><Icon size={16} /></span><div><h3>{title}</h3><p>{detail}</p></div></div>
}

function BuildPage({ navigate }: { navigate: Navigate }) {
  return <PageIntro kicker="For builders" title={<>Give your agent<br /><span>an AI network.</span></>} detail="AiDN gives autonomous systems a resource layer they can inspect and use. Keep the local node in control, then let policy decide when a network Endpoint is eligible." action={<button className="button button-primary" type="button" onClick={() => navigate('docs')}>Open developer docs <ArrowRight size={17} /></button>}><section className="section page-width agent-loop-section"><div className="agent-loop"><div className="agent-loop-copy"><p className="section-kicker">Agent loop</p><h2>Discover → compare → execute → verify.</h2><p>The choice of Endpoint is part of the task. Capability, model, latency, context, validation, reputation, and Q price are inputs an agent can reason about.</p><div className="agent-criteria">{['Capability', 'Model', 'Latency', 'Context', 'Validation', 'Q price'].map((item) => <span key={item}>{item}</span>)}</div></div><div className="agent-loop-visual"><div className="loop-ring"><span className="loop-center"><Sparkles size={23} /><small>agent</small></span><span className="loop-label top">discover</span><span className="loop-label right">select</span><span className="loop-label bottom">execute</span><span className="loop-label left">verify</span></div></div></div></section><section className="section page-width mcp-section"><div className="mcp-header"><div><p className="section-kicker">MCP integration</p><h2>Control a node without hiding the controls.</h2></div><span className="state-chip amber">Policy-bound</span></div><div className="mcp-grid">{['Check hardware', 'Install a Provider', 'Materialize a model', 'Create a Bundle', 'Start an Endpoint', 'Inspect network'].map((item) => <div className="mcp-item" key={item}><Check size={15} />{item}</div>)}</div><p className="mcp-note"><KeyRound size={14} /> Financial operations stay behind an explicitly configured operator policy.</p></section></PageIntro>
}

function NetworkPage({ summary, endpoints, summaryState, endpointState, onRefresh }: { summary: NetworkSummary | null; endpoints: EndpointSearchResponse | null; summaryState: 'loading' | 'ready' | 'error'; endpointState: 'loading' | 'ready' | 'error'; onRefresh: () => void }) {
  const [query, setQuery] = useState('')
  const filteredEndpoints = useMemo(() => {
    const normalized = query.trim().toLowerCase()
    if (!normalized) return endpoints?.items ?? []
    return (endpoints?.items ?? []).filter((endpoint) => `${endpoint.model} ${endpoint.provider} ${endpoint.capabilities.join(' ')}`.toLowerCase().includes(normalized))
  }, [endpoints, query])
  const metricItems = summary ? Object.entries(summary.metrics) : []
  return <PageIntro kicker="Consensus and discovery" title={<>The network is<br /><span>an observable system.</span></>} detail="Explore only what the Network API can verify. Every aggregate metric carries a source and an observation time; unknown is a valid state." action={<button className="button button-quiet" type="button" onClick={onRefresh}><RefreshCw size={16} /> Refresh evidence</button>}><section className="section page-width network-overview"><div className="network-state-panel" aria-live="polite"><div><p className="section-kicker">Current readiness</p><h2>{summaryState === 'loading' ? 'Checking the network…' : summary?.status === 'operational' ? 'Network signals are responding.' : 'Network evidence needs attention.'}</h2><p>{summary?.observedAt ? `Last observed ${formatObserved(summary.observedAt)}.` : 'The Website API has not returned an observation yet.'}</p></div><span className={summary?.status === 'operational' ? 'state-chip good' : 'state-chip amber'}>{summaryState === 'loading' ? 'Checking' : summary?.status ?? 'Unavailable'}</span></div><div className="metric-grid">{metricItems.length > 0 ? metricItems.map(([key, value]) => <MetricBlock key={key} label={metricLabel(key)} metric={value as NetworkMetric} />) : <UnavailableMetricGrid />}</div></section><section className="section page-width explorer-section"><div className="explorer-header"><div><p className="section-kicker">Read-only explorer</p><h2>Find a resource by what it can do.</h2></div><div className="search-field"><Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search model, provider, capability" aria-label="Search endpoints" /></div></div>{endpointState === 'error' ? <UnavailablePanel title="Endpoint discovery is unavailable" detail="The explorer is waiting for the Website API. It will not turn an empty response into a false zero." /> : filteredEndpoints.length === 0 ? <div className="empty-explorer"><Radar size={19} /><p>{endpointState === 'loading' ? 'Loading Endpoint records…' : 'No matching Endpoint records.'}</p></div> : <div className="endpoint-table" role="table" aria-label="Available endpoints"><div className="endpoint-table-head" role="row"><span role="columnheader">Model / Provider</span><span role="columnheader">Capabilities</span><span role="columnheader">Context</span><span role="columnheader">Validation</span><span role="columnheader">Price</span></div>{filteredEndpoints.map((endpoint) => <EndpointRow endpoint={endpoint} key={endpoint.id} />)}</div>}</section></PageIntro>
}

function MetricBlock({ label, metric }: { label: string; metric: NetworkMetric }) {
  return <div className="metric-block"><span className="mono-label">{label}</span><strong>{metric.value ?? 'Not reported'}</strong><small>{metric.source}{metric.observedAt ? ` · ${formatObserved(metric.observedAt)}` : ''}</small></div>
}

function UnavailableMetricGrid() {
  return <>{['Active Hypervisors', 'Active Endpoints', 'Available GPUs', 'Available VRAM', 'Models', 'Network Compute', 'Requests / 24h', 'Q Settled / 24h'].map((label) => <MetricBlock key={label} label={label} metric={{ value: null, source: 'Not reported', observedAt: null }} />)}</>
}

function EndpointRow({ endpoint }: { endpoint: EndpointSummary }) {
  return <div className="endpoint-row" role="row"><div role="cell"><strong>{endpoint.model}</strong><small>{endpoint.provider}{endpoint.operator ? ` · ${endpoint.operator}` : ''}</small></div><div className="capability-list" role="cell">{endpoint.capabilities.slice(0, 3).map((capability) => <span key={capability}>{capability}</span>)}</div><span role="cell">{endpoint.context ?? 'Not reported'}</span><span role="cell" className={`table-state ${endpoint.validation}`}>{endpoint.validation}</span><span role="cell">{endpoint.price ?? 'Not reported'}</span></div>
}

function DocsPage({ navigate }: { navigate: Navigate }) {
  const groups = [
    { title: 'Getting started', icon: Play, items: ['Install Hypervisor', 'Connect to Network', 'Get Q'] },
    { title: 'Operators', icon: ServerCog, items: ['Providers', 'Models', 'Bundles', 'Endpoints', 'Validation'] },
    { title: 'Developers', icon: Code2, items: ['API', 'CometBFT', 'MCP', 'Provider SDK', 'Bundle specification'] },
    { title: 'Network', icon: Network, items: ['Consensus', 'Q accounting', 'Validation', 'Governance'] },
  ]
  const routeForItem: Record<string, Route> = {
    'Install Hypervisor': 'run',
    'Connect to Network': 'network',
    'Get Q': 'faucet',
    Providers: 'run',
    Models: 'run',
    Bundles: 'run',
    Endpoints: 'network',
    Validation: 'network',
    API: 'build',
    CometBFT: 'build',
    MCP: 'build',
    'Provider SDK': 'build',
    'Bundle specification': 'build',
    Consensus: 'network',
    'Q accounting': 'network',
    Governance: 'network',
  }
  return <PageIntro kicker="Documentation" title={<>The shortest path from<br /><span>what is this? to done.</span></>} detail="Docs are organized around the task in front of you. Protocol specifications remain normative; this is the human route into them." action={<button className="button button-primary" type="button" onClick={() => navigate('run')}>Start as an operator <ArrowRight size={17} /></button>}>
    <section className="section page-width docs-grid">
      {groups.map(({ title, icon: Icon, items }) => <article className="docs-group" key={title}>
        <div className="docs-group-head"><span className="docs-group-icon"><Icon size={17} /></span><h2>{title}</h2></div>
        <ul>{items.map((item) => <li key={item}><button type="button" onClick={() => navigate(routeForItem[item])}>{item}<ChevronRight size={15} /></button></li>)}</ul>
      </article>)}
      <article className="docs-rfc"><div><p className="section-kicker">Specifications</p><h2>Normative detail lives here.</h2><p>When you need the exact object, state transition, or security boundary, use the RFC index alongside the implementation guides.</p></div><a className="text-link" href="https://github.com/glinko/AiDN" target="_blank" rel="noreferrer">Open GitHub <ExternalLink size={14} /></a></article>
    </section>
    <section className="section page-width docs-note"><BookOpen size={20} /><div><h2>Read the route, then inspect the contract.</h2><p>Every public website page links back to a concrete API shape, an install ref, or an operator action. If the network cannot prove a value, the UI says so.</p></div></section>
  </PageIntro>
}

function FaucetPage({ faucet, state, onRefresh }: { faucet: FaucetStatus | null; state: 'loading' | 'ready' | 'error'; onRefresh: () => void }) {
  const [step, setStep] = useState<'wallet' | 'challenge' | 'submitted'>('wallet')
  const [walletId, setWalletId] = useState('')
  const [publicKey, setPublicKey] = useState('')
  const [signature, setSignature] = useState('')
  const [challenge, setChallenge] = useState<FaucetChallenge | null>(null)
  const [result, setResult] = useState<FaucetClaimResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const walletValid = /^wallet-[0-9a-f]{12}$/.test(walletId)
  const keyValid = /^ed25519:[0-9a-f]{64}$/.test(publicKey)
  async function requestChallenge(event: FormEvent) {
    event.preventDefault()
    if (!walletValid || !keyValid) { setFormError('Use a Wallet ID like wallet-0123456789ab and an ed25519 public key.'); return }
    setBusy(true); setFormError(null)
    try { setChallenge(await issueFaucetChallenge(walletId, publicKey)); setStep('challenge') } catch (reason) { setFormError(reason instanceof Error ? reason.message : 'Could not issue a challenge') } finally { setBusy(false) }
  }
  async function submitClaim(event: FormEvent) {
    event.preventDefault()
    if (!challenge || !signature.trim()) { setFormError('Paste the signature produced by your Wallet or Hypervisor.'); return }
    setBusy(true); setFormError(null)
    try { setResult(await submitFaucetClaim({ requestId: `web-${crypto.randomUUID()}`, walletId, walletPublicKey: publicKey, challengeId: challenge.challengeId, walletSignature: signature.trim() })); setStep('submitted') } catch (reason) { setFormError(reason instanceof Error ? reason.message : 'Could not submit the Faucet claim') } finally { setBusy(false) }
  }
  return <PageIntro kicker="Web App · Faucet" title={<>Get Q for your<br /><span>first network action.</span></>} detail="The Faucet is a small testnet on-ramp. It never receives a private key: you prove Wallet control by signing a one-time challenge, then the Website Backend forwards the claim." action={<button className="button button-quiet" type="button" onClick={onRefresh}><RefreshCw size={16} /> Refresh status</button>}><section className="section page-width faucet-section"><div className="faucet-status" aria-live="polite"><div><p className="section-kicker">Public Faucet state</p><h2>{state === 'loading' ? 'Checking availability…' : faucet?.enabled ? 'Ready for an eligible Wallet.' : 'Temporarily unavailable.'}</h2><p>{faucet?.paused ? faucet.pauseReason ?? 'The operator has paused new claims.' : faucet?.lowBalanceBlocked ? 'Claims are paused while the treasury is below policy.' : 'A claim is subject to cooldown, abuse protection, budget, and network finality.'}</p></div><span className={faucet?.enabled ? 'state-chip good' : 'state-chip amber'}>{state === 'loading' ? 'Checking' : faucet?.state ?? 'Unavailable'}</span></div><div className="faucet-grid"><form className="faucet-form" onSubmit={step === 'wallet' ? requestChallenge : submitClaim}><div className="form-steps"><span className={step === 'wallet' ? 'form-step active' : 'form-step done'}>1 Wallet</span><span className={step === 'challenge' ? 'form-step active' : step === 'submitted' ? 'form-step done' : 'form-step'}>2 Prove control</span><span className={step === 'submitted' ? 'form-step active' : 'form-step'}>3 Confirmation</span></div>{step === 'wallet' ? <><Field label="Wallet ID" hint="Current format: wallet-<12 lowercase hex>" value={walletId} onChange={setWalletId} placeholder="wallet-0123456789ab" /><Field label="Wallet public key" hint="Used only to verify the relationship to the Wallet ID." value={publicKey} onChange={setPublicKey} placeholder="ed25519:…" wide /><button className="button button-primary form-submit" type="submit" disabled={busy || !faucet?.enabled}>{busy ? <RefreshCw className="spin" size={16} /> : <KeyRound size={16} />} {busy ? 'Requesting challenge…' : 'Request signing challenge'} <ArrowRight size={16} /></button></> : null}{step === 'challenge' && challenge ? <><div className="challenge-box"><div className="challenge-head"><span className="mono-label">SIGNING DOMAIN</span><span className="state-chip">Expires {formatExpires(challenge.expiresAt)}</span></div><strong>{challenge.signingDomain}</strong><code>{challenge.challenge}</code><p>Sign this exact challenge with the Wallet that owns <b>{challenge.walletId}</b>. Do not send a private key to the website.</p></div><Field label="Wallet signature" hint="Paste the returned ed25519 signature." value={signature} onChange={setSignature} placeholder="ed25519:…" wide /><div className="form-actions"><button className="button button-quiet" type="button" onClick={() => { setStep('wallet'); setChallenge(null); setSignature('') }}>Back</button><button className="button button-primary" type="submit" disabled={busy}>{busy ? <RefreshCw className="spin" size={16} /> : <ShieldCheck size={16} />} {busy ? 'Submitting…' : 'Submit claim'} <ArrowRight size={16} /></button></div></> : null}{step === 'submitted' && result ? <ClaimResult result={result} onRestart={() => { setStep('wallet'); setChallenge(null); setResult(null); setSignature('') }} /> : null}{formError ? <p className="form-error" role="alert"><CircleAlert size={15} /> {formError}</p> : null}</form><aside className="faucet-aside"><div className="faucet-amount"><span className="mono-label">AVAILABLE PER ELIGIBLE CLAIM</span><strong>{faucet?.amountQAtoms === null || faucet?.amountQAtoms === undefined ? 'Not reported' : formatQ(faucet.amountQAtoms)}</strong><small>Q · subject to current policy</small></div><div className="faucet-rules"><Rule icon={ShieldCheck} title="Proof, not a password" copy="The backend verifies a one-time signature against the public key." /><Rule icon={Gauge} title="Cooldown applies" copy={faucet?.cooldownSeconds ? `One claim per Wallet per ${Math.round(faucet.cooldownSeconds / 3600)} hours in the current policy.` : 'Current cooldown is not reported.'} /><Rule icon={Clipboard} title="Idempotent request" copy="A request ID lets the backend reconcile a retry without creating a duplicate transfer." /></div></aside></div></section></PageIntro>
}

function Field({ label, hint, value, onChange, placeholder, wide = false }: { label: string; hint: string; value: string; onChange: (value: string) => void; placeholder: string; wide?: boolean }) {
  return <label className={wide ? 'form-field wide' : 'form-field'}><span>{label}</span><input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} autoComplete="off" /><small>{hint}</small></label>
}

function Rule({ icon: Icon, title, copy }: { icon: LucideIcon; title: string; copy: string }) {
  return <div className="rule"><Icon size={16} /><div><strong>{title}</strong><p>{copy}</p></div></div>
}

function ClaimResult({ result, onRestart }: { result: FaucetClaimResult; onRestart: () => void }) {
  return <div className="claim-result"><div className="claim-result-icon"><Check size={23} /></div><p className="section-kicker">Claim submitted</p><h2>{result.status.replaceAll('_', ' ')}</h2><p>{result.detail ?? 'The claim is now tracked by the Website Backend.'}</p><div className="claim-facts"><span><small>Amount</small><b>{formatQ(result.amountQAtoms)}</b></span><span><small>Request ID</small><b>{result.requestId}</b></span><span><small>Transaction</small><b>{result.transactionHash ?? 'Pending finality'}</b></span></div><button className="text-link" type="button" onClick={onRestart}>Start another claim <ArrowUpRight size={14} /></button></div>
}

function PageIntro({ kicker, title, detail, action, children }: { kicker: string; title: ReactNode; detail: string; action: ReactNode; children: ReactNode }) {
  return <><section className="page-intro page-width"><div><p className="hero-kicker"><span className="kicker-line" /> {kicker}</p><h1>{title}</h1><p className="hero-lede">{detail}</p></div><div className="page-intro-action">{action}</div></section>{children}</>
}

function UnavailablePanel({ title, detail }: { title: string; detail: string }) {
  return <div className="unavailable-panel"><CircleAlert size={18} /><div><strong>{title}</strong><p>{detail}</p></div></div>
}

function SiteFooter({ navigate }: { navigate: Navigate }) {
  return <footer className="site-footer"><div className="page-width footer-grid"><div className="footer-brand"><button className="brand" type="button" onClick={() => navigate('home')}><BrandMark /><span>AiDN</span></button><p>Compute that starts local<br />and reaches further when needed.</p></div><FooterGroup title="Product"><button type="button" onClick={() => navigate('network')}>Network</button><button type="button" onClick={() => navigate('run')}>Run a node</button><button type="button" onClick={() => navigate('faucet')}>Faucet</button></FooterGroup><FooterGroup title="Developers"><button type="button" onClick={() => navigate('docs')}>Documentation</button><button type="button" onClick={() => navigate('build')}>MCP + API</button><a href="https://github.com/glinko/AiDN" target="_blank" rel="noreferrer">GitHub <ExternalLink size={12} /></a></FooterGroup><FooterGroup title="Project"><button type="button" onClick={() => navigate('how')}>How it works</button><button type="button" onClick={() => navigate('docs')}>Research</button><a href="https://github.com/glinko/AiDN" target="_blank" rel="noreferrer">Roadmap <ExternalLink size={12} /></a></FooterGroup></div><div className="page-width footer-bottom"><span>AiDN · public website preview</span><span>Network data is shown only when the API can verify it.</span></div></footer>
}

function FooterGroup({ title, children }: { title: string; children: ReactNode }) {
  return <div className="footer-group"><span className="mono-label">{title}</span>{children}</div>
}

function formatObserved(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.valueOf())) return 'recently'
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(date)
}

function formatExpires(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.valueOf())) return 'soon'
  return new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' }).format(date)
}

const Q_ATOMS_PER_Q = 1_000_000

function formatQ(atoms: number) {
  return `${(atoms / Q_ATOMS_PER_Q).toLocaleString(undefined, { maximumFractionDigits: 6 })} Q`
}

function metricLabel(key: string) {
  const labels: Record<string, string> = { activeHypervisors: 'Active Hypervisors', activeEndpoints: 'Active Endpoints', availableGpus: 'Available GPUs', availableVram: 'Available VRAM', models: 'Models', networkCompute: 'Network Compute', requests24h: 'Requests / 24h', qSettled24h: 'Q Settled / 24h' }
  return labels[key] ?? key
}

export default App
