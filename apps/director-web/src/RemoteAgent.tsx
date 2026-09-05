import { useEffect, useRef, useState } from "react";
import { token } from "./lib/api";

type Frame = { session_id: string; frame_id: string; image: string; control: boolean };

export function RemoteAgent({ deviceId }: { deviceId: string }) {
  const [frame, setFrame] = useState<Frame | null>(null);
  const [control, setControl] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [text, setText] = useState("");
  const session = useRef("");
  const inFlight = useRef(false);
  const mounted = useRef(true);
  const panel = useRef<HTMLDivElement>(null);

  async function send(action: string, extra: Record<string, unknown> = {}) {
    const response = await fetch(`/agents/${encodeURIComponent(deviceId)}/remote-control`, {
      method: "POST", cache: "no-store", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token()}` },
      body: JSON.stringify({ action, session_id: session.current, ...extra }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Collegamento remoto non disponibile");
    return result;
  }

  async function act(action: string, extra: Record<string, unknown> = {}) {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true);
    try {
      const result = await send(action, { frame_id: frame?.frame_id || "", ...extra });
      if (result.session_id) session.current = result.session_id;
      if (!mounted.current) {
        if (session.current) await send("close");
        return;
      }
      setError("");
      if (action === "close") { session.current = ""; setFrame(null); setControl(false); setText(""); }
      else if (action === "start" || action === "frame") setFrame(result);
      else if (action === "control") setControl(true);
      else { setText(""); setFrame(await send("frame")); }
    } catch (e) {
      if (mounted.current) { setError(e instanceof Error ? e.message : "Errore remoto"); setControl(false); setFrame(null); }
      if (session.current) { try { await send("close"); } catch { /* Agent lease expires independently. */ } session.current = ""; }
    } finally { inFlight.current = false; if (mounted.current) setBusy(false); }
  }

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (session.current) void send("close").catch(() => undefined);
    };
  }, [deviceId]);

  useEffect(() => {
    if (!frame) return;
    const timer = window.setInterval(() => { if (!document.hidden) void act("frame"); }, 2000);
    return () => window.clearInterval(timer);
  }, [frame]);

  return <div className="remote-live" ref={panel}>
    <div className="agent-view-notice"><strong>{frame ? control ? "Controllo manuale · Automazione esclusa" : "Schermo remoto · Sola osservazione" : "Assistenza remota · macOS"}</strong><p>Condividi lo schermo principale, incluse eventuali informazioni visibili. Nessuna registrazione. L’apertura richiede che l’Agent non stia eseguendo un lavoro.</p></div>
    {error ? <p role="alert">{error}</p> : null}
    <div className="agent-view-toolbar">
      {!frame ? <button disabled={busy} onClick={() => void act("start")}>{busy ? "Collegamento…" : "Apri schermo remoto"}</button> : <>
        <button disabled={busy || control} onClick={() => void act("control")}>Intervieni</button>
        <button onClick={() => void panel.current?.requestFullscreen().catch(() => setError("Schermo intero non disponibile"))}>Schermo intero</button>
        <button disabled={busy} onClick={() => void act("close")}>Chiudi e libera il PC</button>
      </>}
    </div>
    {frame ? <>
      <p role="status">Aggiornamento ogni 2 secondi · {control ? "Clicca sull’immagine per scegliere il campo" : "Premi Intervieni per abilitare i clic"}</p>
      <img className="remote-live-image" src={`data:image/jpeg;base64,${frame.image}`} alt="Schermo principale del PC remoto" onClick={event => {
        if (!control || busy) return;
        const rect = event.currentTarget.getBoundingClientRect();
        void act("click", { x: (event.clientX - rect.left) / rect.width, y: (event.clientY - rect.top) / rect.height });
      }} />
      {control ? <form onSubmit={event => { event.preventDefault(); if (text) void act("text", { text }); }}>
        <label>Testo da inserire nel campo selezionato<input type="password" autoComplete="off" maxLength={256} value={text} onChange={event => setText(event.target.value)} /></label>
        <button disabled={busy || !text}>Inserisci testo</button>
        <div className="agent-view-toolbar">{["Tab", "Backspace", "Escape", "Enter"].map(key => <button type="button" disabled={busy} key={key} onClick={() => { if (key !== "Enter" || window.confirm("Inviare il tasto Invio al PC remoto? Può confermare il modulo selezionato.")) void act("key", { key }); }}>{key === "Enter" ? "Invio…" : key}</button>)}</div>
      </form> : null}
      <p>Chiudere libera il PC. Non riavvia e non duplica il lavoro interrotto. La ripresa automatica della fattura non è ancora disponibile.</p>
    </> : null}
  </div>;
}
