"""Explicit, short-lived manual session on the primary Mac screen.

Busy workers are never cancelled or restarted by this protocol.
Frames and typed text remain in memory, never task evidence or logs.
"""
import asyncio
import base64
import ctypes
import io
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image


class Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class Size(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class Rect(ctypes.Structure):
    _fields_ = [("origin", Point), ("size", Size)]


def quartz():
    if sys.platform != "darwin":
        raise RuntimeError("Questa versione dell’assistenza supporta solo macOS")
    q = ctypes.CDLL('/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices')
    q.CFRelease.argtypes = [ctypes.c_void_p]
    q.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    return q


_screen_permission_requested = False


def require_screen_permission(q):
    global _screen_permission_requested
    q.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
    if q.CGPreflightScreenCaptureAccess():
        return
    # This path is reached only after the user explicitly opens remote view.
    # Request from the actual worker, not an unrelated terminal or Finder entry.
    if not _screen_permission_requested:
        _screen_permission_requested = True
        q.CGRequestScreenCaptureAccess.restype = ctypes.c_bool
        if q.CGRequestScreenCaptureAccess():
            return
    raise RuntimeError("macOS non ha ancora autorizzato il processo di cattura. Consenti la richiesta mostrata da Kreluna Agent (o dal suo Python), poi riavvia Kreluna Agent. Nessuna immagine acquisita.")


def _frame_from_payload(frame: dict):
    if frame.get('error'):
        raise RuntimeError(frame['error'])
    if not frame.get('image') or frame.get('width', 0) <= 0 or frame.get('height', 0) <= 0:
        raise RuntimeError('Risposta di cattura nativa non valida')
    return frame['image'], (frame['width'], frame['height'])


def capture_via_socket(path: str):
    """Ask the LS-launched app process for a frame (same TCC identity)."""
    import socket

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(10)
        sock.connect(path)
        sock.sendall(b'{"op":"capture"}\n')
        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            if b'\n' in chunk:
                break
    raw = b''.join(chunks).split(b'\n', 1)[0]
    return _frame_from_payload(json.loads(raw.decode()))


def capture():
    sock = os.environ.get('KRELUNA_NATIVE_CAPTURE_SOCK')
    if sock:
        return capture_via_socket(sock)
    native = os.environ.get('KRELUNA_NATIVE_CAPTURE')
    if native:
        # Legacy CLI path. Prefer KRELUNA_NATIVE_CAPTURE_SOCK: a fresh
        # `Kreluna --capture-frame` process often loses Screen Recording after re-sign.
        result = subprocess.run([native, '--capture-frame'], check=True,
                                capture_output=True, timeout=10)
        return _frame_from_payload(json.loads(result.stdout))
    q = quartz()
    require_screen_permission(q)
    q.CGMainDisplayID.restype = ctypes.c_uint32
    q.CGDisplayBounds.argtypes = [ctypes.c_uint32]
    q.CGDisplayBounds.restype = Rect
    display = q.CGMainDisplayID()
    bounds = q.CGDisplayBounds(display)
    size = (bounds.size.width, bounds.size.height)
    with tempfile.TemporaryDirectory(prefix='kreluna-live-') as folder:
        path = Path(folder) / 'frame.png'
        subprocess.run(['screencapture', '-x', '-D', '1', str(path)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=6)
        with Image.open(path) as image:
            image = image.convert('RGB')
            image.thumbnail((1440, 1000))
            output = io.BytesIO()
            image.save(output, format='JPEG', quality=65)
    return base64.b64encode(output.getvalue()).decode(), size


def input_event(body, size):
    q = quartz()
    q.AXIsProcessTrusted.restype = ctypes.c_bool
    if not q.AXIsProcessTrusted():
        raise RuntimeError("Consenti Accessibilità a Kreluna Agent sul Mac remoto")
    if body['action'] in {'click', 'scroll'}:
        q.CGEventCreateMouseEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, Point, ctypes.c_uint32]
        q.CGEventCreateMouseEvent.restype = ctypes.c_void_p
        kinds = (5,) if body['action'] == 'scroll' else (5, 1, 2)
        events = [(kind, Point(body['x'] * size[0], body['y'] * size[1])) for kind in kinds]
        for kind, point in events:
            event = q.CGEventCreateMouseEvent(None, kind, point, 0)
            if not event:
                raise RuntimeError("Evento mouse non disponibile")
            try:
                q.CGEventPost(0, event)
            finally:
                q.CFRelease(event)
        if body['action'] == 'scroll':
            q.CGEventCreateScrollWheelEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
            q.CGEventCreateScrollWheelEvent.restype = ctypes.c_void_p
            event = q.CGEventCreateScrollWheelEvent(None, 0, 1, ctypes.c_int32(-body['delta_y']))
            if not event:
                raise RuntimeError("Scorrimento non disponibile")
            try:
                q.CGEventPost(0, event)
            finally:
                q.CFRelease(event)
        return
    keys = {'Enter':36, 'Tab':48, 'Backspace':51, 'Escape':53,
            'ArrowLeft':123, 'ArrowRight':124, 'ArrowDown':125, 'ArrowUp':126}
    key = keys.get(body.get('key'), 0)
    text = body.get('text', '') if body['action'] == 'text' else ''
    if body['action'] == 'key' and body.get('key') not in keys:
        raise RuntimeError("Tasto non supportato")
    q.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
    q.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
    q.CGEventKeyboardSetUnicodeString.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_uint16)]
    raw = text.encode('utf-16-le')
    units = (ctypes.c_uint16 * (len(raw)//2)).from_buffer_copy(raw)
    for down in (True, False):
        event = q.CGEventCreateKeyboardEvent(None, key, down)
        if not event:
            raise RuntimeError("Evento tastiera non disponibile")
        try:
            if text:
                q.CGEventKeyboardSetUnicodeString(event, len(units), units)
            q.CGEventPost(0, event)
        finally:
            q.CFRelease(event)


class RemoteControl:
    def __init__(self, safety):
        self.safety = safety
        self.session_id = ''
        self.owner = ''
        self.until = 0.0
        self.control = False
        self.frame_id = ''
        self.frame_at = 0.0
        self.size = (0, 0)

    def close(self):
        self.session_id = ''
        self.owner = ''
        self.control = False
        self.frame_id = ''
        self.safety.remote_active = False

    def expire(self):
        if self.session_id and time.monotonic() >= self.until:
            self.close()

    async def execute(self, body):
        self.expire()
        try:
            action = body.get('action')
            if self.safety.killed:
                self.close()
                raise RuntimeError("Agent fermato")
            if action == 'start':
                if self.session_id:
                    raise RuntimeError("Un’altra sessione di assistenza è già aperta")
                if self.safety.active_task_id or self.safety.gui_lock.locked() or self.safety.workers:
                    raise RuntimeError("Agent occupato: attendi il termine o il blocco del lavoro. Nessun lavoro è stato interrotto")
                self.safety.remote_active = True
                self.session_id = secrets.token_hex(24)
                self.owner = body.get('owner')
                self.until = time.monotonic() + 30
                try:
                    data, self.size = await asyncio.to_thread(capture)
                except Exception:
                    self.close()
                    raise
                return self.frame(data)
            if not self.session_id or body.get('session_id') != self.session_id or body.get('owner') != self.owner:
                raise RuntimeError("Sessione remota scaduta o non autorizzata")
            self.until = time.monotonic() + 30
            if action == 'close':
                self.close()
                return {'ok': True}
            if action == 'control':
                self.control = True
                return {'ok': True, 'control': True}
            if action == 'frame':
                data, self.size = await asyncio.to_thread(capture)
                return self.frame(data)
            if action not in {'click', 'scroll', 'key', 'text'} or not self.control:
                raise RuntimeError("Premi Intervieni prima di usare mouse o tastiera")
            if body.get('frame_id') != self.frame_id or time.monotonic() - self.frame_at > 5:
                raise RuntimeError("Immagine non aggiornata: attendi una nuova schermata")
            if not (0 <= body.get('x', 0) < 1 and 0 <= body.get('y', 0) < 1) or len(body.get('text', '')) > 256:
                raise RuntimeError("Comando non valido")
            if action == 'scroll' and (type(body.get('delta_y')) is not int or not -800 <= body['delta_y'] <= 800):
                raise RuntimeError("Scorrimento non valido")
            self.frame_id = ''  # A second action requires a fresh observation.
            await asyncio.to_thread(input_event, body, self.size)
            return {'ok': True}
        except Exception as exc:
            # Never serialize native exceptions that could include typed text.
            error = str(exc) if isinstance(exc, RuntimeError) else 'Operazione remota non riuscita: verifica i permessi sul PC'
            return {'ok': False, 'error': error}

    def frame(self, data):
        self.frame_id = secrets.token_hex(16)
        self.frame_at = time.monotonic()
        return {'ok': True, 'session_id': self.session_id, 'frame_id': self.frame_id,
                'image': data, 'control': self.control, 'screen': 'Schermo principale'}
