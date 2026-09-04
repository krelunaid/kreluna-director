"""Reject direct calls from obsolete code. The registered workflow uses Webdesk."""


async def prepare(**kwargs):
    raise RuntimeError("SIMULATORE_FATTURE_RIMOSSO: usare portal_open per Webdesk.")


async def submit(**kwargs):
    raise RuntimeError("SIMULATORE_FATTURE_RIMOSSO: nessuna emissione consentita.")
