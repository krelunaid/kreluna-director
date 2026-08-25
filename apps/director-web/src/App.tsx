import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  Agent,
  AIProviderOption,
  api,
  Approval,
  Overview,
  setToken,
  Task,
  token,
  UpdateStatus,
  VaultCredential,
  VaultPreview,
} from "./lib/api";

type ChatItem = { role: "user" | "director"; text: string; deny?: boolean; source?: string };

const SUGGESTIONS = [
  { short: "Fattura Gadducci", full: "Fai la fattura ad Andrea Gadducci per 35-40 mila euro di manodopera" },
  { short: "F24 IPSOA", full: "Prepara gli F24 in scadenza, ma non inviarli" },
  { short: "Contabilità", full: "Scarica le fatture in IPSOA per Gadducci" },
  { short: "Camerali", full: "Prepara la pratica camerale per Gadducci" },
  { short: "Contratti", full: "Prepara il contratto sul sito AdE di Samuele per Gadducci" },
  { short: "DURC", full: "Prepara la richiesta DURC per Gadducci" },
  { short: "Visure", full: "Prepara la visura per Gadducci" },
  { short: "Visura vera su CGN", full: "Apri il sito CGN e fai la visura vera per Gadducci" },
  { short: "DURC vero su INPS", full: "Apri il sito INPS e prepara il DURC vero per Gadducci" },
  { short: "Fermo", full: "Ferma tutto" },
];

const STARTER_REQUESTS = [
  { title: "Aprire il gestionale e compilare la fattura ad Andrea Gadducci", prompt: SUGGESTIONS[0].full, icon: "▣" },
  { title: "Imparare la pagina di Fatture su Webdesk", prompt: SUGGESTIONS[2].full, icon: "⌘" },
  { title: "Impostare la visura per Bianchi", prompt: "Prepara la visura per Bianchi", icon: "◈" },
  { title: "Preparare visura per Bianchi", prompt: "Apri il sito CGN e prepara la visura per Bianchi", icon: "△" },
  { title: "Preparare la richiesta per il certificato dei contributi", prompt: SUGGESTIONS[5].full, icon: "♙" },
];

const TASK_LABEL: Record<string, string> = {
  queued: "in attesa", assigned: "sul PC", running: "in corso", waiting_approval: "da approvare",
  completed: "fatto", failed: "errore", cancelled: "annullato", blocked: "bloccato",
};

const UPDATE_REMINDER_KEY = "kreluna.update.reminder";

function updateReminderExpired(version: string): boolean {
  try {
    const value = JSON.parse(localStorage.getItem(UPDATE_REMINDER_KEY) || "{}");
    return value.version !== version || Number(value.until || 0) <= Date.now();
  } catch {
    return true;
  }
}

function label(map: Record<string, string>, value: string): string {
  return map[value] || value.replace(/_/g, " ");
}

function currentWork(agent: Agent, tasks: Task[]): Task | undefined {
  if (agent.active_task_id) {
    const hit = tasks.find((item) => item.id === agent.active_task_id);
    if (hit) return hit;
  }
  return tasks.find((item) => item.assigned_device_id === agent.device_id && ["queued", "assigned", "running", "waiting_approval"].includes(item.status));
}

function agentState(agent: Agent, work?: Task): string {
  if (agent.killed || agent.paused) return "Fermo";
  if (work) return work.goal;
  if (agent.presence === "waiting_install") return "Da installare";
  if (agent.connected || agent.presence === "online") return agent.agent_id === "pc-visure" ? "Pronto" : "In ascolto";
  return "Spento";
}

