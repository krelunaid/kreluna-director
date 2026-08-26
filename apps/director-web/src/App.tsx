import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  Agent,
  AIProviderOption,
  api,
  Approval,
  Overview,
  setVaultGrant,
  setToken,
  Task,
  token,
  tokenIsPersistent,
  UpdateStatus,
  VaultCredential,
  VaultCredentialInput,
  VaultPreview,
} from "./lib/api";

type ChatItem = { role: "user" | "director"; text: string; deny?: boolean; source?: string };
type NavSection = "dashboard" | "agents" | "tasks" | "requests" | "errors" | "contracts" | "visure" | "vault" | "documents" | "settings";
type RequestFilter = "all" | "active" | "errors" | "approvals";

const INITIAL_CHAT: ChatItem[] = [{ role: "director", text: "Ciao Andrea, sono Kreluna, il tuo assistente IA operativo. Posso aiutarti con fatture elettroniche, F24, contabilità, pratiche camerali, contratti, DURC e visure.\n\nPer lavorare su un sito vero aggiungi «vera» o «apri il sito». Importi e nomi non li invento: se mancano, te li chiedo.\n\nNiente invii, niente pagamenti: prima chiedo Approva." }];

function chatSource(item: ChatItem): string {
  if (!item.source) return "";
  if (item.source.startsWith("llm")) return " · IA";
  if (item.deny || item.source === "deterministic-kill") return " · Sicurezza";
  return "";
}

