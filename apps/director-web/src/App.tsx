import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { Agent, AIProviderOption, api, Approval, Overview, setToken, Task, token } from "./lib/api";

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
  { short: "Ferma", full: "Ferma tutto" },
];

const TASK_LABEL: Record<string, string> = {
  queued: "in attesa",
  assigned: "sul PC",
  running: "in corso",
  waiting_approval: "da approvare",
  completed: "fatto",
  failed: "errore",
  cancelled: "annullato",
  blocked: "bloccato",
};

function label(map: Record<string, string>, value: string): string {
  return map[value] || value.replace(/_/g, " ");
}

function currentWork(agent: Agent, tasks: Task[]): Task | undefined {
  if (agent.active_task_id) {
    const hit = tasks.find((item) => item.id === agent.active_task_id);
    if (hit) return hit;
  }
  return tasks.find(
    (item) =>
      item.assigned_device_id === agent.device_id &&
      ["queued", "assigned", "running", "waiting_approval"].includes(item.status),
  );
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
  const [chat, setChat] = useState<ChatItem[]>([
    {
      role: "director",
      text: "Sono Kreluna Director. Ogni PC ha un lavoro e un programma (Webdesk, IPSOA, CGN, INPS…). Clicca un bottone, poi Approva se serve. Nessun invio reale.",
    },
  ]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmKill, setConfirmKill] = useState(false);
  const [version, setVersion] = useState("");
  const [updateNote, setUpdateNote] = useState("");
  const [lightbox, setLightbox] = useState<string | null>(null);
  const [orb, setOrb] = useState<"listen" | "think" | "talk">("listen");
  const logRef = useRef<HTMLDivElement | null>(null);
  const talkTimer = useRef<number>(0);

  async function refresh() {
    const [over, ag, ts, ap, ai] = await Promise.all([
      api.overview(),
      api.agents(),
      api.tasks(),
      api.approvals(),
      api.aiProviders(),
    ]);
    setOverview(over);
    setAIProviders(ai.providers);
    setAgents(ag.agents);
    setTasks(ts.tasks);
    setApprovals(ap.approvals);
  }

  useEffect(() => {
    api
      .health()
      .then((health) => {
        setVersion(health.version);
        return api.updateManifest().then((data) => ({ health, data }));
      })
      .then((result) => {
        if (!result) return;
        const remote = result.data.manifest?.version;
        if (remote && remote !== result.health.version) {
          setUpdateNote(`Aggiornamento ${remote} disponibile.`);
        }
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!ready) return;
    api
      .me()
      .then((me) => {
        setName(me.name);
        return refresh().catch(() => undefined);
      })
      .catch(() => {
        setToken(null);
        setReady(false);
      });
    const timer = window.setInterval(() => {
      refresh().catch(() => undefined);
    }, 2500);
    return () => window.clearInterval(timer);
  }, [ready]);

  useEffect(() => {
    const node = logRef.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
  }, [chat, busy]);

  async function onLogin(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      const result = await api.login(email, password);
      setToken(result.token);
      setName(result.user.name);
      setReady(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login fallito");
    }
  }

  async function send(text: string) {
    const message = text.trim();
    if (!message) return;
    setDraft("");
    setBusy(true);
    setOrb("think");
    setChat((items) => [...items, { role: "user", text: message }]);
    try {
      const result = await api.chat(message);
      setChat((items) => [
        ...items,
        {
          role: "director",
          text: result.summary + (result.deny_reason ? `\n${result.deny_reason}` : ""),
          deny: result.denied,
          source: result.source,
        },
      ]);
      setOrb("talk");
      window.clearTimeout(talkTimer.current);
      talkTimer.current = window.setTimeout(() => setOrb("listen"), 4200);
      await refresh();
    } catch (err) {
      setChat((items) => [
        ...items,
        { role: "director", text: err instanceof Error ? err.message : "Errore Director", deny: true },
      ]);
      setOrb("listen");
    } finally {
      setBusy(false);
    }
  }

  const pending = useMemo(() => approvals.filter((item) => item.status === "pending"), [approvals]);
  const blocked = useMemo(() => agents.filter((item) => item.killed || item.paused), [agents]);
  const wrongJob = useMemo(() => agents.filter((item) => item.retired && item.connected), [agents]);
  const oldAgent = useMemo(() => agents.filter((item) => item.needs_update && item.connected), [agents]);

  async function resumeAll() {
    await Promise.all(blocked.map((item) => api.resume(item.device_id).catch(() => undefined)));
    setChat((items) => [...items, { role: "director", text: "Ho ripreso i PC. Ora possono lavorare." }]);
    await refresh();
  }

  const recentTasks = tasks.slice(0, 12);
  const activeErrors = tasks.filter((task) => task.error_state === "active");
  const historicalErrors = tasks.filter((task) => task.error_state === "historical").slice(0, 5);

  if (!ready) {
    return (
      <div className="login">
        <div className="login-card">
          <div className="orb listen login-orb" aria-hidden="true">
            <span className="orb-core" />
            <span className="orb-ring" />
          </div>
          <div className="eyebrow">Studio · Cloud</div>
          <h1>Kreluna Director</h1>
          <p>Entra nello studio demo. L’intelligenza sta qui; i PC eseguono solo ciò che la policy permette.</p>
          <form onSubmit={onLogin}>
            <label>
              Email
              <input value={email} onChange={(event) => setEmail(event.target.value)} />
            </label>
            <label>
              Password
              <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
            </label>
            {error ? <div className="error">{error}</div> : null}
            <button className="btn" type="submit">
              Entra nello studio
            </button>
          </form>
          <p className="hint">Demo: andrea@studio.demo / demo{version ? ` · v${version}` : ""}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">Kreluna Director</div>
          <div className="small">
            {name} · {overview?.license_state ?? "…"}
            {version ? ` · v${version}` : ""}
            {overview
              ? ` · IA: ${overview.ai_provider_label || "non configurata"}${overview.ai_model ? ` / ${overview.ai_model}` : ""}`
              : ""}
            {updateNote ? ` · ${updateNote}` : ""}
          </div>
        </div>
        <div className="stats">
          <Stat label="PC" value={`${overview?.agents_online ?? 0}/${overview?.agents_total ?? 0}`} />
          <Stat label="Task" value={overview?.tasks_today ?? 0} />
          <Stat label="Corso" value={overview?.running ?? 0} />
          <Stat label="Approva" value={overview?.pending_approvals ?? 0} />
          <Stat label="Errori attivi" value={overview?.active_errors ?? 0} />
          <Stat label="Storico" value={overview?.historical_errors ?? 0} />
        </div>
        <div className="actions">
          {blocked.length && !confirmKill ? (
            <button className="btn ok" onClick={resumeAll}>
              Riprendi {blocked.length > 1 ? `(${blocked.length})` : ""}
            </button>
          ) : null}
          {confirmKill ? (
            <>
              <button className="btn ghost" onClick={() => setConfirmKill(false)}>
                Annulla
              </button>
              <button
                className="btn danger"
                onClick={async () => {
                  await api.kill();
                  setConfirmKill(false);
                  setChat((items) => [...items, { role: "director", text: "Kill switch attivato. Tutti i PC sono fermi." }]);
                  await refresh();
                }}
              >
                Conferma stop
              </button>
            </>
          ) : (
            <button className="btn danger" onClick={() => setConfirmKill(true)}>
              Ferma
            </button>
          )}
          <label className="provider-select">
            <span>IA</span>
            <select
              value={overview?.ai_provider || "openai"}
              onChange={async (event) => {
                await api.chooseAIProvider(event.target.value);
                await refresh();
              }}
              aria-label="Provider IA"
            >
              {aiProviders.map((item) => (
                <option key={item.provider} value={item.provider}>
                  {item.label}{item.configured ? "" : " · da configurare"}
                </option>
              ))}
            </select>
          </label>
          <button
            className="btn ghost"
            onClick={() => {
              setToken(null);
              setReady(false);
            }}
          >
            Esci
          </button>
        </div>
      </header>

      {overview && overview.ai_status !== "connected" ? (
        <div className="banner">
          <span>
            IA {overview.ai_provider_label || ""} non disponibile: {overview.ai_detail || "controlla la configurazione"}.
            Le richieste non comprese dalle regole vengono fermate e segnalate, senza fallback silenzioso.
          </span>
        </div>
      ) : null}

      {wrongJob.map((item) => (
        <div className="banner" key={item.device_id}>
          <span>
            {item.hostname} è acceso come {item.display_name || item.agent_id}, un ruolo vecchio: nessun lavoro dello
            studio gli arriva. Apri Kreluna Agent su quel computer, clicca Cambia lavoro e scegli il lavoro che deve
            fare.
          </span>
        </div>
      ))}

      {oldAgent.map((item) => (
        <div className="banner" key={`vecchio-${item.device_id}`}>
          <span>
            {item.display_name || item.agent_id} ({item.hostname}) ha un Kreluna Agent vecchio: sa fare i lavori di una
            versione precedente. Installa l'Agent nuovo su quel computer, altrimenti i lavori di{" "}
            {item.job || "questo ruolo"} arrivano ma vengono rifiutati.
          </span>
        </div>
      ))}

      {blocked.length ? (
        <div className="banner">
          <span>
            Hai premuto Ferma: {blocked.length === 1 ? "un PC è bloccato" : `${blocked.length} PC sono bloccati`} e le
            richieste restano in attesa.
          </span>
          <button className="btn ok" onClick={resumeAll}>
            Riprendi
          </button>
        </div>
      ) : null}

      <section className="agent-board" aria-label="PC dello studio">
        {agents.map((agent) => {
          const work = currentWork(agent, tasks);
          const working = Boolean(agent.busy || work);
          return (
            <article
              key={agent.device_id}
              className={`agent-card ${agent.presence} ${working ? "working" : ""} ${agent.killed ? "stopped" : ""}`}
            >
              <div className="agent-card-top">
                <span className={`dot ${agent.killed ? "killed" : working ? "busy" : agent.presence}`} />
                <strong>{agent.display_name || agent.agent_id}</strong>
              </div>
              <div className="small">{agent.job}</div>
              <div className={`agent-now ${working ? "live" : ""}`}>
                {agent.killed
                  ? "Fermo"
                  : working && work
                    ? work.goal
                    : agent.presence === "waiting_install"
                      ? "Da installare"
                      : agent.connected || agent.presence === "online"
                        ? "In ascolto"
                        : "Spento"}
              </div>
              {agent.killed || agent.paused ? (
                <button className="btn ok" onClick={() => api.resume(agent.device_id).then(refresh)}>
                  Riprendi
                </button>
              ) : null}
            </article>
          );
        })}
      </section>

      <main className="layout">
        <section className="chat">
          <div className="chat-head">
            <div className={`orb ${busy ? "think" : orb}`} aria-hidden="true">
              <span className="orb-core" />
              <span className="orb-ring" />
            </div>
            <div>
              <div className="orb-title">Kreluna</div>
              <div className="orb-caption">
                {busy || orb === "think"
                  ? "Sta pensando"
                  : orb === "talk"
                    ? "Ti parla"
                    : "Ti ascolta"}
              </div>
            </div>
          </div>
          <div className="chat-log" ref={logRef}>
            {chat.map((item, index) => (
              <div key={index} className={`msg ${item.role} ${item.deny ? "deny" : ""}`}>
                <strong>
                  {item.role === "user" ? "Tu" : "Kreluna"}
                  {item.role === "director" && item.source
                    ? item.source.startsWith("llm")
                      ? " · IA"
                      : " · regole"
                    : ""}
                </strong>
                <div>{item.text}</div>
              </div>
            ))}
          </div>
          <div className="chips">
            {SUGGESTIONS.map((item) => (
              <button key={item.full} className="chip" onClick={() => send(item.full)} disabled={busy} title={item.full}>
                {item.short}
              </button>
            ))}
          </div>
          <form
            className="composer"
            onSubmit={(event) => {
              event.preventDefault();
              void send(draft);
            }}
          >
            <textarea
              value={draft}
              placeholder="Clicca Fattura Gadducci, oppure scrivi qui…"
              onChange={(event) => setDraft(event.target.value)}
            />
            <button className="btn" disabled={busy}>
              Invia
            </button>
          </form>
        </section>

        <aside className="stack">
          {(activeErrors.length || historicalErrors.length) ? (
            <div className="panel">
              <h2>Errori</h2>
              <div className="panel-body">
                <div className="small">Attivi nelle ultime 24 ore ({activeErrors.length})</div>
                {activeErrors.map((task) => (
                  <div className="row compact" key={`errore-${task.id}`}>
                    <div className="row-main">
                      <strong>{task.goal}</strong>
                      <div className="small">{task.error}</div>
                    </div>
                  </div>
                ))}
                <div className="small">Storico ({overview?.historical_errors ?? historicalErrors.length})</div>
                {historicalErrors.map((task) => (
                  <div className="row compact" key={`storico-${task.id}`}>
                    <div className="row-main">
                      <strong>{task.goal}</strong>
                      <div className="small">{task.error}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          <div className="panel">
            <h2>Da approvare {pending.length ? `(${pending.length})` : ""}</h2>
            <div className="panel-body">
              {pending.length === 0 ? <div className="small">Niente in attesa.</div> : null}
              {pending.map((item) => {
                const observed = ((item.preview.observed as Record<string, string>) || {}) as Record<string, string>;
                return (
                  <div className="row compact" key={item.id}>
                    <div className="row-main">
                      <strong>{observed.client || "Fattura"}</strong>
                      <div className="small">
                        {observed.total_label} · {observed.status}
                      </div>
                      <EvidenceStrip ids={(item.task?.evidence || []).map((shot) => shot.id)} onOpen={setLightbox} />
                    </div>
                    <div className="actions">
                      <button className="btn ok" onClick={() => api.approve(item.id).then(refresh)}>
                        Approva
                      </button>
                      <button className="btn ghost" onClick={() => api.reject(item.id).then(refresh)}>
                        No
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="panel">
            <h2>Richieste</h2>
            <div className="panel-body">
              {recentTasks.map((task) => (
                <div className="row compact" key={task.id}>
                  <div className="row-main">
                    <div className="task-goal" title={task.goal}>
                      {task.goal}
                    </div>
                    <EvidenceStrip ids={task.evidence.map((shot) => shot.id)} onOpen={setLightbox} />
                  </div>
                  <div className="actions">
                    <span className={`pill ${task.status} ${task.risk}`}>{label(TASK_LABEL, task.status)}</span>
                    {task.status === "queued" || task.status === "assigned" ? (
                      <button className="btn ghost" onClick={() => api.cancelTask(task.id).then(refresh)}>
                        Annulla
                      </button>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </aside>
      </main>
      {lightbox ? (
        <button className="lightbox" onClick={() => setLightbox(null)}>
          <img src={lightbox} alt="Schermata del PC" />
        </button>
      ) : null}
    </div>
  );
}

function EvidenceStrip({ ids, onOpen }: { ids: string[]; onOpen: (src: string) => void }) {
  if (!ids.length) return null;
  const shown = ids.slice(-3).reverse();
  return (
    <div className="thumbs">
      {shown.map((id) => (
        <EvidenceThumb key={id} id={id} onOpen={onOpen} />
      ))}
      {ids.length > 3 ? <span className="small">+{ids.length - 3}</span> : null}
    </div>
  );
}

function EvidenceThumb({ id, onOpen }: { id: string; onOpen: (src: string) => void }) {
  const [src, setSrc] = useState<string>();
  useEffect(() => {
    let objectUrl = "";
    const current = token();
    if (!current) return;
    fetch(`/evidence/${id}/image`, { headers: { Authorization: `Bearer ${current}` } })
      .then((response) => (response.ok ? response.blob() : Promise.reject(new Error("no image"))))
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        setSrc(objectUrl);
      })
      .catch(() => undefined);
    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [id]);
  if (!src) return null;
  return (
    <button type="button" className="thumb" onClick={() => onOpen(src)}>
      <img src={src} alt="" />
    </button>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="stat">
      <span className="small">{label}</span>
      <b>{value}</b>
    </div>
  );
}