export default function App() {
  const [ready, setReady] = useState(Boolean(token()));
  const [email, setEmail] = useState("andrea@studio.demo");
  const [password, setPassword] = useState("demo");
  const [name, setName] = useState("Studio");
  const [error, setError] = useState("");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [aiProviders, setAIProviders] = useState<AIProviderOption[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [chat, setChat] = useState<ChatItem[]>([{ role: "director", text: "Ciao Andrea, sono Kreluna, il tuo assistente IA operativo. Posso aiutarti con fatture elettroniche, F24, contabilità, pratiche camerali, contratti, DURC e visure.\n\nPer lavorare su un sito vero aggiungi «vera» o «apri il sito». Importi e nomi non li invento: se mancano, te li chiedo.\n\nNiente invii, niente pagamenti: prima chiedo Approva." }]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmKill, setConfirmKill] = useState(false);
  const [version, setVersion] = useState("");
  const [updateStatus, setUpdateStatus] = useState<UpdateStatus | null>(null);
  const [updateOpen, setUpdateOpen] = useState(false);
  const [updateInstallState, setUpdateInstallState] = useState<"idle" | "installing" | "restarting">("idle");
  const [updateInstallError, setUpdateInstallError] = useState("");
  const [lightbox, setLightbox] = useState<string | null>(null);
  const [orb, setOrb] = useState<"listen" | "think" | "talk">("listen");
  const [activeNav, setActiveNav] = useState("dashboard");
  const [deviceAction, setDeviceAction] = useState<string | null>(null);
  const [vaultOpen, setVaultOpen] = useState(false);
  const [vaultCredentials, setVaultCredentials] = useState<VaultCredential[]>([]);
  const [vaultFile, setVaultFile] = useState<File | null>(null);
  const [vaultPreview, setVaultPreview] = useState<VaultPreview | null>(null);
  const [vaultBusy, setVaultBusy] = useState(false);
  const [vaultMessage, setVaultMessage] = useState("");
  const [vaultError, setVaultError] = useState("");
  const vaultInput = useRef<HTMLInputElement | null>(null);
  const logRef = useRef<HTMLDivElement | null>(null);
  const talkTimer = useRef<number>(0);

  async function refresh() {
    const [over, ag, ts, ap, ai] = await Promise.all([api.overview(), api.agents(), api.tasks(), api.approvals(), api.aiProviders()]);
    setOverview(over); setAIProviders(ai.providers); setAgents(ag.agents); setTasks(ts.tasks); setApprovals(ap.approvals);
  }

  useEffect(() => {
    let active = true;
    const applyUpdateStatus = (status: UpdateStatus | null) => {
      if (!active || !status) return;
      setUpdateStatus(status);
      if (status?.available) {
        setUpdateOpen(updateReminderExpired(status.latest_version));
      }
    };
    Promise.all([api.health(), api.updateStatus().catch(() => null)]).then(([health, status]) => {
      if (active) setVersion(health.version);
      applyUpdateStatus(status);
    }).catch(() => undefined);
    const updateTimer = window.setInterval(() => {
      api.updateStatus().then(applyUpdateStatus).catch(() => undefined);
    }, 15 * 60 * 1000);
    return () => {
      active = false;
      window.clearInterval(updateTimer);
    };
  }, []);

  useEffect(() => {
    if (!ready) return;
    api.me().then((me) => { setName(me.name); return refresh().catch(() => undefined); }).catch(() => { setToken(null); setReady(false); });
    const timer = window.setInterval(() => refresh().catch(() => undefined), 2500);
    return () => window.clearInterval(timer);
  }, [ready]);

  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [chat, busy]);

  async function onLogin(event: FormEvent) {
    event.preventDefault(); setError("");
    try {
      const result = await api.login(email, password);
      setToken(result.token); setName(result.user.name); setReady(true);
    } catch (err) { setError(err instanceof Error ? err.message : "Login fallito"); }
  }

  async function send(text: string) {
    const message = text.trim();
    if (!message) return;
    setDraft(""); setBusy(true); setOrb("think"); setChat((items) => [...items, { role: "user", text: message }]);
    try {
      const result = await api.chat(message);
      setChat((items) => [...items, { role: "director", text: result.summary + (result.deny_reason ? `\n${result.deny_reason}` : ""), deny: result.denied, source: result.source }]);
      setOrb("talk"); window.clearTimeout(talkTimer.current); talkTimer.current = window.setTimeout(() => setOrb("listen"), 4200); await refresh();
    } catch (err) {
      setChat((items) => [...items, { role: "director", text: err instanceof Error ? err.message : "Errore Director", deny: true }]); setOrb("listen");
    } finally { setBusy(false); }
  }

  const pending = useMemo(() => approvals.filter((item) => item.status === "pending"), [approvals]);
  const blocked = useMemo(() => agents.filter((item) => item.killed || item.paused), [agents]);
  const activeErrors = useMemo(() => tasks.filter((task) => task.error_state === "active"), [tasks]);
  const requestCount = useMemo(() => tasks.filter((item) => ["queued", "assigned", "running", "waiting_approval"].includes(item.status)).length, [tasks]);
  const recentTasks = tasks.slice(0, 12);

  async function resumeAll() {
    await Promise.all(blocked.map((item) => api.resume(item.device_id).catch(() => undefined)));
    setChat((items) => [...items, { role: "director", text: "Ho ripreso i PC. Ora possono lavorare." }]); await refresh();
  }

  async function toggleAgent(agent: Agent) {
    if (agent.presence === "waiting_install" || deviceAction) return;
    setDeviceAction(agent.device_id);
    try { if (agent.killed || agent.paused) await api.resume(agent.device_id); else await api.pause(agent.device_id); await refresh(); }
    finally { setDeviceAction(null); }
  }

  async function loadVault() {
    const result = await api.vaultCredentials();
    setVaultCredentials(result.credentials);
  }

  async function openVault() {
    setVaultOpen(true); setVaultError(""); setVaultMessage("");
    try { await loadVault(); }
    catch (err) { setVaultError(err instanceof Error ? err.message : "Cassaforte non disponibile"); }
  }

  async function previewVaultFile(file: File | null) {
    if (!file) return;
    setVaultBusy(true); setVaultError(""); setVaultMessage(""); setVaultPreview(null); setVaultFile(file);
    try { setVaultPreview(await api.previewVaultCsv(file)); }
    catch (err) { setVaultFile(null); setVaultError(err instanceof Error ? err.message : "CSV non riconosciuto"); }
    finally { setVaultBusy(false); }
  }

  async function importVaultFile() {
    if (!vaultFile || !vaultPreview) return;
    setVaultBusy(true); setVaultError("");
    try {
      const result = await api.importVaultCsv(vaultFile);
      setVaultMessage(`${result.created} accessi aggiunti, ${result.updated} aggiornati${result.rejected ? `, ${result.rejected} esclusi` : ""}.`);
      setVaultFile(null); setVaultPreview(null); await loadVault();
      if (vaultInput.current) vaultInput.current.value = "";
    } catch (err) { setVaultError(err instanceof Error ? err.message : "Importazione non riuscita"); }
    finally { setVaultBusy(false); }
  }

  async function downloadVaultTemplate() {
    try {
      const blob = await api.vaultTemplate(); const url = URL.createObjectURL(blob); const link = document.createElement("a");
      link.href = url; link.download = "kreluna-cassaforte-modello.csv"; link.click(); URL.revokeObjectURL(url);
    } catch (err) { setVaultError(err instanceof Error ? err.message : "Download non riuscito"); }
  }

  async function checkVaultCredential(id: string) {
    setVaultError("");
    try { const result = await api.checkVaultCredential(id); setVaultMessage(result.detail); await loadVault(); }
    catch (err) { setVaultError(err instanceof Error ? err.message : "Controllo non riuscito"); }
  }

  async function revokeVaultCredential(id: string) {
    if (!window.confirm("Rimuovere questo accesso dalla Cassaforte?")) return;
    setVaultError("");
    try { await api.revokeVaultCredential(id); setVaultMessage("Accesso rimosso."); await loadVault(); }
    catch (err) { setVaultError(err instanceof Error ? err.message : "Rimozione non riuscita"); }
  }

  function goTo(section: string, prompt?: string, nav = section) {
    setActiveNav(nav); if (prompt) setDraft(prompt);
    window.setTimeout(() => document.getElementById(section)?.scrollIntoView({ behavior: "smooth", block: "nearest" }), 0);
  }

  function remindUpdateLater() {
    if (updateStatus) {
      localStorage.setItem(UPDATE_REMINDER_KEY, JSON.stringify({
        version: updateStatus.latest_version,
        until: Date.now() + 24 * 60 * 60 * 1000,
      }));
    }
    setUpdateOpen(false);
  }

  function downloadUpdateManually() {
    if (!updateStatus) return;
    const url = updateStatus.download_url || updateStatus.release_url;
    if (url) window.open(url, "_blank", "noopener,noreferrer");
  }

  async function waitForUpdateRestart(expectedVersion: string) {
    await new Promise((resolve) => window.setTimeout(resolve, 2500));
    let previousVersionChecks = 0;
    for (let attempt = 0; attempt < 180; attempt += 1) {
      try {
        const response = await fetch("/health", { cache: "no-store" });
        if (response.ok) {
          const health = await response.json() as { version?: string };
          if (health.version === expectedVersion) {
            window.location.reload();
            return;
          }
          if (health.version) {
            previousVersionChecks += 1;
            if (previousVersionChecks >= 5) {
              setUpdateInstallState("idle");
              setUpdateInstallError("La nuova versione non è partita. Kreluna ha riaperto la versione precedente.");
              return;
            }
          }
        }
      } catch {
        /* il programma si sta riavviando */
      }
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
    }
    setUpdateInstallState("idle");
    setUpdateInstallError("Il riavvio sta impiegando troppo tempo. Riapri Kreluna Director da Applicazioni.");
  }

  async function installUpdate() {
    if (!updateStatus || updateInstallState !== "idle") return;
    if (updateStatus.platform !== "macos") {
      downloadUpdateManually();
      return;
    }
    setUpdateInstallError("");
    setUpdateInstallState("installing");
    try {
      const result = await api.installUpdate();
      setUpdateInstallState("restarting");
      void waitForUpdateRestart(result.version);
    } catch (err) {
      setUpdateInstallState("idle");
      setUpdateInstallError(err instanceof Error ? err.message : "Aggiornamento non riuscito");
    }
  }

  if (!ready) {
    return <div className="login"><div className="login-card">
      <div className="orb listen login-orb" aria-hidden="true"><span className="orb-core" /><span className="orb-ring" /></div>
      <div className="eyebrow">Studio · Cloud</div><h1>Kreluna Director</h1>
      <p>Entra nello studio. L’intelligenza sta qui; i PC eseguono solo ciò che la policy permette.</p>
      <form onSubmit={onLogin}>
        <label>Email<input value={email} onChange={(event) => setEmail(event.target.value)} /></label>
        <label>Password<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
        {error ? <div className="error">{error}</div> : null}<button className="btn" type="submit">Entra nello studio</button>
      </form><p className="hint">Demo: andrea@studio.demo / demo{version ? ` · v${version}` : ""}</p>
    </div></div>;
  }

  const providerLabel = overview?.ai_provider_label || "IA";
  const aiConnected = overview?.ai_status === "connected";
  const updateAvailable = Boolean(updateStatus?.available);

  return <div className="director-cockpit" id="dashboard">
    <header className="cockpit-header">
      <div className="identity-card">
        <div className="orb brand-orb listen" aria-hidden="true"><span className="orb-core" /><span className="orb-ring" /></div>
        <div className="identity-copy"><h1>KRELUNA DIRECTOR</h1><p>{name} <span>•</span> active <span>•</span> v{version || "0.5.13"}</p>
          <button className={`identity-ai ${aiConnected ? "connected" : "warning"}`} onClick={() => goTo("ai-settings")}>IA: {providerLabel}{overview?.ai_model ? ` · ${overview.ai_model}` : ""}{aiConnected ? "" : " · da configurare"}</button>
        </div>
      </div>
      <div className="metric-grid" aria-label="Riepilogo">
        <Metric icon="▱" label="PC" value={`${overview?.agents_online ?? 0}/${overview?.agents_total ?? 0}`} note="Attivi" tone="blue" />
        <Metric icon="⌘" label="TASK" value={overview?.tasks_today ?? 0} note="Totali" tone="blue" />
        <Metric icon="◎" label="CORSO" value={overview?.running ?? 0} note="In corso" tone="gold" />
        <Metric icon="◉" label="APPROVA" value={overview?.pending_approvals ?? 0} note="In attesa" tone="purple" />
        <Metric icon="?" label="ERRORI" value={overview?.active_errors ?? 0} note="Da risolvere" tone="red" />
      </div>
      <div className="orbit-art" aria-hidden="true"><span className="orbit-line orbit-one" /><span className="orbit-line orbit-two" /><span className="orbit-line orbit-three" /><span className="orbit-planet"><i /></span></div>
      <div className="header-tools"><button className="approval-shortcut" onClick={() => goTo("approvals")}>Da approvare ({pending.length})</button><button className="notification" aria-label="Notifiche" onClick={() => updateStatus?.available ? setUpdateOpen(true) : goTo("errors")}>♧{activeErrors.length || updateStatus?.available ? <i /> : null}</button><button className="avatar" aria-label="Profilo">AR</button></div>
    </header>

    <div className="cockpit-body">
      <aside className="cockpit-sidebar">
        <nav aria-label="Navigazione principale">
          <NavButton active={activeNav === "dashboard"} icon="⌂" label="Dashboard" onClick={() => goTo("dashboard")} />
          <NavButton active={activeNav === "agents"} icon="▱" label="PC & Feature" onClick={() => goTo("agents")} />
          <NavButton active={activeNav === "tasks"} icon="⌘" label="Task" count={overview?.tasks_today} onClick={() => goTo("requests", undefined, "tasks")} />
          <NavButton active={activeNav === "requests"} icon="▱" label="Richieste" count={requestCount} onClick={() => goTo("requests")} />
          <NavButton active={activeNav === "errors"} icon="△" label="Errori" count={overview?.active_errors} onClick={() => goTo("errors")} />
          <NavButton icon="▤" label="Contratti" onClick={() => goTo("chat", SUGGESTIONS[4].full)} />
          <NavButton icon="▧" label="Visure" onClick={() => goTo("chat", SUGGESTIONS[6].full)} />
          <NavButton icon="▦" label="Cassaforte" count={vaultCredentials.length || undefined} onClick={() => void openVault()} />
          <NavButton icon="▤" label="Documenti" onClick={() => goTo("requests")} />
          <NavButton icon="⚙" label="Impostazioni" onClick={() => goTo("ai-settings")} />
          <button
            type="button"
            className={`sidebar-update ${updateAvailable ? "available" : "idle"}`}
            aria-label={updateAvailable ? "Aggiornamento disponibile" : "Nessun aggiornamento disponibile"}
            disabled={!updateAvailable}
            onClick={() => setUpdateOpen(true)}
          >
            <span className="sidebar-update-dot" aria-hidden="true" />
            {updateAvailable ? <strong>Aggiornamento</strong> : null}
          </button>
        </nav>
        <div className="sidebar-bottom"><div className="assistant-card"><div className={`orb sidebar-orb ${busy ? "think" : orb}`} aria-hidden="true"><span className="orb-core" /></div><div><strong>Kreluna</strong><span>{busy ? "Sta pensando" : "Ti ascolta"}</span></div></div>
          {blocked.length ? <button className="resume-all" onClick={() => void resumeAll()}>Riprendi {blocked.length} agent</button> : null}
          <button className="new-request" onClick={() => goTo("chat")}>Nuova richiesta <b>＋</b></button>
          <button className="side-logout" onClick={() => { setToken(null); setReady(false); }}>↪ <span>Chiudi sessione</span></button>
        </div>
      </aside>

      <main className="dashboard-stage">
        <section className="feature-panel" id="agents"><div className="panel-heading"><h2>PC &amp; FEATURE</h2><button className="manage-feature" onClick={() => setActiveNav("agents")}>⌘&nbsp;&nbsp; Gestisci feature</button></div>
          <div className="feature-grid" aria-label="PC dello studio">{agents.map((agent) => {
            const work = currentWork(agent, tasks); const enabled = !(agent.killed || agent.paused); const active = enabled && agent.presence !== "waiting_install";
            return <article className={`feature-card ${work ? "working" : ""} ${enabled ? "enabled" : "disabled"}`} key={agent.device_id}>
              <div className="feature-name"><span className={`status-dot ${agent.presence === "waiting_install" ? "waiting" : enabled ? "online" : "off"}`} /><strong>{agent.display_name || agent.agent_id}</strong>
                <button className={`mini-switch ${active ? "on" : "off"}`} disabled={agent.presence === "waiting_install" || deviceAction === agent.device_id} onClick={() => void toggleAgent(agent)} title={agent.presence === "waiting_install" ? "Installa prima l’Agent" : enabled ? "Disattiva Agent" : "Attiva Agent"} aria-label={`${agent.presence === "waiting_install" ? "Installa prima" : enabled ? "Disattiva" : "Attiva"} ${agent.display_name || agent.agent_id}`} aria-pressed={active}><i /></button>
              </div><p>{agent.job}</p><span title="Disponibile per Mac e Windows">{agentState(agent, work)} · Mac/PC</span>
            </article>;
          })}</div>
        </section>

        <div className="work-grid">
          <section className="kreluna-panel" id="chat">
            <div className="kreluna-heading"><div className={`orb chat-orb ${busy ? "think" : orb}`} aria-hidden="true"><span className="orb-core" /><span className="orb-ring" /></div><h2>Kreluna</h2><span className={`ai-active ${aiConnected ? "connected" : "warning"}`}>{aiConnected ? "IA attiva" : "IA da configurare"}</span>
              <label className="provider-compact" id="ai-settings"><select value={overview?.ai_provider || "openai"} onChange={async (event) => { await api.chooseAIProvider(event.target.value); await refresh(); }} aria-label="Provider IA">{aiProviders.map((item) => <option key={item.provider} value={item.provider}>{item.label}{item.configured ? "" : " · da configurare"}</option>)}</select></label>
            </div>
            {!aiConnected ? <div className="ai-diagnostic" title={overview?.ai_detail || "Configurazione incompleta"}><strong>{providerLabel}</strong>: {overview?.ai_detail || "modello o chiave API mancanti"}. Nessun fallback silenzioso.</div> : null}
            <div className="chat-log" ref={logRef}>{chat.map((item, index) => <div key={index} className={`msg ${item.role} ${item.deny ? "deny" : ""}`}><strong>{item.role === "user" ? "Tu" : `Kreluna${item.source ? item.source.startsWith("llm") ? " · IA" : " · Regole" : ""}`}</strong><div>{item.text}</div></div>)}{busy ? <div className="typing"><i /><i /><i /></div> : null}</div>
            <div className="chips">{SUGGESTIONS.map((item) => <button key={item.full} className="chip" onClick={() => void send(item.full)} disabled={busy}>{item.short}</button>)}</div>
            <form className="composer" onSubmit={(event) => { event.preventDefault(); void send(draft); }}><span className="mic">♩</span><textarea value={draft} placeholder="Clicca Fattura Gadducci, oppure scrivi qui…" onChange={(event) => setDraft(event.target.value)} /><button className="send-button" disabled={busy} aria-label="Invia">➤</button></form>
          </section>

          <aside className="requests-panel" id="requests"><div className="requests-heading"><h2>RICHIESTE</h2><select aria-label="Filtra richieste"><option>Tutte</option><option>In corso</option><option>Errori</option></select></div>
            <div className="request-list">
              {pending.map((item) => { const observed = ((item.preview.observed as Record<string, string>) || {}) as Record<string, string>; return <article className="request-row approval-row" id="approvals" key={item.id}><span className="request-icon">◉</span><div className="request-copy"><strong>Approvare {observed.client || "fattura"}</strong><span>{observed.total_label || "Operazione in attesa"}</span></div><div className="request-actions"><button onClick={() => api.approve(item.id).then(refresh)}>Approva</button><button onClick={() => api.reject(item.id).then(refresh)}>No</button></div></article>; })}
              {recentTasks.map((task) => <article className={`request-row ${task.status}`} id={task.error_state === "active" ? "errors" : undefined} key={task.id}><span className={`request-icon ${task.status}`}>{task.status === "failed" ? "△" : "▣"}</span><div className="request-copy"><strong title={task.goal}>{task.goal}</strong><EvidenceStrip ids={task.evidence.map((shot) => shot.id)} onOpen={setLightbox} />{task.error ? <span className="request-error">{task.error}</span> : null}</div><div className="request-meta"><span className={`request-status ${task.status}`}>{label(TASK_LABEL, task.status)}</span>{task.created_at ? <time>{new Date(task.created_at).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" })}</time> : null}{task.status === "queued" || task.status === "assigned" ? <button onClick={() => api.cancelTask(task.id).then(refresh)}>Annulla</button> : null}</div></article>)}
              {!recentTasks.length && !pending.length ? STARTER_REQUESTS.map((item, index) => <button className="request-row starter-row" key={item.title} onClick={() => { setDraft(item.prompt); goTo("chat"); }}><span className={`request-icon starter-${index}`}>{item.icon}</span><span className="request-copy"><strong>{item.title}</strong><span className="preview-strip"><i /><i /><i /><i /></span></span><span className="request-meta"><span className="request-status starter">Avvia</span><time>pronto</time></span></button>) : null}
            </div><button className="show-all" onClick={() => setActiveNav("requests")}>Mostra tutte le richieste <span>→</span></button>
          </aside>
        </div>
      </main>
    </div>

    <footer className="cockpit-footer"><span>◉&nbsp; Sistema: macOS</span><span>▣&nbsp; Host: questo Mac</span><span>♙&nbsp; Utente: {name}</span><span>◷&nbsp; Sessione attiva</span><span className={aiConnected ? "healthy" : "warning"}>●&nbsp; {aiConnected ? "Tutti i sistemi operativi" : `${providerLabel} da configurare`}</span></footer>
    {confirmKill ? <div className="kill-confirm" role="dialog" aria-modal="true" aria-label="Conferma stop"><div><h2>Fermare tutti gli Agent?</h2><p>I lavori in corso torneranno in attesa.</p><button onClick={() => setConfirmKill(false)}>Annulla</button><button className="danger" onClick={async () => { await api.kill(); setConfirmKill(false); await refresh(); }}>Conferma stop</button></div></div> : null}
    {vaultOpen ? <div className="vault-dialog" role="dialog" aria-modal="true" aria-labelledby="vault-title"><div className="vault-card">
      <div className="vault-heading"><div><span className="vault-eyebrow">CASSAFORTE CLIENTI</span><h2 id="vault-title">Accessi protetti per cliente</h2><p>Il CSV viene riconosciuto nel Director. Password e token sono cifrati e non vengono inviati a Grok.</p></div><button className="vault-close" aria-label="Chiudi Cassaforte" onClick={() => setVaultOpen(false)}>×</button></div>
      <div className="vault-toolbar"><input ref={vaultInput} type="file" accept=".csv,text/csv" hidden onChange={(event) => void previewVaultFile(event.target.files?.[0] || null)} /><button className="primary" disabled={vaultBusy} onClick={() => vaultInput.current?.click()}>{vaultBusy ? "Riconosco il CSV…" : "Importa CSV"}</button><button disabled={vaultBusy} onClick={() => void downloadVaultTemplate()}>Scarica modello</button><span>🔒 Nessun segreto mostrato</span></div>
      {vaultError ? <div className="vault-alert error" role="alert">{vaultError}</div> : null}{vaultMessage ? <div className="vault-alert success">{vaultMessage}</div> : null}
      {vaultPreview ? <section className="vault-preview"><div><strong>{vaultPreview.recognized} accessi riconosciuti</strong><span>{vaultPreview.warnings.length ? ` · ${vaultPreview.warnings.length} righe da correggere` : " · CSV pronto"}</span></div><div className="vault-preview-list">{vaultPreview.rows.slice(0, 8).map((row) => <span key={`${row.row_number}-${row.client_name}-${row.portal}`}><b>{row.client_name}</b><i>{row.portal}</i><em>{row.username_masked}</em></span>)}</div><div className="vault-preview-actions"><button onClick={() => { setVaultFile(null); setVaultPreview(null); }}>Annulla</button><button className="primary" disabled={vaultBusy} onClick={() => void importVaultFile()}>Cifra e importa</button></div></section> : null}
      <div className="vault-list">{vaultCredentials.map((item) => <article className="vault-row" key={item.id}><div className={`vault-lock ${item.status}`}>◆</div><div><strong>{item.client_name}</strong><span>{item.portal} · {item.credential_label}</span></div><div className="vault-user"><span>{item.username_masked}</span><small>{item.secret_kind.replace(/_/g, " ")}</small></div><div className="vault-actions"><button onClick={() => void checkVaultCredential(item.id)}>Controlla</button><button className="danger-text" onClick={() => void revokeVaultCredential(item.id)}>Rimuovi</button></div></article>)}{!vaultCredentials.length && !vaultPreview ? <div className="vault-empty"><strong>Nessun accesso ancora caricato</strong><span>Usa il modello CSV: cliente, portale, username e password/token.</span></div> : null}</div>
      <div className="vault-safety"><strong>Barriere sempre attive</strong><span>Niente SPID/CNS automatico · niente invio fatture, F24, PEC o pagamenti · OTP inserito dalla persona.</span></div>
    </div></div> : null}
    <button className="global-stop" onClick={() => setConfirmKill(true)} title="Ferma tutti gli Agent">■</button>
    {updateStatus?.available && !updateOpen ? <button className="update-note" onClick={() => setUpdateOpen(true)}>↑ Kreluna {updateStatus.latest_version} disponibile</button> : null}
    {updateOpen && updateStatus ? <div className="update-dialog" role="dialog" aria-modal="true" aria-labelledby="update-title"><div className="update-card">
      <div className="update-orb" aria-hidden="true">↑</div>
      <span className="update-eyebrow">AGGIORNAMENTO SOFTWARE</span>
      <h2 id="update-title">Kreluna {updateStatus.latest_version} è disponibile</h2>
      <p>Ora stai usando la versione {updateStatus.current_version}. I dati dello studio e la configurazione restano al loro posto.</p>
      {updateStatus.notes ? <div className="update-notes"><strong>Novità</strong><span>{updateStatus.notes}</span></div> : null}
      {updateInstallState === "installing" ? <div className="update-progress">Scarico e verifico l’aggiornamento…</div> : null}
      {updateInstallState === "restarting" ? <div className="update-progress success">Installato. Kreluna si sta riavviando…</div> : null}
      {updateInstallError ? <div className="update-install-error" role="alert">{updateInstallError}</div> : null}
      <div className="update-actions">
        <button onClick={remindUpdateLater} disabled={updateInstallState !== "idle"}>Ricordamelo dopo</button>
        <button className="primary" onClick={() => void installUpdate()} disabled={updateInstallState !== "idle"}>{updateStatus.platform === "macos" ? "Installa ora" : "Scarica aggiornamento"}</button>
        {updateInstallError ? <button onClick={downloadUpdateManually}>Scarica manualmente</button> : null}
      </div>
      <small>Su Mac l’app viene verificata, sostituita in Applicazioni e riaperta automaticamente.</small>
    </div></div> : null}
    {lightbox ? <button className="lightbox" onClick={() => setLightbox(null)}><img src={lightbox} alt="Schermata del PC" /></button> : null}
  </div>;
}

function NavButton({ active = false, icon, label, count, onClick }: { active?: boolean; icon: string; label: string; count?: number; onClick: () => void }) {
  return <button className={active ? "active" : ""} onClick={onClick}><span>{icon}</span><strong>{label}</strong>{count ? <b>{count}</b> : null}</button>;
}

function Metric({ icon, label, value, note, tone }: { icon: string; label: string; value: string | number; note: string; tone: string }) {
  return <div className={`metric ${tone}`}><div><span className="metric-icon">{icon}</span><strong>{label}</strong></div><b>{value}</b><small>{note}</small></div>;
}

function EvidenceStrip({ ids, onOpen }: { ids: string[]; onOpen: (src: string) => void }) {
  if (!ids.length) return null;
  const shown = ids.slice(-3).reverse();
  return <div className="thumbs">{shown.map((id) => <EvidenceThumb key={id} id={id} onOpen={onOpen} />)}{ids.length > 3 ? <span>+{ids.length - 3}</span> : null}</div>;
}

function EvidenceThumb({ id, onOpen }: { id: string; onOpen: (src: string) => void }) {
  const [src, setSrc] = useState<string>();
  useEffect(() => {
    let objectUrl = ""; const current = token(); if (!current) return;
    fetch(`/evidence/${id}/image`, { headers: { Authorization: `Bearer ${current}` } }).then((response) => response.ok ? response.blob() : Promise.reject(new Error("no image"))).then((blob) => { objectUrl = URL.createObjectURL(blob); setSrc(objectUrl); }).catch(() => undefined);
    return () => { if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [id]);
  if (!src) return null;
  return <button type="button" className="thumb" onClick={() => onOpen(src)}><img src={src} alt="" /></button>;
}
