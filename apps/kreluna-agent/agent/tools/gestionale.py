"""Compatibility tombstone: the invoice simulator has been removed permanently."""


def show_invoice_on_this_mac(**kwargs):
    raise RuntimeError("SIMULATORE_FATTURE_RIMOSSO: utilizzare solo Webdesk reale.")


def fill_invoice_on_pc(**kwargs):
    raise RuntimeError("SIMULATORE_FATTURE_RIMOSSO: nessuna bozza simulata creata.")
