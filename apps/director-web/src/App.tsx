import { FormEvent, useEffect, useMemo, useState } from "react";
import { Agent, api, Approval, Overview, setToken, Task, token } from "./lib/api";

type ChatItem = { role: "user" | "director"; text: string; deny?: boolean };

const SUGGESTIONS = [
  "Apri Blocco Note e scrivi: Kreluna Agent operativo",
  "Prepara una fattura demo a Rossi Mario per consulenza, EUR 1500 + IVA",
  "Controlla quali clienti hanno documenti mancanti",
  "Ferma tutto",
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
      text: "Sono Kreluna Director. Parla solo con me: scelgo io il PC, preparo il lavoro e ti chiedo conferma prima di qualsiasi cosa irreversibile.",
    },
  ]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmKill, setConfirmKill] = useState(false);

  async function refresh() {
    const [over, ag, ts, ap] = await Promise.all([api.overview(), api.agents(), api.tasks(), api.approvals()]);
    setOverview(over);
    setAgents(ag.agents);
    setTasks(ts.tasks);
    setApprovals(ap.approvals);
  }

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
          <p className="hint">Demo: andrea@studio.demo / demo</p>
        </div>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="eyebrow">Kreluna</div>
          <h1>Director</h1>
          <div className="small">
            {name} · licenza {overview?.license_state ?? "…"}
          </div>
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
                Conferma FERMA TUTTO
              </button>
            </>
          ) : (
            <button className="btn danger" onClick={() => setConfirmKill(true)}>
              Ferma tutto
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

      <section className="stats">
        <Stat label="PC online" value={`${overview?.agents_online ?? 0}/${overview?.agents_total ?? 0}`} />
        <Stat label="Task" value={overview?.tasks_today ?? 0} />
        <Stat label="In corso" value={overview?.running ?? 0} />
        <Stat label="Da approvare" value={overview?.pending_approvals ?? 0} />
        <Stat label="Errori" value={overview?.errors ?? 0} />
      </section>

      <main className="layout">
        <section className="chat">
          <div className="chat-log">
            {chat.map((item, index) => (
              <div key={index} className={`msg ${item.role} ${item.deny ? "deny" : ""}`}>
                <strong>{item.role === "user" ? "Tu" : "Director"}</strong>
                <div>{item.text}</div>
              </div>
            ))}
            <div className="small">Prova: {SUGGESTIONS[0]}</div>
            <div className="actions" style={{ flexWrap: "wrap" }}>
              {SUGGESTIONS.map((item) => (
                <button key={item} className="btn ghost" onClick={() => send(item)} disabled={busy}>
                  {item}
                </button>
              ))}
            </div>
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
              placeholder="Scrivi a Kreluna Director…"
              onChange={(event) => setDraft(event.target.value)}
            />
            <button className="btn" disabled={busy}>
              Invia
            </button>
          </form>
        </section>

        <aside className="stack">
          <div className="panel">
            <h2>PC dello studio</h2>
            {agents.length === 0 ? <div className="small">Nessun agent iscritto. Avvia l’agent locale.</div> : null}
            {agents.map((agent) => (
              <div className="row" key={agent.device_id}>
                <div>
                  <span className={`dot ${agent.presence}`} />
                  <strong>{agent.display_name || agent.agent_id}</strong>
                  <div className="small">
                    {agent.hostname} · {agent.platform} · {agent.capabilities.join(", ")}
                  </div>
                </div>
                <div className="actions">
                  <span className="pill">{agent.killed ? "fermo" : agent.presence}</span>
                  {agent.killed ? (
                    <button className="btn ghost" onClick={() => api.resume(agent.device_id).then(refresh)}>
                      Riprendi
                    </button>
                  ) : null}
                </div>
              </div>
            ))}
          </div>

          <div className="panel">
            <h2>Da approvare</h2>
            {pending.length === 0 ? <div className="small">Nessuna azione sensibile in attesa.</div> : null}
            {pending.map((item) => {
              const observed = ((item.preview.observed as Record<string, string>) || {}) as Record<string, string>;
              const shot = item.task?.evidence[0];
              return (
                <div className="row" key={item.id} style={{ flexDirection: "column", alignItems: "stretch" }}>
                  <div>
                    <strong>Fattura pronta</strong>
                    <div className="small">
                      Cliente: {observed.client} · {observed.total_label} · stato {observed.status}
                    </div>
                  </div>
                  {shot ? <EvidenceImage id={shot.id} /> : null}
                  <div className="actions">
                    <button className="btn ok" onClick={() => api.approve(item.id).then(refresh)}>
                      Approva
                    </button>
                    <button className="btn ghost" onClick={() => api.reject(item.id).then(refresh)}>
                      Rifiuta
                    </button>
                  </div>
                </div>
              );
            })}
          </div>

          <div className="panel">
            <h2>Task</h2>
            {tasks.slice(0, 8).map((task) => (
              <div className="row" key={task.id}>
                <div>
                  <div>{task.goal}</div>
                  <div className="small">{task.capability}</div>
                  {task.evidence[0] ? <EvidenceImage id={task.evidence[0].id} /> : null}
                </div>
                <span className={`pill ${task.status} ${task.risk}`}>{task.status}</span>
              </div>
            ))}
          </div>
        </aside>
      </main>
    </div>
  );
}

function EvidenceImage({ id }: { id: string }) {
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
  return <img className="evidence" src={src} alt="Evidenza del lavoro" />;
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="stat">
      <span className="small">{label}</span>
      <b>{value}</b>
    </div>
  );
}
