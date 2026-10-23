"""Read-only Anki adapter; startup derived from anki-connect-operations."""
import csv
import html
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request

LOCAL_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def invoke(action, timeout=60, **params):
    request = urllib.request.Request('http://127.0.0.1:8765',
        data=json.dumps({'action': action, 'version': 6, 'params': params}).encode('utf-8'),
        headers={'Content-Type': 'application/json'})
    with LOCAL_HTTP.open(request, timeout=timeout) as response:
        result = json.load(response)
    if result.get('error'):
        raise RuntimeError(f'AnkiConnect {action}: {result["error"]}')
    return result['result']


def probe(timeout=2):
    try:
        version = invoke('version', timeout=timeout)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'Local AnkiConnect HTTP {exc.code}') from None
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return None
    if not isinstance(version, int) or version < 6:
        raise RuntimeError('AnkiConnect version 6 or later is required')
    return version


def find_anki(explicit=None):
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file() or path.suffix.lower() != '.exe':
            raise RuntimeError('Specified Anki executable not found')
        return path
    candidates = []
    if found := shutil.which('anki.exe'):
        candidates.append(Path(found))
    import winreg
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive,
                        r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\anki.exe',
                        0, winreg.KEY_READ | view) as key:
                    candidates.append(Path(winreg.QueryValue(key, None).strip('"')))
            except OSError:
                pass
    for variable, relative in [('LOCALAPPDATA', 'Programs/Anki/anki.exe'),
                              ('ProgramFiles', 'Anki/anki.exe'),
                              ('ProgramFiles(x86)', 'Anki/anki.exe')]:
        if os.environ.get(variable):
            candidates.append(Path(os.environ[variable]) / relative)
    return next((p.resolve() for p in candidates if p.is_file()), None)


def ensure_running(executable=None, timeout=45):
    if version := probe():
        return {'ready': True, 'launched': False, 'version': version}
    if os.name != 'nt':
        raise RuntimeError('Start Anki manually; automatic startup is Windows-only')
    processes = subprocess.run(['tasklist.exe', '/FO', 'CSV', '/NH'],
        capture_output=True, text=True, errors='replace', check=True,
        creationflags=subprocess.CREATE_NO_WINDOW)
    running = any(row and row[0].lower() in {'anki.exe', 'anki-console.exe'}
                  for row in csv.reader(io.StringIO(processes.stdout)))
    if not running:
        path = find_anki(executable)
        if path is None:
            raise RuntimeError('Anki installation not found; use --anki-exe PATH')
        subprocess.Popen([str(path)], cwd=str(path.parent), stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if version := probe(max(.001, min(2, deadline-time.monotonic()))):
            return {'ready': True, 'launched': not running, 'version': version}
        time.sleep(min(1, max(0, deadline-time.monotonic())))
    raise RuntimeError('AnkiConnect unavailable after 45s: check profile selection, '
                       'startup dialogs, and whether AnkiConnect is installed/enabled')


class SingleImage(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sources = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag != 'img' or set(attrs) - {'src', 'alt', 'title'}:
            raise ValueError('Image field has unsupported HTML or layout attributes')
        self.sources.append(attrs.get('src', ''))

    def handle_endtag(self, tag):
        if tag != 'img':
            raise ValueError('Image field has unsupported HTML')

    def handle_data(self, data):
        if data.strip():
            raise ValueError('Image field contains additional text')


def source_data(note, templates):
    fields = {k: v['value'] for k, v in note['fields'].items()}
    if not all(k in fields for k in ('Image', 'Masks', 'Mode')):
        raise ValueError('Requires Image/Masks/Mode fields; other occlusion formats are not yet supported')
    if fields['Mode'] != 'free_guess':
        raise ValueError('Only the client-verified free_guess mode is supported')
    # Check interpretation in the front template; never execute source JavaScript.
    fronts = '\n'.join(t.get('Front', '') for t in templates.values())
    for name, index, dimension in [('left', 0, 'Width'), ('top', 1, 'Height'),
                                   ('width', 2, 'Width'), ('height', 3, 'Height')]:
        pattern = (rf'\.style\.{name}\s*=\s*mask\[{index}\]\s*\*\s*img{dimension}'
                   r'''\s*\+\s*["']px["']\s*;''')
        if not re.search(pattern, fronts):
            raise ValueError('Unrecognized template coordinate interpretation')
    parser = SingleImage()
    parser.feed(fields['Image'])
    parser.close()
    if len(parser.sources) != 1:
        raise ValueError('Requires exactly one original image')
    filename = parser.sources[0]
    if not filename or any(c in filename for c in ('/', '\\', ':', '\x00')) or filename in ('.', '..'):
        raise ValueError('Image must reference local Anki media, not an external URL or path')
    groups = json.loads(fields['Masks'])
    if not isinstance(groups, list) or not groups:
        raise ValueError('Masks must be a nonempty list of rectangle groups')
    # Anki reveals every rectangle in one group together; Markji has no such grouping,
    # so convert() flattens each group into separate mask indexes in source order.
    if any(not isinstance(g, list) or not g for g in groups):
        raise ValueError('Each Masks group must be a nonempty list of rectangles')
    title = html.unescape(re.sub(r'<[^>]*>', '', fields.get('Titile', fields.get('Title', '')))).strip()
    return {'note_id': note['noteId'], 'model': note['modelName'],
            'title': title or f'Anki {note["noteId"]}', 'filename': filename, 'groups': groups}


def notes_for(ids):
    result = []
    for offset in range(0, len(ids), 100):
        result.extend(invoke('notesInfo', notes=ids[offset:offset+100]))
    return result
