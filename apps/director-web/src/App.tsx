import { FormEvent, useEffect, useMemo, useState } from "react";
import { Agent, api, Approval, Overview, setToken, Task, token } from "./lib/api";

type ChatItem = { role: "user" | "director"; text: string; deny?: boolean };

const SUGGESTIONS = [
  { short: "Fattura Gadducci", full: "Fai la fattura ad Andrea Gadducci per 35-40 mila euro di manodopera" },
  { short: "Blocco note", full: "Apri Blocco Note e scrivi: Kreluna Agent operativo" },
  { short: "Controlla fatture", full: "Controlla le fatture" },
  { short: "Pagamento", full: "Prepara un pagamento di 500 euro, non eseguirlo" },
  { short: "F24", full: "Prepara gli F24 in scadenza, ma non inviarli" },
  { short: "Ferma", full: "Ferma tutto" },
];

export default function App() {
  const [ready, setReady] = useState(Boolean(token()));
  const [email, setEmail] = useState("andrea@studio.demo");
  const [password, setPassword] = useState("demo");
  const [name, setName] = useState("Studio");
  const [error, setError] = useState("");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [chat, setChat] = useState<ChatItem[]>([
    {
      role: "director",
      text: "Sono Kreluna Director. Parla solo con me: scelgo io il PC e ti chiedo conferma prima delle azioni irreversibili.",
    },
  ]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmKill, setConfirmKill] = useState(false);
  const [version, setVersion] = useState("");
  const [updateNote, setUpdateNote] = useState("");
  const [lightbox, setLightbox] = useState<string | null>(null);

  async function refresh() {
    const [over, ag, ts, ap] = await Promise.all([api.overview(), api.agents(), api.tasks(), api.approvals()]);
    setOverview(over);
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
    setChat((items) => [...items, { role: "user", text: message }]);
    try {
      const result = await api.chat(message);
      setChat((items) => [
        ...items,
        { role: "director", text: result.summary + (result.deny_reason ? `\n${result.deny_reason}` : ""), deny: result.denied },
      ]);
      await refresh();
    } catch (err) {
      setChat((items) => [
        ...items,
        { role: "director", text: err instanceof Error ? err.message : "Errore Director", deny: true },
      ]);
    } finally {
      setBusy(false);
    }
  }

  const pending = useMemo(() => approvals.filter((item) => item.status === "pending"), [approvals]);
  const recentTasks = tasks.slice(0, 6);

  if (!ready) {
    return (
      <div className="login">
        <div className="login-card">
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
          <div className="eyebrow">Kreluna Director</div>
          <div className="small">
            {name} · {overview?.license_state ?? "…"}
            {version ? ` · v${version}` : ""}
            {updateNote ? ` · ${updateNote}` : ""}
          </div>
        </div>
        <div className="stats">
          <Stat label="PC" value={`${overview?.agents_online ?? 0}/${overview?.agents_total ?? 0}`} />
          <Stat label="Task" value={overview?.tasks_today ?? 0} />
          <Stat label="Corso" value={overview?.running ?? 0} />
          <Stat label="Approva" value={overview?.pending_approvals ?? 0} />
          <Stat label="Errori" value={overview?.errors ?? 0} />
        </div>
        <div className="actions">
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

      <main className="layout">
        <section className="chat">
          <div className="chat-log">
            {chat.map((item, index) => (
              <div key={index} className={`msg ${item.role} ${item.deny ? "deny" : ""}`}>
                <strong>{item.role === "user" ? "Tu" : "Director"}</strong>
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
              placeholder="Scrivi a Kreluna…"
              onChange={(event) => setDraft(event.target.value)}
            />
            <button className="btn" disabled={busy}>
              Invia
            </button>
          </form>
        </section>

        <aside className="stack">
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
                    <div className="task-goal">{task.goal}</div>
                    <EvidenceStrip ids={task.evidence.map((shot) => shot.id)} onOpen={setLightbox} />
                  </div>
                  <span className={`pill ${task.status} ${task.risk}`}>{task.status}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="panel slim">
            <h2>PC</h2>
            <div className="panel-body">
              {agents.map((agent) => (
                <div className="row compact" key={agent.device_id}>
                  <div>
                    <span className={`dot ${agent.presence}`} />
                    <strong>{agent.display_name || agent.agent_id}</strong>
                    <span className="small"> · {agent.job}</span>
                  </div>
                  <span className="pill">{agent.killed ? "fermo" : agent.presence}</span>
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