const SUGGESTIONS = [
  { short: "Fattura Gadducci", full: "Fai la fattura ad Andrea Gadducci per 35-40 mila euro di manodopera" },
  { short: "F24 IPSOA", full: "Prepara gli F24 in scadenza, ma non inviarli" },
  { short: "Contabilità", full: "Scarica le fatture in IPSOA per Gadducci" },
  { short: "Camerali", full: "Prepara la pratica camerale per Gadducci" },
  { short: "Contratti", full: "Prepara una bozza di contratto per il cliente indicato, senza inviarla" },
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
const EMPTY_VAULT_FORM: VaultCredentialInput = {
  client_name: "",
  portal: "",
  portal_url: "",
  username: "",
  secret: "",
  secret_kind: "password",
  credential_label: "principale",
};

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

function agentOnline(agent: Agent): boolean {
  return agent.connected && ["online", "busy"].includes(agent.presence);
}

function agentState(agent: Agent, work?: Task): string {
  if (agent.killed || agent.paused) return "Fermo";
  if (agent.presence === "waiting_install") return "Da installare";
  if (!agentOnline(agent)) return "Spento — apri Kreluna Agent";
  if (work) return work.goal;
  return agent.agent_id === "pc-visure" ? "Pronto" : "In ascolto";
}

export default function App() {
  const [ready, setReady] = useState(Boolean(token()));
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [rememberDevice, setRememberDevice] = useState(true);
  const [name, setName] = useState("Studio");
  const [error, setError] = useState("");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [aiProviders, setAIProviders] = useState<AIProviderOption[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [chat, setChat] = useState<ChatItem[]>(INITIAL_CHAT);
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
  const [activeNav, setActiveNav] = useState<NavSection>("dashboard");
  const [requestFilter, setRequestFilter] = useState<RequestFilter>("all");
  const [deviceAction, setDeviceAction] = useState<string | null>(null);
  const [enrollment, setEnrollment] = useState<{
    agentId: string;
    displayName: string;
    code: string;
    expiresAt: string;
  } | null>(null);
  const [enrollmentError, setEnrollmentError] = useState("");
  const [vaultOpen, setVaultOpen] = useState(false);
  const [vaultUnlocked, setVaultUnlocked] = useState(false);
  const [vaultPinConfigured, setVaultPinConfigured] = useState<boolean | null>(null);
  const [vaultPin, setVaultPin] = useState("");
  const [vaultPinConfirm, setVaultPinConfirm] = useState("");
  const [vaultUnlockBusy, setVaultUnlockBusy] = useState(false);
  const [vaultRetryAfter, setVaultRetryAfter] = useState(0);
  const [vaultCredentials, setVaultCredentials] = useState<VaultCredential[]>([]);
  const [vaultFile, setVaultFile] = useState<File | null>(null);
  const [vaultPreview, setVaultPreview] = useState<VaultPreview | null>(null);
  const [vaultBusy, setVaultBusy] = useState(false);
  const [vaultMessage, setVaultMessage] = useState("");
  const [vaultError, setVaultError] = useState("");
  const [vaultFormOpen, setVaultFormOpen] = useState(false);
  const [vaultEditingId, setVaultEditingId] = useState<string | null>(null);
  const [vaultForm, setVaultForm] = useState<VaultCredentialInput>({ ...EMPTY_VAULT_FORM });
  const [aiSettingsOpen, setAISettingsOpen] = useState(false);
  const [aiSettingsProvider, setAISettingsProvider] = useState<AIProviderOption["provider"]>("grok");
  const [aiSettingsModel, setAISettingsModel] = useState("grok-4.6");
  const [aiSettingsKey, setAISettingsKey] = useState("");
  const [aiSettingsBusy, setAISettingsBusy] = useState(false);
  const [aiSettingsError, setAISettingsError] = useState("");
  const [aiSettingsMessage, setAISettingsMessage] = useState("");
  const vaultInput = useRef<HTMLInputElement | null>(null);
  const logRef = useRef<HTMLDivElement | null>(null);
  const talkTimer = useRef<number>(0);
  const vaultLockTimer = useRef<number>(0);
  const refreshInFlight = useRef<Promise<void> | null>(null);

  function refresh(): Promise<void> {
    if (refreshInFlight.current) return refreshInFlight.current;
    const request = Promise.all([api.overview(), api.agents(), api.tasks(), api.approvals(), api.aiProviders()])
      .then(([over, ag, ts, ap, ai]) => {
        setOverview(over); setAIProviders(ai.providers); setAgents(ag.agents); setTasks(ts.tasks); setApprovals(ap.approvals);
      })
      .finally(() => {
        refreshInFlight.current = null;
      });
    refreshInFlight.current = request;
    return request;
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
    const persistent = tokenIsPersistent();
    api.me().then(async (me) => {
      setName(me.name);
      const renewed = await api.refreshSession(persistent).catch(() => null);
      if (renewed) setToken(renewed.token, persistent);
      return refresh().catch(() => undefined);
    }).catch(() => { setToken(null); setReady(false); });
    const timer = window.setInterval(() => refresh().catch(() => undefined), 2500);
    return () => window.clearInterval(timer);
  }, [ready]);

  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [chat, busy]);

  useEffect(() => {
    if (!vaultOpen || vaultRetryAfter <= 0) return;
    const timer = window.setInterval(
      () => setVaultRetryAfter((value) => Math.max(0, value - 1)),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [vaultOpen, vaultRetryAfter]);

  async function onLogin(event: FormEvent) {
    event.preventDefault(); setError("");
    try {
      const result = await api.login(email, password, rememberDevice);
      setToken(result.token, rememberDevice); setName(result.user.name); setReady(true);
    } catch (err) { setError(err instanceof Error ? err.message : "Login fallito"); }
  }

  async function send(text: string) {
    const message = text.trim();
    if (!message) return;
    const history = chat.slice(-8).map((item) => ({
      role: item.role === "user" ? "user" as const : "assistant" as const,
      content: item.text,
    }));
    setDraft(""); setBusy(true); setOrb("think"); setChat((items) => [...items, { role: "user", text: message }]);
    try {
      const result = await api.chat(message, history);
      setChat((items) => [...items, { role: "director", text: result.summary + (result.deny_reason ? `\n${result.deny_reason}` : ""), deny: result.denied, source: result.source }]);
      setOrb("talk"); window.clearTimeout(talkTimer.current); talkTimer.current = window.setTimeout(() => setOrb("listen"), 4200); await refresh();
    } catch (err) {
      setChat((items) => [...items, { role: "director", text: err instanceof Error ? err.message : "Errore Director", deny: true }]); setOrb("listen");
    } finally { setBusy(false); }
  }

  function newRequest() {
    setChat(INITIAL_CHAT);
    setDraft("");
    setOrb("listen");
    void api.resetChat().catch(() => undefined);
    openComposer("");
  }

  const pending = useMemo(() => approvals.filter((item) => item.status === "pending"), [approvals]);
  const blocked = useMemo(() => agents.filter((item) => item.killed || item.paused), [agents]);
  const activeErrors = useMemo(() => tasks.filter((task) => task.error_state === "active"), [tasks]);
  const historicalErrors = useMemo(() => tasks.filter((task) => task.error_state === "historical"), [tasks]);
  const requestCount = useMemo(() => tasks.filter((item) => ["queued", "assigned", "running", "waiting_approval"].includes(item.status)).length, [tasks]);
  const recentTasks = useMemo(() => tasks.slice(0, 12), [tasks]);
  const dashboardTasks = useMemo(() => {
    if (requestFilter === "active") return tasks.filter((item) => ["queued", "assigned", "running", "waiting_approval"].includes(item.status)).slice(0, 12);
    if (requestFilter === "errors") return tasks.filter((item) => item.error_state === "active").slice(0, 12);
    if (requestFilter === "approvals") return [];
    return recentTasks;
  }, [requestFilter, recentTasks, tasks]);

  async function resumeAll() {
    await Promise.all(blocked.map((item) => api.resume(item.device_id).catch(() => undefined)));
    setChat((items) => [...items, { role: "director", text: "Ho ripreso i PC. Ora possono lavorare." }]); await refresh();
  }

  async function toggleAgent(agent: Agent) {
    if (deviceAction) return;
    setDeviceAction(agent.device_id);
    try {
      if (agent.presence === "waiting_install") {
        setEnrollmentError("");
        const issued = await api.issueAgentEnrollment(agent.agent_id);
        setEnrollment({
          agentId: issued.agent_id,
          displayName: agent.display_name || agent.agent_id,
          code: issued.enrollment_code,
          expiresAt: issued.expires_at,
        });
      } else if (agent.killed || agent.paused) await api.resume(agent.device_id);
      else await api.pause(agent.device_id);
      await refresh();
    } catch (err) {
      setEnrollmentError(err instanceof Error ? err.message : "Codice Agent non disponibile");
    }
    finally { setDeviceAction(null); }
  }

  async function loadVault() {
    const result = await api.vaultCredentials();
    setVaultCredentials(result.credentials);
  }

  async function openVault() {
    window.clearTimeout(vaultLockTimer.current); setVaultGrant(null);
    setActiveNav("vault"); setVaultOpen(true); setVaultUnlocked(false);
    setVaultPin(""); setVaultPinConfirm(""); setVaultPinConfigured(null);
    setVaultError(""); setVaultMessage(""); setVaultCredentials([]);
    try {
      const status = await api.vaultPinStatus();
      setVaultPinConfigured(status.configured); setVaultRetryAfter(status.retry_after);
    } catch (err) { setVaultError(err instanceof Error ? err.message : "Fort Knox non disponibile"); }
  }

  function closeVault() {
    window.clearTimeout(vaultLockTimer.current); setVaultGrant(null);
    setVaultOpen(false); setVaultFormOpen(false); setVaultEditingId(null);
    setVaultForm({ ...EMPTY_VAULT_FORM }); setVaultFile(null); setVaultPreview(null);
    setVaultUnlocked(false); setVaultPin(""); setVaultPinConfirm("");
    setActiveNav("dashboard");
  }

  function addVaultPinDigit(digit: string) {
    if (vaultUnlockBusy) return;
    if (vaultPinConfigured === false && vaultPin.length === 6) {
      setVaultPinConfirm((value) => (value + digit).slice(0, 6));
    } else {
      setVaultPin((value) => (value + digit).slice(0, 6));
    }
    setVaultError("");
  }

  function removeVaultPinDigit() {
    if (vaultPinConfirm) setVaultPinConfirm((value) => value.slice(0, -1));
    else setVaultPin((value) => value.slice(0, -1));
    setVaultError("");
  }

  async function unlockVault(event?: FormEvent) {
    event?.preventDefault();
    if (vaultPin.length !== 6) { setVaultError("Inserisci tutte le 6 cifre del PIN."); return; }
    if (vaultPinConfigured === false && vaultPinConfirm !== vaultPin) {
      setVaultError("I due PIN non coincidono."); return;
    }
    setVaultUnlockBusy(true); setVaultError("");
    try {
      if (vaultPinConfigured === false) {
        await api.configureVaultPin(vaultPin); setVaultPinConfigured(true);
      }
      const result = await api.unlockVault(vaultPin);
      setVaultGrant(result.grant); setVaultUnlocked(true); setVaultPin(""); setVaultPinConfirm("");
      await loadVault();
      window.clearTimeout(vaultLockTimer.current);
      vaultLockTimer.current = window.setTimeout(() => {
        setVaultGrant(null); setVaultUnlocked(false); setVaultCredentials([]);
        setVaultMessage(""); setVaultError("Fort Knox si è richiuso automaticamente. Inserisci di nuovo il PIN.");
      }, result.expires_in * 1000);
    } catch (err) {
      setVaultPin(""); setVaultPinConfirm("");
      setVaultError(err instanceof Error ? err.message : "Apertura non riuscita");
      const status = await api.vaultPinStatus().catch(() => null);
      if (status) setVaultRetryAfter(status.retry_after);
    } finally { setVaultUnlockBusy(false); }
  }

  function newVaultCredential() {
    setVaultEditingId(null); setVaultForm({ ...EMPTY_VAULT_FORM });
    setVaultFormOpen(true); setVaultError(""); setVaultMessage("");
  }

  function editVaultCredential(item: VaultCredential) {
    setVaultEditingId(item.id);
    setVaultForm({
      client_name: item.client_name,
      portal: item.portal,
      portal_url: item.portal_url,
      username: "",
      secret: "",
      secret_kind: item.secret_kind as VaultCredentialInput["secret_kind"],
      credential_label: item.credential_label,
    });
    setVaultFormOpen(true); setVaultError(""); setVaultMessage("");
  }

  function closeVaultForm() {
    setVaultFormOpen(false); setVaultEditingId(null); setVaultForm({ ...EMPTY_VAULT_FORM });
  }

  async function saveVaultCredential(event: FormEvent) {
    event.preventDefault(); setVaultBusy(true); setVaultError(""); setVaultMessage("");
    try {
      if (vaultEditingId) await api.updateVaultCredential(vaultEditingId, vaultForm);
      else await api.createVaultCredential(vaultForm);
      const action = vaultEditingId ? "aggiornato" : "salvato";
      closeVaultForm(); await loadVault();
      setVaultMessage(`Accesso ${action} in Fort Knox. La password non verrà mai mostrata.`);
    } catch (err) { setVaultError(err instanceof Error ? err.message : "Salvataggio non riuscito"); }
    finally { setVaultBusy(false); }
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
    setVaultError(""); setVaultMessage("");
    try {
      const blob = await api.vaultTemplate(); const url = URL.createObjectURL(blob); const link = document.createElement("a");
      link.href = url; link.download = "kreluna-fort-knox-modello.csv";
      document.body.appendChild(link); link.click(); link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 2000);
      setVaultMessage("Modello CSV salvato nella cartella Download.");
    } catch (err) { setVaultError(err instanceof Error ? err.message : "Download non riuscito"); }
  }

  async function checkVaultCredential(id: string) {
    setVaultError("");
    try { const result = await api.checkVaultCredential(id); setVaultMessage(result.detail); await loadVault(); }
    catch (err) { setVaultError(err instanceof Error ? err.message : "Controllo non riuscito"); }
  }

  async function revokeVaultCredential(id: string) {
    if (!window.confirm("Rimuovere questo accesso da Fort Knox?")) return;
    setVaultError("");
    try { await api.revokeVaultCredential(id); setVaultMessage("Accesso rimosso."); await loadVault(); }
    catch (err) { setVaultError(err instanceof Error ? err.message : "Rimozione non riuscita"); }
  }

  function openAISettings(provider = overview?.ai_provider || "grok") {
    const option = aiProviders.find((item) => item.provider === provider);
    setAISettingsProvider(provider);
    setAISettingsModel(option?.model || (provider === "grok" ? "grok-4.6" : ""));
    setAISettingsKey("");
    setAISettingsError("");
    setAISettingsMessage("");
    setAISettingsOpen(true);
  }

  function closeAISettings() {
    setAISettingsOpen(false);
    setAISettingsKey("");
    setAISettingsError("");
    setAISettingsMessage("");
  }

  function changeAISettingsProvider(provider: AIProviderOption["provider"]) {
    const option = aiProviders.find((item) => item.provider === provider);
    setAISettingsProvider(provider);
    setAISettingsModel(option?.model || (provider === "grok" ? "grok-4.6" : ""));
    setAISettingsKey("");
    setAISettingsError("");
    setAISettingsMessage("");
  }

  async function saveAISettings(event: FormEvent) {
    event.preventDefault();
    setAISettingsBusy(true); setAISettingsError(""); setAISettingsMessage("");
    try {
      const option = aiProviders.find((item) => item.provider === aiSettingsProvider);
      const result = option?.managed
        ? await api.chooseAIProvider(aiSettingsProvider)
        : await api.configureAI(aiSettingsProvider, aiSettingsModel, aiSettingsKey);
      setAISettingsKey("");
      if (result.connected) setAISettingsMessage(`${result.label} è collegato e pronto.`);
      else setAISettingsError(result.detail);
      await refresh();
    } catch (err) {
      setAISettingsError(err instanceof Error ? err.message : "Configurazione IA non riuscita");
    } finally { setAISettingsBusy(false); }
  }

  function goTo(section: NavSection, prompt?: string) {
    setActiveNav(section); if (prompt) setDraft(prompt);
  }

  function openComposer(prompt: string) {
    setDraft(prompt); setActiveNav("dashboard");
    window.setTimeout(() => document.querySelector<HTMLTextAreaElement>(".composer textarea")?.focus(), 0);
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
        <label className="remember-device"><input type="checkbox" checked={rememberDevice} onChange={(event) => setRememberDevice(event.target.checked)} /><span>Resta collegato su questo computer</span></label>
        {error ? <div className="error">{error}</div> : null}<button className="btn" type="submit">Entra nello studio</button>
      </form><p className="hint">La password non viene salvata{version ? ` · v${version}` : ""}</p>
    </div></div>;
  }

  const providerLabel = overview?.ai_provider_label || "IA";
  const aiConnected = overview?.ai_status === "connected";
  const activeProvider = aiProviders.find((item) => item.provider === overview?.ai_provider);
  const aiManaged = Boolean(activeProvider?.managed);
  const settingsProvider = aiProviders.find((item) => item.provider === aiSettingsProvider);
  const settingsManaged = Boolean(settingsProvider?.managed);
  const aiUnavailable = aiManaged ? "licenza non attiva" : "da configurare";
  const identityAILabel = aiManaged
    ? `IA Kreluna · ${aiConnected ? "attiva" : aiUnavailable}`
    : `IA: ${providerLabel}${overview?.ai_model ? ` · ${overview.ai_model}` : ""}${aiConnected ? "" : ` · ${aiUnavailable}`}`;
  const updateAvailable = Boolean(updateStatus?.available);
  const activeTasks = tasks.filter((item) => ["queued", "assigned", "running", "waiting_approval"].includes(item.status));
  const contractTasks = tasks.filter((item) => item.capability.includes("contratt") || String(item.args.portal || "").toLowerCase().includes("contratt"));
  const visureTasks = tasks.filter((item) => item.capability.includes("visur") || String(item.args.portal || "").toLowerCase().includes("visur") || String(item.args.portal || "").toLowerCase().includes("cgn"));
  const documentTasks = tasks.filter((item) => item.capability.includes("document") || item.evidence.length > 0);

  function taskRows(rows: Task[], empty: string) {
    if (!rows.length) return <div className="workspace-empty"><strong>Nessun elemento</strong><span>{empty}</span></div>;
    return <div className="workspace-list">{rows.map((task) => <article className={`workspace-row ${task.status}`} key={task.id}>
      <span className={`workspace-row-icon ${task.status}`}>{task.status === "failed" || task.error_state === "active" ? "△" : "▣"}</span>
      <div className="workspace-row-copy"><strong>{task.goal}</strong><span>{task.capability.replace(/_/g, " ")} · rischio {task.risk}</span>{task.error ? <small className="request-error">{task.error}</small> : null}<EvidenceStrip ids={task.evidence.map((shot) => shot.id)} onOpen={setLightbox} /></div>
      <div className="workspace-row-meta"><span className={`request-status ${task.status}`}>{label(TASK_LABEL, task.status)}</span>{task.created_at ? <time>{new Date(task.created_at).toLocaleString("it-IT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</time> : null}{["queued", "assigned"].includes(task.status) ? <button onClick={() => api.cancelTask(task.id).then(refresh)}>Annulla</button> : null}</div>
    </article>)}</div>;
  }

  function workspacePage() {
    if (activeNav === "agents") return <section className="workspace-page" aria-labelledby="workspace-title">
      <div className="workspace-heading"><div><span>CONTROLLO LOCALE</span><h2 id="workspace-title">PC &amp; FEATURE</h2><p>Installa, attiva o sospendi gli Agent autorizzati dello studio.</p></div><button onClick={() => void refresh()}>↻ Aggiorna stato</button></div>
      <div className="workspace-stats"><WorkspaceStat value={agents.filter(agentOnline).length} label="PC collegati" tone="green" /><WorkspaceStat value={agents.filter((item) => item.presence === "waiting_install").length} label="Da installare" tone="gold" /><WorkspaceStat value={blocked.length} label="Sospesi" tone="red" /></div>
      <div className="agent-workspace-grid">{agents.map((agent) => {
        const work = currentWork(agent, tasks); const waiting = agent.presence === "waiting_install"; const online = agentOnline(agent); const enabled = !(agent.killed || agent.paused); const offlineEnabled = !waiting && !online && enabled;
        return <article className={`agent-workspace-card ${online && enabled ? "online" : ""}`} key={agent.device_id}><div><span className={`status-dot ${waiting ? "waiting" : online && enabled ? "online" : "off"}`} /><strong>{agent.display_name || agent.agent_id}</strong><em>{agent.platform || "Mac/PC"}</em></div><h3>{agent.job}</h3><p>{agentState(agent, work)}</p><small>{agent.hostname || "Computer non ancora associato"}</small><button disabled={deviceAction === agent.device_id || offlineEnabled} onClick={() => void toggleAgent(agent)}>{waiting ? "Installa Agent" : offlineEnabled ? "Apri Kreluna Agent sul PC" : enabled ? "Disattiva" : "Attiva"}</button></article>;
      })}</div>
    </section>;

    if (activeNav === "tasks") return <section className="workspace-page" aria-labelledby="workspace-title"><div className="workspace-heading"><div><span>CRONOLOGIA OPERATIVA</span><h2 id="workspace-title">TASK</h2><p>Tutti i lavori creati, con stato, capacità usata e prove disponibili.</p></div><button onClick={() => openComposer("")}>＋ Nuovo task</button></div><div className="workspace-stats"><WorkspaceStat value={tasks.length} label="Totali" /><WorkspaceStat value={activeTasks.length} label="Attivi" tone="gold" /><WorkspaceStat value={tasks.filter((item) => item.status === "completed").length} label="Completati" tone="green" /></div>{taskRows(tasks, "I nuovi lavori compariranno qui.")}</section>;

    if (activeNav === "requests") return <section className="workspace-page" aria-labelledby="workspace-title"><div className="workspace-heading"><div><span>CODA DELLO STUDIO</span><h2 id="workspace-title">RICHIESTE</h2><p>Operazioni attive e conferme che richiedono una decisione umana.</p></div><button onClick={() => openComposer("")}>＋ Nuova richiesta</button></div>{pending.length ? <div className="workspace-approvals"><h3>Da approvare</h3>{pending.map((item) => { const observed = (item.preview.observed || {}) as Record<string, string>; return <article className="workspace-row approval-row" key={item.id}><span className="workspace-row-icon waiting_approval">◉</span><div className="workspace-row-copy"><strong>{item.task?.goal || `Approvare ${observed.client || "operazione"}`}</strong><span>{observed.total_label || "Controlla i dati prima di autorizzare"}</span></div><div className="workspace-approval-actions"><button className="approve" onClick={() => api.approve(item.id).then(refresh)}>Approva</button><button onClick={() => api.reject(item.id).then(refresh)}>Rifiuta</button></div></article>; })}</div> : null}{taskRows(activeTasks, "Non ci sono richieste in attesa o in lavorazione.")}</section>;

    if (activeNav === "errors") return <section className="workspace-page" aria-labelledby="workspace-title"><div className="workspace-heading"><div><span>DIAGNOSTICA</span><h2 id="workspace-title">ERRORI</h2><p>I problemi da risolvere sono separati dagli errori già chiusi.</p></div><button onClick={() => void refresh()}>↻ Ricontrolla</button></div><div className="workspace-error-group"><h3><i className="error-active" /> Attivi ({activeErrors.length})</h3>{taskRows(activeErrors, "Nessun errore attivo: tutti i sistemi sono operativi.")}</div><div className="workspace-error-group historical"><h3><i /> Storico ({historicalErrors.length})</h3>{taskRows(historicalErrors, "Non ci sono errori storici.")}</div></section>;

    if (activeNav === "contracts") return <section className="workspace-page" aria-labelledby="workspace-title"><div className="workspace-heading"><div><span>AREA DOCUMENTALE</span><h2 id="workspace-title">CONTRATTI</h2><p>Prepara bozze e raccogli dati. Nessun contratto viene inviato o firmato automaticamente.</p></div><button onClick={() => openComposer("Prepara una bozza di contratto per il cliente ")}>＋ Prepara contratto</button></div><div className="workspace-safety">✓ Bozze soltanto · invio e firma restano sempre alla persona</div>{taskRows(contractTasks, "Non hai ancora preparato contratti con Kreluna.")}</section>;

    if (activeNav === "visure") return <section className="workspace-page" aria-labelledby="workspace-title"><div className="workspace-heading"><div><span>AREA CAMERALI</span><h2 id="workspace-title">VISURE</h2><p>Prepara richieste di visura e consulta le prove prodotte dall’Agent.</p></div><button onClick={() => openComposer("Prepara una visura per il cliente ")}>＋ Nuova visura</button></div><div className="workspace-safety">✓ Accesso umano per SPID, CNS, CIE e OTP · nessun invio automatico</div>{taskRows(visureTasks, "Non ci sono ancora richieste di visura.")}</section>;

    if (activeNav === "documents") return <section className="workspace-page" aria-labelledby="workspace-title"><div className="workspace-heading"><div><span>ARCHIVIO OPERATIVO</span><h2 id="workspace-title">DOCUMENTI</h2><p>Controlli documentali e prove raccolte dai lavori, senza mostrare credenziali.</p></div><button onClick={() => openComposer("Controlla i documenti mancanti per il cliente ")}>＋ Controlla documenti</button></div>{taskRows(documentTasks, "I controlli e le prove dei task compariranno qui.")}</section>;

    return <section className="workspace-page settings-workspace" aria-labelledby="workspace-title"><div className="workspace-heading"><div><span>CONTROLLO DEL PROGRAMMA</span><h2 id="workspace-title">IMPOSTAZIONI</h2><p>Connessione IA, aggiornamenti, sessione e protezioni operative.</p></div><button onClick={() => void refresh()}>↻ Aggiorna</button></div><div className="settings-grid">
      <article><span>INTELLIGENZA ARTIFICIALE</span><h3>{providerLabel}</h3><p>{overview?.ai_detail || (aiConnected ? "Collegata e pronta." : "Servizio non disponibile.")}</p><div className={`settings-state ${aiConnected ? "connected" : "warning"}`}>● {aiConnected ? "IA attiva" : "Da controllare"}</div><button onClick={() => openAISettings()}>Configura e verifica</button></article>
      <article><span>AGGIORNAMENTI</span><h3>Kreluna Director v{version}</h3><p>{updateAvailable ? `È disponibile la versione ${updateStatus?.latest_version}.` : "Il programma è aggiornato."}</p><div className={`settings-state ${updateAvailable ? "warning" : "connected"}`}>● {updateAvailable ? "Aggiornamento disponibile" : "Versione corrente"}</div><button disabled={!updateAvailable} onClick={() => setUpdateOpen(true)}>{updateAvailable ? "Installa aggiornamento" : "Nessun aggiornamento"}</button></article>
      <article><span>SESSIONE</span><h3>{name}</h3><p>Accesso protetto su questo Mac. La password non viene conservata nell’app.</p><div className="settings-state connected">● Sessione attiva</div><button onClick={() => { setToken(null); setReady(false); }}>Esci dallo studio</button></article>
      <article><span>BARRIERE DI SICUREZZA</span><h3>Sempre attive</h3><p>Niente shell remota, eval, pagamenti, invii fiscali o login automatici SPID/CNS. Le schermate non vanno all’IA.</p><div className="settings-state connected">● Protezioni operative</div><button onClick={() => void openVault()}>Apri Fort Knox</button></article>
    </div></section>;
  }

  return <div className="director-cockpit" id="dashboard">
    <header className="cockpit-header">
      <div className="identity-card">
        <div className="orb brand-orb listen" aria-hidden="true"><span className="orb-core" /><span className="orb-ring" /></div>
        <div className="identity-copy"><h1>KRELUNA DIRECTOR</h1><p>{name} <span>•</span> active <span>•</span> v{version || "0.5.18"}</p>
          <button className={`identity-ai ${aiConnected ? "connected" : "warning"}`} onClick={() => openAISettings()}>{identityAILabel}</button>
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
      <div className="header-tools"><button className="approval-shortcut" onClick={() => goTo("requests")}>Da approvare ({pending.length})</button><button className="notification" aria-label="Notifiche" onClick={() => updateStatus?.available ? setUpdateOpen(true) : goTo("errors")}>♧{activeErrors.length || updateStatus?.available ? <i /> : null}</button><button className="avatar" aria-label="Profilo e impostazioni" onClick={() => goTo("settings")}>AR</button></div>
    </header>

    <div className="cockpit-body">
      <aside className="cockpit-sidebar">
        <nav aria-label="Navigazione principale">
          <NavButton active={activeNav === "dashboard"} icon="⌂" label="Dashboard" onClick={() => goTo("dashboard")} />
          <NavButton active={activeNav === "agents"} icon="▱" label="PC & Feature" onClick={() => goTo("agents")} />
          <NavButton active={activeNav === "tasks"} icon="⌘" label="Task" count={overview?.tasks_today} onClick={() => goTo("tasks")} />
          <NavButton active={activeNav === "requests"} icon="▱" label="Richieste" count={requestCount} onClick={() => goTo("requests")} />
          <NavButton active={activeNav === "errors"} icon="△" label="Errori" count={overview?.active_errors} onClick={() => goTo("errors")} />
          <NavButton active={activeNav === "contracts"} icon="▤" label="Contratti" onClick={() => goTo("contracts")} />
          <NavButton active={activeNav === "visure"} icon="▧" label="Visure" onClick={() => goTo("visure")} />
          <NavButton active={activeNav === "vault"} icon="▦" label="Fort Knox" count={vaultCredentials.length || undefined} onClick={() => void openVault()} />
          <NavButton active={activeNav === "documents"} icon="▤" label="Documenti" onClick={() => goTo("documents")} />
          <NavButton active={activeNav === "settings"} icon="⚙" label="Impostazioni" onClick={() => goTo("settings")} />
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
          <button className="new-request" onClick={newRequest}>Nuova richiesta <b>＋</b></button>
          <button className="side-logout" onClick={() => { setToken(null); setReady(false); }}>↪ <span>Chiudi sessione</span></button>
        </div>
      </aside>

      <main className={`dashboard-stage ${activeNav !== "dashboard" ? "workspace-mode" : ""}`}>
        {activeNav === "dashboard" ? <>
        <section className="feature-panel" id="agents"><div className="panel-heading"><h2>PC &amp; FEATURE</h2><button className="manage-feature" onClick={() => setActiveNav("agents")}>⌘&nbsp;&nbsp; Gestisci feature</button></div>
          <div className="feature-grid" aria-label="PC dello studio">{agents.map((agent) => {
            const work = currentWork(agent, tasks);
            const waiting = agent.presence === "waiting_install";
            const online = agentOnline(agent);
            const enabled = !(agent.killed || agent.paused);
            const active = online && enabled;
            const offlineEnabled = !waiting && !online && enabled;
            const controlTitle = waiting
              ? "Genera il codice per installare l’Agent"
              : offlineEnabled
                ? "Agent spento: apri Kreluna Agent su questo computer"
                : enabled ? "Disattiva Agent" : "Attiva Agent";
            const controlAction = waiting ? "Installa" : enabled ? "Disattiva" : "Attiva";
            return <article className={`feature-card ${work && online ? "working" : ""} ${active ? "enabled" : "disabled"}`} key={agent.device_id}>
              <div className="feature-name"><span className={`status-dot ${waiting ? "waiting" : active ? "online" : "off"}`} /><strong>{agent.display_name || agent.agent_id}</strong>
                <button className={`mini-switch ${active ? "on" : "off"}`} disabled={deviceAction === agent.device_id || offlineEnabled} onClick={() => void toggleAgent(agent)} title={controlTitle} aria-label={`${controlAction} ${agent.display_name || agent.agent_id}`} aria-pressed={active}><i /></button>
              </div><p>{agent.job}</p><span title="Disponibile per Mac e Windows">{agentState(agent, work)} · Mac/PC</span>
            </article>;
          })}</div>
        </section>

        <div className="work-grid">
          <section className="kreluna-panel" id="chat">
            <div className="kreluna-heading"><div className={`orb chat-orb ${busy ? "think" : orb}`} aria-hidden="true"><span className="orb-core" /><span className="orb-ring" /></div><h2>Kreluna</h2><span className={`ai-active ${aiConnected ? "connected" : "warning"}`}>{aiConnected ? "IA attiva" : "IA non disponibile"}</span>
              <label className="provider-compact" id="ai-settings"><select value={overview?.ai_provider || "grok"} onChange={async (event) => { await api.chooseAIProvider(event.target.value); await refresh(); }} aria-label="Provider IA">{aiProviders.map((item) => <option key={item.provider} value={item.provider}>{item.label}{item.configured ? "" : item.managed ? " · licenza non attiva" : " · da configurare"}</option>)}</select></label>
            </div>
            {!aiConnected ? <button className="ai-diagnostic" title={overview?.ai_detail || "Configurazione incompleta"} onClick={() => openAISettings()}><strong>{providerLabel}</strong>: {overview?.ai_detail || "servizio non disponibile"}. {aiManaged ? "Controlla la licenza." : "Configura ora."}</button> : null}
            <div className="chat-log" ref={logRef}>{chat.map((item, index) => <div key={index} className={`msg ${item.role} ${item.deny ? "deny" : ""}`}><strong>{item.role === "user" ? "Tu" : `Kreluna${chatSource(item)}`}</strong><div>{item.text}</div></div>)}{busy ? <div className="typing"><i /><i /><i /></div> : null}</div>
            <div className="chips">{SUGGESTIONS.map((item) => <button key={item.full} className="chip" onClick={() => void send(item.full)} disabled={busy}>{item.short}</button>)}</div>
            <form className="composer" onSubmit={(event) => { event.preventDefault(); void send(draft); }}><span className="mic">♩</span><textarea value={draft} aria-label="Scrivi una richiesta a Kreluna" placeholder="Scrivi qui la tua richiesta…" onChange={(event) => setDraft(event.target.value)} /><button className="send-button" disabled={busy} aria-label="Invia">➤</button></form>
          </section>

          <aside className="requests-panel" id="requests"><div className="requests-heading"><h2>RICHIESTE</h2><select aria-label="Filtra richieste" value={requestFilter} onChange={(event) => setRequestFilter(event.target.value as RequestFilter)}><option value="all">Tutte</option><option value="active">In corso</option><option value="errors">Errori</option><option value="approvals">Da approvare</option></select></div>
            <div className="request-list">
              {requestFilter !== "active" && requestFilter !== "errors" ? pending.map((item) => { const observed = ((item.preview.observed as Record<string, string>) || {}) as Record<string, string>; return <article className="request-row approval-row" id="approvals" key={item.id}><span className="request-icon">◉</span><div className="request-copy"><strong>Approvare {observed.client || "fattura"}</strong><span>{observed.total_label || "Operazione in attesa"}</span></div><div className="request-actions"><button onClick={() => api.approve(item.id).then(refresh)}>Approva</button><button onClick={() => api.reject(item.id).then(refresh)}>No</button></div></article>; }) : null}
              {dashboardTasks.map((task) => <article className={`request-row ${task.status}`} id={task.error_state === "active" ? "errors" : undefined} key={task.id}><span className={`request-icon ${task.status}`}>{task.status === "failed" ? "△" : "▣"}</span><div className="request-copy"><strong title={task.goal}>{task.goal}</strong><EvidenceStrip ids={task.evidence.map((shot) => shot.id)} onOpen={setLightbox} />{task.error ? <span className="request-error">{task.error}</span> : null}</div><div className="request-meta"><span className={`request-status ${task.status}`}>{label(TASK_LABEL, task.status)}</span>{task.created_at ? <time>{new Date(task.created_at).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" })}</time> : null}{task.status === "queued" || task.status === "assigned" ? <button onClick={() => api.cancelTask(task.id).then(refresh)}>Annulla</button> : null}</div></article>)}
              {!dashboardTasks.length && !pending.length && requestFilter === "all" ? STARTER_REQUESTS.map((item, index) => <button className="request-row starter-row" key={item.title} onClick={() => openComposer(item.prompt)}><span className={`request-icon starter-${index}`}>{item.icon}</span><span className="request-copy"><strong>{item.title}</strong><span className="preview-strip"><i /><i /><i /><i /></span></span><span className="request-meta"><span className="request-status starter">Avvia</span><time>pronto</time></span></button>) : null}
              {!dashboardTasks.length && requestFilter !== "all" && (requestFilter !== "approvals" || !pending.length) ? <div className="request-filter-empty">Nessuna richiesta per questo filtro.</div> : null}
            </div><button className="show-all" onClick={() => setActiveNav("requests")}>Mostra tutte le richieste <span>→</span></button>
          </aside>
        </div>
        </> : workspacePage()}
      </main>
    </div>

    <footer className="cockpit-footer"><span>◉&nbsp; Sistema: macOS</span><span>▣&nbsp; Host: questo Mac</span><span>♙&nbsp; Utente: {name}</span><span>◷&nbsp; Sessione attiva</span><span className={aiConnected ? "healthy" : "warning"}>●&nbsp; {aiConnected ? "Tutti i sistemi operativi" : `${providerLabel}: ${aiUnavailable}`}</span></footer>
    {confirmKill ? <div className="kill-confirm" role="dialog" aria-modal="true" aria-label="Conferma stop"><div><h2>Fermare tutti gli Agent?</h2><p>I lavori in corso torneranno in attesa.</p><button onClick={() => setConfirmKill(false)}>Annulla</button><button className="danger" onClick={async () => { await api.kill(); setConfirmKill(false); await refresh(); }}>Conferma stop</button></div></div> : null}
    {enrollment || enrollmentError ? <div className="enrollment-dialog" role="dialog" aria-modal="true" aria-labelledby="enrollment-title"><div className="enrollment-card">
      <span>INSTALLAZIONE AGENT</span><h2 id="enrollment-title">{enrollment?.displayName || "Codice non disponibile"}</h2>
      {enrollment ? <><p>Inserisci questo codice nell’installer Mac o Windows. Vale una sola volta e scade alle {new Date(enrollment.expiresAt).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" })}.</p><code>{enrollment.code}</code><button className="primary" onClick={() => void navigator.clipboard.writeText(enrollment.code)}>Copia codice</button></> : null}
      {enrollmentError ? <div className="enrollment-error" role="alert">{enrollmentError}</div> : null}
      <button onClick={() => { setEnrollment(null); setEnrollmentError(""); }}>Chiudi</button>
      <small>Il Director conserva soltanto l’impronta del codice. Per reinstallare un PC già collegato occorre prima revocarlo.</small>
    </div></div> : null}
    {aiSettingsOpen ? <div className="ai-settings-dialog" role="dialog" aria-modal="true" aria-labelledby="ai-settings-title"><form className="ai-settings-card" onSubmit={saveAISettings}>
      <div className="ai-settings-heading"><div><span>CONFIGURAZIONE IA</span><h2 id="ai-settings-title">{settingsManaged ? "IA Kreluna" : "Collega il provider al Director"}</h2><p>{settingsManaged ? "Il servizio IA è gestito e protetto da Kreluna. Questa app usa soltanto la sua licenza revocabile." : "La chiave viene cifrata sul computer e non viene mai mostrata nuovamente."}</p></div><button type="button" aria-label="Chiudi configurazione IA" onClick={closeAISettings}>×</button></div>
      <label>Provider<select value={aiSettingsProvider} onChange={(event) => changeAISettingsProvider(event.target.value as AIProviderOption["provider"])}>{aiProviders.map((item) => <option key={item.provider} value={item.provider}>{item.label}</option>)}</select></label>
      {settingsManaged ? <div className="ai-settings-note">Nessuna chiave API o configurazione tecnica da inserire. Il motore IA è controllato dalla licenza Kreluna.</div> : <label>Modello<input value={aiSettingsModel} onChange={(event) => setAISettingsModel(event.target.value)} placeholder="Nome del modello" autoComplete="off" /></label>}
      {!settingsManaged && aiSettingsProvider !== "ollama" ? <label>Chiave API<input type="password" value={aiSettingsKey} onChange={(event) => setAISettingsKey(event.target.value)} placeholder={settingsProvider?.key_saved ? "Chiave già salvata · lascia vuoto per conservarla" : "Incolla la chiave API"} autoComplete="new-password" /></label> : !settingsManaged ? <div className="ai-settings-note">Ollama non usa una chiave API; deve essere attivo su questo computer.</div> : null}
      {aiSettingsError ? <div className="ai-settings-alert error" role="alert">{aiSettingsError}</div> : null}
      {aiSettingsMessage ? <div className="ai-settings-alert success">{aiSettingsMessage}</div> : null}
      <div className="ai-settings-actions"><button type="button" onClick={closeAISettings}>Annulla</button><button className="primary" disabled={aiSettingsBusy || !aiSettingsModel.trim()}>{aiSettingsBusy ? "Controllo…" : settingsManaged ? "Controlla connessione" : "Salva e controlla"}</button></div>
      <small>La verifica usa il provider selezionato. Nessun fallback automatico verso OpenAI.</small>
    </form></div> : null}
    {vaultOpen ? <div className="vault-dialog" role="dialog" aria-modal="true" aria-labelledby="vault-title"><div className={`vault-card ${vaultUnlocked ? "open" : "sealed"}`}>
      <div className="vault-heading"><div><span className="vault-eyebrow">KRELUNA FORT KNOX</span><h2 id="vault-title">{vaultUnlocked ? "Cassaforte digitale clienti" : "Fort Knox è chiuso"}</h2><p>{vaultUnlocked ? "Inserisci un cliente oppure importa un CSV. Ogni accesso è cifrato separatamente per lo studio e non viene inviato all’IA." : "Solo il titolare può aprire lo sportello. Il PIN viene verificato nel Director e non viene mai conservato in chiaro."}</p></div><button className="vault-close" aria-label="Chiudi Fort Knox" onClick={closeVault}>×</button></div>
      {!vaultUnlocked ? <form className="vault-gate" onSubmit={unlockVault} autoComplete="off">
        <div className="vault-door" aria-hidden="true"><div className="vault-door-rim"><i className="vault-bolt b1" /><i className="vault-bolt b2" /><i className="vault-bolt b3" /><i className="vault-bolt b4" /><i className="vault-bolt b5" /><i className="vault-bolt b6" /><div className="vault-wheel"><span /><span /><span /><b>K</b></div></div></div>
        <div className="vault-keypad-panel"><span className="vault-gate-state">{vaultPinConfigured === null ? "CONTROLLO SERRATURA" : vaultPinConfigured ? "ACCESSO PROTETTO" : "PRIMA CONFIGURAZIONE"}</span><h3>{vaultPinConfigured === false ? "Crea il PIN della cassaforte" : "Inserisci il PIN a 6 cifre"}</h3>
          <input className="vault-pin-input" type="password" inputMode="numeric" pattern="[0-9]*" maxLength={6} autoComplete="off" autoFocus aria-label={vaultPinConfigured === false && vaultPin.length === 6 ? "Conferma PIN Fort Knox" : "PIN Fort Knox"} value={vaultPinConfigured === false && vaultPin.length === 6 ? vaultPinConfirm : vaultPin} onChange={(event) => { const value = event.target.value.replace(/\D/g, "").slice(0, 6); if (vaultPinConfigured === false && vaultPin.length === 6) setVaultPinConfirm(value); else setVaultPin(value); setVaultError(""); }} onKeyDown={(event) => { if (event.key === "Backspace" && vaultPinConfigured === false && vaultPin.length === 6 && !vaultPinConfirm) setVaultPin((value) => value.slice(0, -1)); }} />
          <div className="vault-pin-display" aria-label="PIN inserito">{Array.from({ length: 6 }, (_, index) => <i className={index < vaultPin.length ? "filled" : ""} key={index} />)}</div>
          {vaultPinConfigured === false ? <><small>Conferma lo stesso PIN</small><div className="vault-pin-display confirm" aria-label="Conferma PIN">{Array.from({ length: 6 }, (_, index) => <i className={index < vaultPinConfirm.length ? "filled" : ""} key={index} />)}</div></> : null}
          <div className="vault-keypad">{[1, 2, 3, 4, 5, 6, 7, 8, 9].map((digit) => <button type="button" disabled={vaultUnlockBusy || vaultPinConfigured === null} onClick={() => addVaultPinDigit(String(digit))} key={digit}>{digit}</button>)}<button type="button" className="clear" disabled={vaultUnlockBusy} onClick={() => { setVaultPin(""); setVaultPinConfirm(""); setVaultError(""); }}>C</button><button type="button" disabled={vaultUnlockBusy || vaultPinConfigured === null} onClick={() => addVaultPinDigit("0")}>0</button><button type="button" className="backspace" disabled={vaultUnlockBusy} onClick={removeVaultPinDigit} aria-label="Cancella ultima cifra">⌫</button></div>
          {vaultRetryAfter > 0 ? <div className="vault-lockout">Serratura temporaneamente bloccata. Riprova tra circa {vaultRetryAfter} secondi.</div> : null}
          {vaultError ? <div className="vault-alert error" role="alert">{vaultError}</div> : null}
          <button className="vault-unlock" disabled={vaultUnlockBusy || vaultPinConfigured === null || vaultRetryAfter > 0}>{vaultUnlockBusy ? "Verifica…" : vaultPinConfigured === false ? "Configura e apri" : "Apri Fort Knox"}</button><small className="vault-gate-note">5 tentativi massimi · blocco automatico · chiusura dopo 10 minuti</small>
        </div>
      </form> : <>
      <div className="vault-toolbar"><input ref={vaultInput} type="file" accept=".csv,text/csv" hidden onChange={(event) => void previewVaultFile(event.target.files?.[0] || null)} /><button className="primary" disabled={vaultBusy} onClick={newVaultCredential}>＋ Nuovo cliente</button><button disabled={vaultBusy} onClick={() => vaultInput.current?.click()}>{vaultBusy ? "Elaborazione…" : "Importa CSV"}</button><button disabled={vaultBusy} onClick={() => void downloadVaultTemplate()}>Scarica modello</button><span>🔒 Nessun segreto mostrato</span></div>
      {vaultError ? <div className="vault-alert error" role="alert">{vaultError}</div> : null}{vaultMessage ? <div className="vault-alert success">{vaultMessage}</div> : null}
      {vaultFormOpen ? <form className="vault-form" onSubmit={saveVaultCredential} autoComplete="off">
        <div className="vault-form-heading"><div><strong>{vaultEditingId ? "Aggiorna accesso" : "Nuovo cliente"}</strong><span>{vaultEditingId ? "Reinserisci username e password: Fort Knox non può mostrarli." : "I dati vengono cifrati appena premi Salva."}</span></div><button type="button" onClick={closeVaultForm}>×</button></div>
        <div className="vault-form-grid">
          <label>Cliente<input required maxLength={200} value={vaultForm.client_name} onChange={(event) => setVaultForm({ ...vaultForm, client_name: event.target.value })} placeholder="Ragione sociale o nome" /></label>
          <label>Portale<input required maxLength={80} list="fort-knox-portals" value={vaultForm.portal} onChange={(event) => setVaultForm({ ...vaultForm, portal: event.target.value })} placeholder="es. Webdesk, CGN, AdE" /><datalist id="fort-knox-portals"><option value="webdesk" /><option value="ade" /><option value="cgn" /><option value="comunica" /><option value="ipsoa" /><option value="inps" /></datalist></label>
          <label>Username<input required maxLength={320} value={vaultForm.username} onChange={(event) => setVaultForm({ ...vaultForm, username: event.target.value })} placeholder="Username o email" autoComplete="off" /></label>
          <label className="vault-url-field">Link del portale<input required type="url" maxLength={1000} value={vaultForm.portal_url} onChange={(event) => setVaultForm({ ...vaultForm, portal_url: event.target.value })} placeholder="https://indirizzo-del-portale.it/login" autoComplete="url" /></label>
          <label>Password o token<input required type="password" maxLength={2048} value={vaultForm.secret} onChange={(event) => setVaultForm({ ...vaultForm, secret: event.target.value })} placeholder="Non verrà più mostrato" autoComplete="new-password" /></label>
          <label>Tipo<select value={vaultForm.secret_kind} onChange={(event) => setVaultForm({ ...vaultForm, secret_kind: event.target.value as VaultCredentialInput["secret_kind"] })}><option value="password">Password</option><option value="api_token">Token API</option><option value="client_secret">Client secret</option></select></label>
          <label>Profilo<input required maxLength={120} value={vaultForm.credential_label} onChange={(event) => setVaultForm({ ...vaultForm, credential_label: event.target.value })} placeholder="principale" /></label>
        </div>
        <div className="vault-form-note">SPID, CNS, CIE, smart card e OTP non possono essere salvati: l’Agent si fermerà e chiederà l’intervento umano.</div>
        <div className="vault-form-actions"><button type="button" onClick={closeVaultForm}>Annulla</button><button className="primary" disabled={vaultBusy}>{vaultBusy ? "Cifro…" : "Cifra e salva"}</button></div>
      </form> : null}
      {vaultPreview ? <section className="vault-preview"><div><strong>{vaultPreview.recognized} accessi riconosciuti</strong><span>{vaultPreview.warnings.length ? ` · ${vaultPreview.warnings.length} righe da correggere` : " · CSV pronto"}</span></div><div className="vault-preview-list">{vaultPreview.rows.slice(0, 8).map((row) => <span key={`${row.row_number}-${row.client_name}-${row.portal}`} title={row.portal_url || "Link non indicato"}><b>{row.client_name}</b><i>{row.portal}</i><em>{row.username_masked}</em></span>)}</div><div className="vault-preview-actions"><button onClick={() => { setVaultFile(null); setVaultPreview(null); }}>Annulla</button><button className="primary" disabled={vaultBusy} onClick={() => void importVaultFile()}>Cifra e importa</button></div></section> : null}
      <div className="vault-list">{vaultCredentials.map((item) => <article className="vault-row" key={item.id}><div className={`vault-lock ${item.status}`}>◆</div><div><strong>{item.client_name}</strong><span>{item.portal} · {item.credential_label}</span><small className="vault-saved-link" title={item.portal_url}>{item.portal_url || "Link da aggiungere"}</small></div><div className="vault-user"><span>{item.username_masked}</span><small>{item.secret_kind.replace(/_/g, " ")}</small></div><div className="vault-actions"><button onClick={() => editVaultCredential(item)}>Aggiorna</button><button onClick={() => void checkVaultCredential(item.id)}>Controlla</button><button className="danger-text" onClick={() => void revokeVaultCredential(item.id)}>Rimuovi</button></div></article>)}{!vaultCredentials.length && !vaultPreview ? <div className="vault-empty"><strong>Nessun accesso ancora caricato</strong><span>Premi Nuovo cliente oppure importa il modello CSV.</span></div> : null}</div>
      <div className="vault-safety"><strong>Barriere sempre attive</strong><span>Niente SPID/CNS automatico · niente invio fatture, F24, PEC o pagamenti · OTP inserito dalla persona.</span></div>
      </>}
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

function WorkspaceStat({ value, label: statLabel, tone = "blue" }: { value: number; label: string; tone?: string }) {
  return <div className={`workspace-stat ${tone}`}><strong>{value}</strong><span>{statLabel}</span></div>;
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
