"""Finestra gestionale vera sul Mac: si vede aprire e compilare i campi."""

from __future__ import annotations

import json
import sys

from agent.tools.screen_pointer import move_and_click


def run(payload: dict) -> None:
    import tkinter as tk

    account = str(payload.get("account_name") or "")
    client = str(payload.get("client_name") or "")
    description = str(payload.get("description") or "")
    net = float(payload.get("net_eur") or 0)
    vat_rate = float(payload.get("vat_rate", 0.22))
    vat_note = str(payload.get("vat_note") or "")
    vat = round(net * vat_rate, 2)
    total = round(net + vat, 2)
    net_label = f"€ {net:,.2f}"
    vat_label = f"€ {vat:,.2f}"
    total_label = f"€ {total:,.2f}"

    root = tk.Tk()
    root.title("Webdesk / AdE  ·  PC-FATTURE (demo)")
    root.geometry("920x620+80+80")
    root.configure(bg="#ece8de")
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        pass

    navy = "#101828"
    gold = "#c49a2a"
    ink = "#161c26"

    tk.Label(root, text="Webdesk / Agenzia delle Entrate (demo)", bg=navy, fg="#f4efe4", font=("Helvetica", 18, "bold"), anchor="w", padx=20, pady=14).pack(fill="x")
    status = tk.Label(root, text="Apro il programma sul tuo Mac…", bg="#ece8de", fg="#5a606c", font=("Helvetica", 13), anchor="w", padx=24, pady=8)
    status.pack(fill="x")

    form = tk.Frame(root, bg="#ece8de", padx=24, pady=12)
    form.pack(fill="both", expand=True)

    def field(label: str) -> tk.Entry:
        tk.Label(form, text=label, bg="#ece8de", fg="#5a606c", font=("Helvetica", 12)).pack(anchor="w")
        entry = tk.Entry(form, font=("Helvetica", 16), fg=ink, relief="solid", bd=1)
        entry.pack(fill="x", pady=(0, 16), ipady=8)
        return entry

    if account:
        account_entry = field("Azienda emittente")
        account_entry.insert(0, account)
    client_entry = field("Cliente destinatario")
    desc_entry = field("Prestazione")
    money = tk.Frame(form, bg="#ece8de")
    money.pack(fill="x")

    def money_field(parent, label: str) -> tk.Entry:
        box = tk.Frame(parent, bg="#ece8de")
        box.pack(side="left", expand=True, fill="x", padx=(0, 12))
        tk.Label(box, text=label, bg="#ece8de", fg="#5a606c", font=("Helvetica", 12)).pack(anchor="w")
        entry = tk.Entry(box, font=("Helvetica", 16), fg=ink, relief="solid", bd=1)
        entry.pack(fill="x", ipady=8)
        return entry

    net_entry = money_field(money, "Imponibile")
    vat_entry = money_field(money, f"IVA {vat_rate * 100:g}%")
    total_entry = money_field(money, "Totale")
    if vat_note:
        tk.Label(form, text=vat_note, bg="#ece8de", fg="#8a5b12", font=("Helvetica", 12, "bold")).pack(anchor="w", pady=(8, 0))

    buttons = tk.Frame(form, bg="#ece8de")
    buttons.pack(anchor="w", pady=8)
    save = tk.Label(buttons, text="  Salva bozza  ", bg=navy, fg="#f4efe4", font=("Helvetica", 14, "bold"), padx=12, pady=8)
    save.pack(side="left", padx=(0, 12))
    emit = tk.Label(buttons, text="  Emetti (bloccato)  ", bg="#d2d2d2", fg=ink, font=("Helvetica", 14, "bold"), padx=12, pady=8)
    emit.pack(side="left")

    def point_to(widget, *, click: bool = True) -> None:
        root.update_idletasks()
        x = widget.winfo_rootx() + max(1, widget.winfo_width() // 2)
        y = widget.winfo_rooty() + max(1, widget.winfo_height() // 2)
        move_and_click(
            x,
            y,
            screen_width=root.winfo_screenwidth(),
            screen_height=root.winfo_screenheight(),
            start_x=root.winfo_pointerx(),
            start_y=root.winfo_pointery(),
            click=click,
        )
        try:
            widget.focus_force()
        except tk.TclError:
            pass

    def type_into(entry: tk.Entry, text: str, done) -> None:
        point_to(entry)

        def step(index: int = 0) -> None:
            entry.delete(0, tk.END)
            entry.insert(0, text[:index])
            entry.configure(highlightbackground=gold, highlightcolor=gold, highlightthickness=2)
            if index <= len(text):
                root.after(45, lambda: step(index + 1))
            else:
                entry.configure(highlightthickness=1)
                done()

        step()

    def after_client() -> None:
        status.configure(text="Scrivo la prestazione…")
        type_into(desc_entry, description, after_desc)

    def after_desc() -> None:
        status.configure(text="Compilo importi. Nessun invio all'Agenzia.")
        point_to(net_entry)
        net_entry.insert(0, net_label)
        vat_entry.insert(0, vat_label)
        total_entry.insert(0, total_label)
        save.configure(bg=gold)
        root.after(250, lambda: point_to(save, click=False))
        status.configure(text="Bozza pronta sul tuo Mac. Mi fermo prima di emettere.")

    status.configure(text="Sposto il mouse sul cliente e compilo…")
    root.after(350, lambda: type_into(client_entry, client, after_client))
    root.mainloop()


if __name__ == "__main__":
    raw = sys.argv[1] if len(sys.argv) > 1 else "{}"
    run(json.loads(raw))
