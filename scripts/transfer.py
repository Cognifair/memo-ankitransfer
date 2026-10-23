"""Reproducible Anki image-occlusion to Markji transfer. See --help."""
import argparse
import base64
from contextlib import contextmanager
from decimal import Decimal, ROUND_HALF_EVEN
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from anki_source import ensure_running, invoke, notes_for, source_data

BASE = 'https://open.maimemo.com/open/api/v1/markji'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def save(path, value):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def convert(groups, size):
    masks, max_parameter, max_edge = [], Decimal(0), Decimal(0)
    flattened = 0
    for group in groups:
        if not isinstance(group, list) or not group:
            raise ValueError('Each reveal group must be a nonempty list of [x,y,width,height]')
        if len(group) > 1:
            flattened += 1
        # Markji has no simultaneous-reveal group, so every rectangle becomes its own
        # mask index in source order: group order first, rectangle order inside a group.
        for rect in group:
            if not isinstance(rect, list) or len(rect) != 4:
                raise ValueError('Expected [x,y,width,height]')
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in rect):
                raise ValueError('Rectangle coordinates must be numbers')
            x, y, w, h = values = [Decimal(str(v)) for v in rect]
            if not all(v.is_finite() for v in values):
                raise ValueError('Non-finite rectangle coordinates')
            if min(x, y) < 0 or min(w, h) <= 0 or x+w > 1 or y+h > 1:
                raise ValueError('Rectangle lies outside the original image')
            quantized = [int((v*10000).to_integral_value(rounding=ROUND_HALF_EVEN)) for v in values]
            left, top, width, height = quantized
            if min(width, height) <= 0 or left+width > 10000 or top+height > 10000:
                raise ValueError('Rectangle cannot be represented without clipping or disappearing')
            masks.append(dict(width=width, height=height, top=top, left=left,
                              index=len(masks)+1, type='rect'))
            errors = [(Decimal(q)/10000-v)*dimension
                      for q, v, dimension in zip(quantized, values, (size[0], size[1], size[0], size[1]))]
            max_parameter = max(max_parameter, *(abs(e) for e in errors))
            max_edge = max(max_edge, abs(errors[0]), abs(errors[1]),
                           abs(errors[0]+errors[2]), abs(errors[1]+errors[3]))
    if not masks:
        raise ValueError('No masks to convert')
    return masks, {'max_parameter_error_pixels': float(max_parameter),
                   'max_edge_error_pixels': float(max_edge),
                   'group_count': len(groups), 'mask_count': len(masks),
                   'flattened_groups': flattened}


def selection(args):
    ids = list(dict.fromkeys(args.note_id)) if args.note_id else invoke('findNotes', query=args.query)
    if not ids:
        raise ValueError('No matching Anki notes')
    if len(ids) > args.max_notes:
        raise ValueError(f'{len(ids)} notes exceed --max-notes={args.max_notes}; narrow query or set an explicit limit')
    notes = notes_for(ids)
    if len(notes) != len(ids):
        raise ValueError('Some selected Anki notes could not be read')
    return notes


def inspect_sources(notes):
    cache, results = {}, []
    for note in notes:
        try:
            model = note['modelName']
            if model not in cache:
                cache[model] = invoke('modelTemplates', modelName=model)
            source = source_data(note, cache[model])
            convert(source['groups'], (1, 1))
            source['template_sha256'] = digest(canonical(cache[model]))
            results.append(source)
        except (ValueError, KeyError, TypeError) as exc:
            results.append({'note_id': note['noteId'], 'unsupported': str(exc)})
    return results


def prepare(args):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        raise RuntimeError('Pillow is required for preview; use an existing Python with Pillow or install Pillow') from None
    ensure_running(args.anki_exe)
    sources = inspect_sources(selection(args))
    unsupported = [s for s in sources if 'unsupported' in s]
    if unsupported:
        emit({'unsupported': unsupported})
        raise ValueError('Selected batch contains unsupported notes; nothing prepared, narrow selection explicitly')
    package = Path(args.out).expanduser().resolve()
    package.mkdir(parents=True, exist_ok=False)
    manifest = {'format': 'memo-ankitransfer/1', 'items': [], 'complete': False}
    save(package / 'manifest.json', manifest)
    for source in sources:
        encoded = invoke('retrieveMediaFile', filename=source['filename'])
        if not encoded:
            raise ValueError(f'Original image missing for note {source["note_id"]}')
        raw = base64.b64decode(encoded, validate=True)
        with Image.open(io.BytesIO(raw)) as original:
            if getattr(original, 'n_frames', 1) != 1 or original.getexif().get(274, 1) != 1:
                raise ValueError('Animated or EXIF-rotated image is not supported')
            formats = {'PNG': ('png', 'image/png'), 'JPEG': ('jpg', 'image/jpeg'), 'WEBP': ('webp', 'image/webp')}
            if original.format not in formats:
                raise ValueError('Image format not verified; supported: PNG/JPEG/WebP')
            extension, mime = formats[original.format]
            size = list(original.size)
            preview = original.convert('RGB')
        masks, errors = convert(source['groups'], size)
        folder = package / str(source['note_id'])
        folder.mkdir()
        image_path, mask_path = folder / f'original.{extension}', folder / 'mask.msk1'
        image_path.write_bytes(raw)
        mask_path.write_bytes(canonical(masks))
        draw = ImageDraw.Draw(preview)
        for mask in masks:
            left, top = mask['left']*size[0]/10000, mask['top']*size[1]/10000
            draw.rectangle((left, top, left+mask['width']*size[0]/10000,
                            top+mask['height']*size[1]/10000), fill='#36b59d')
        preview.save(folder / 'preview.png')
        manifest['items'].append({**source, 'source_sha256': digest(canonical(source)),
            'image': image_path.relative_to(package).as_posix(),
            'mask': mask_path.relative_to(package).as_posix(),
            'preview': (folder / 'preview.png').relative_to(package).as_posix(),
            'image_sha256': digest(raw), 'mask_sha256': digest(mask_path.read_bytes()),
            'mime': mime, 'size': size, 'mask_count': len(masks), **errors})
        save(package / 'manifest.json', manifest)
    manifest['complete'] = True
    save(package / 'manifest.json', manifest)
    emit({'package': str(package), 'notes': len(manifest['items']),
          'masks': sum(i['mask_count'] for i in manifest['items']),
          'groups': sum(i['group_count'] for i in manifest['items']),
          'flattened_groups': sum(i['flattened_groups'] for i in manifest['items']),
          'status': 'prepared; not uploaded'})


def safe_path(package, relative):
    path = (package / relative).resolve()
    if not path.is_relative_to(package) or path == package:
        raise ValueError('Package path escapes its directory')
    return path


def read_package(location):
    try:
        from PIL import Image
    except ImportError:
        raise RuntimeError('Package verification requires Pillow; use a Python environment with Pillow') from None
    package = Path(location).expanduser().resolve()
    manifest = load(package / 'manifest.json')
    if manifest.get('format') != 'memo-ankitransfer/1' or not manifest.get('complete') or not manifest.get('items'):
        raise ValueError('Package is incomplete or has an unsupported format')
    ids = [i['note_id'] for i in manifest['items']]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate source note IDs in package')
    for item in manifest['items']:
        source = {key: item[key] for key in ('note_id', 'model', 'title', 'filename', 'groups', 'template_sha256')}
        if digest(canonical(source)) != item['source_sha256']:
            raise ValueError('Source metadata changed since preparation')
        for key in ('image', 'mask'):
            if digest(safe_path(package, item[key]).read_bytes()) != item[key+'_sha256']:
                raise ValueError(f'{key} changed since preparation')
        with Image.open(safe_path(package, item['image'])) as original:
            mime = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'WEBP': 'image/webp'}.get(original.format)
            if (list(original.size) != item['size'] or mime != item['mime']
                    or getattr(original, 'n_frames', 1) != 1 or original.getexif().get(274, 1) != 1):
                raise ValueError('Image dimensions, format, or orientation differ from manifest')
        masks, _ = convert(item['groups'], item['size'])
        if masks != load(safe_path(package, item['mask'])) or len(masks) != item['mask_count']:
            raise ValueError('Mask no longer matches source coordinates')
    return package, manifest


class API:
    def __init__(self):
        self.token = os.environ.get('MAIMEMO_TOKEN', '').strip()
        if not self.token:
            raise RuntimeError('MAIMEMO_TOKEN is missing; configure your own official API key securely')
        self.last_request = 0

    def call(self, method, path, payload=None, data=None, content_type=None):
        if not path.startswith('/') or path.startswith('//'):
            raise ValueError('Invalid API path')
        delay = 1.6 - (time.monotonic()-self.last_request)
        if delay > 0:
            time.sleep(delay)
        if payload is not None:
            data, content_type = canonical(payload), 'application/json'
        request = urllib.request.Request(BASE+path, data=data, method=method,
            headers={'Authorization': 'Bearer '+self.token, 'Accept': 'application/json',
                     **({'Content-Type': content_type} if content_type else {})})
        self.last_request = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            # Do not log raw bodies: they can include signed media URLs or echoed inputs.
            retry = exc.headers.get('Retry-After', '')
            raise RuntimeError(f'Official API HTTP {exc.code}; Retry-After={retry or "not provided"}; no automatic retry') from None
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            raise RuntimeError('Official API transport failed; mutation may have completed; inspect receipt before retry') from None
        if isinstance(result, dict) and isinstance(result.get('data'), dict):
            result = result['data']
        return result

    def decks(self):
        result, offset = [], 0
        while True:
            page = self.call('GET', f'/decks?offset={offset}&limit=100')
            batch = page['decks']
            result.extend(batch)
            offset += len(batch)
            if not batch or offset >= page['total']:
                return result

    def chapters(self, deck, cards=False):
        return self.call('GET', f'/decks/{segment(deck)}/chapters?with_cards={str(cards).lower()}')

    def upload(self, path, mime, deck):
        boundary = 'MemoAnki'+uuid.uuid4().hex
        data = (f'--{boundary}\r\nContent-Disposition: form-data; name="deck_id"\r\n\r\n{deck}\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
                f'Content-Type: {mime}\r\n\r\n').encode() + path.read_bytes() + f'\r\n--{boundary}--\r\n'.encode()
        return self.call('POST', '/files', data=data,
                         content_type=f'multipart/form-data; boundary={boundary}')['file']['id']


def segment(value):
    return urllib.parse.quote(value, safe='')


def resolve_target(api, args):
    decks = api.decks()
    matches = [d for d in decks if (d['id'] == args.deck_id if args.deck_id
               else d['name'].strip().casefold() == args.deck.strip().casefold())]
    if len(matches) != 1:
        raise ValueError('Target deck missing or ambiguous; specify exact --deck-id')
    deck = matches[0]
    response = api.chapters(deck['id'])
    chapters = response['chapters']
    if args.command == 'targets':
        return deck, chapters
    if args.chapter_id:
        chapters = [c for c in chapters if c['id'] == args.chapter_id]
    elif args.chapter:
        chapters = [c for c in chapters if c['name'] == args.chapter]
    if len(chapters) != 1:
        raise ValueError('Specify an unambiguous existing --chapter or --chapter-id')
    return deck, chapters[0]


def content_for(item, record):
    title = re.sub(r'([\\\[\]#])', r'\\\1', item['title'].replace('\n', ' '))
    return f'[P#H1#{title}]\n[Pic#ID/{record["image_id"]},MID/{record["mask_id"]}#]\n'


def verify_card(api, target, item, record):
    deck, chapter = target['deck_id'], target['chapter_id']
    card = api.call('GET', f'/decks/{segment(deck)}/cards/{segment(record["card_id"])}')['card']
    expected = content_for(item, record)
    files = {f['id']: f for f in card.get('files', [])}
    chapters = api.chapters(deck)['chapters']
    selected = next((c for c in chapters if c['id'] == chapter), None)
    image, mask = files.get(record['image_id'], {}), files.get(record['mask_id'], {})
    checks = {'content': card['content'] == expected, 'grammar_version': card.get('grammar_version') == 3,
        'deck': card.get('deck_id') == deck,
        'chapter': selected is not None and card['id'] in selected.get('card_ids', []),
        'image_mime': image.get('mime') == item['mime'],
        'mask_mime': mask.get('mime') == 'markji/mask',
        'image_size': [image.get('info', {}).get('width'), image.get('info', {}).get('height')] == item['size']}
    if not all(checks.values()):
        raise RuntimeError('Readback mismatch: '+', '.join(k for k, v in checks.items() if not v))
    return checks


@contextmanager
def package_lock(package):
    lock = package / 'import.lock'
    with lock.open('x', encoding='utf-8') as stream:
        stream.write(str(os.getpid()))
    try:
        yield
    finally:
        lock.unlink()


def import_package(args):
    if not args.write:
        raise ValueError('Live import requires --write and user authorization for this source and target')
    package, manifest = read_package(args.package)
    with package_lock(package):
        api = API()
        deck, chapter = resolve_target(api, args)
        target = {'deck_id': deck['id'], 'chapter_id': chapter['id']}
        receipt_path = package / 'receipt.json'
        receipt = load(receipt_path) if receipt_path.exists() else {
            'format': 'memo-ankitransfer/1', 'target': target,
            'manifest_sha256': digest(canonical(manifest)), 'items': {},
            'initial_chapter_card_ids': chapter.get('card_ids', [])}
        if receipt['target'] != target or receipt['manifest_sha256'] != digest(canonical(manifest)):
            raise ValueError('Package receipt targets a different deck/chapter or changed manifest')
        save(receipt_path, receipt)
        reused, created = 0, 0
        for item in manifest['items']:
            key = str(item['note_id'])
            record = receipt['items'].setdefault(key, {})
            if record.get('card_id'):
                record['checks'] = verify_card(api, target, item, record)
                record['stage'] = 'verified'
                reused += 1
                save(receipt_path, receipt)
                continue
            if record.get('stage') == 'card_pending':
                snapshot = api.chapters(deck['id'], cards=True)
                current = next(c for c in snapshot['chapters'] if c['id'] == chapter['id'])
                added = set(current.get('card_ids', [])) - set(record['before_card_ids'])
                matches = [c for c in snapshot.get('cards', []) if c['id'] in added
                           and c.get('content') == content_for(item, record)]
                if len(matches) != 1:
                    raise RuntimeError('Previous create is uncertain; cannot uniquely reconcile; no retry sent')
                record['card_id'] = matches[0]['id']
                save(receipt_path, receipt)
                record['checks'] = verify_card(api, target, item, record)
                record['stage'] = 'verified'
                reused += 1
                save(receipt_path, receipt)
                continue
            for field, path_key, mime in [('image_id', 'image', item['mime']), ('mask_id', 'mask', 'markji/mask')]:
                if record.get(field):
                    continue
                if record.get('stage', '').endswith('_pending'):
                    raise RuntimeError('Previous upload response is uncertain; inspect receipt; no duplicate upload sent')
                record['stage'] = field+'_pending'
                save(receipt_path, receipt)
                record[field] = api.upload(safe_path(package, item[path_key]), mime, deck['id'])
                record['stage'] = field+'_uploaded'
                save(receipt_path, receipt)
            snapshot = api.chapters(deck['id'])
            current = next(c for c in snapshot['chapters'] if c['id'] == chapter['id'])
            record['before_card_ids'] = current.get('card_ids', [])
            record['content'] = content_for(item, record)
            record['stage'] = 'card_pending'
            save(receipt_path, receipt)
            response = api.call('POST', f'/decks/{segment(deck["id"])}/chapters/{segment(chapter["id"])}/cards',
                {'card': {'content': record['content'], 'grammar_version': 3}})
            record['card_id'] = response['card']['id']
            save(receipt_path, receipt)
            record['checks'] = verify_card(api, target, item, record)
            record['stage'] = 'verified'
            created += 1
            save(receipt_path, receipt)
        after = next(c for c in api.chapters(deck['id'])['chapters'] if c['id'] == chapter['id'])
        actual = set(after.get('card_ids', []))
        expected = set(receipt['initial_chapter_card_ids']) | {r['card_id'] for r in receipt['items'].values()}
        receipt['chapter_list_matches_expected'] = actual == expected
        save(receipt_path, receipt)
        emit({'created': created, 'reused': reused, 'verified': len(manifest['items']),
              'chapter_list_matches_expected': actual == expected,
              'client_rendering': 'awaiting user confirmation', 'receipt': str(receipt_path)})


def verify_package(args):
    package, manifest = read_package(args.package)
    receipt = load(package / 'receipt.json')
    if receipt['manifest_sha256'] != digest(canonical(manifest)):
        raise ValueError('Manifest differs from imported package')
    api = API()
    results = []
    for item in manifest['items']:
        record = receipt['items'].get(str(item['note_id']), {})
        if not record.get('card_id'):
            raise ValueError(f'Note {item["note_id"]} has not been imported')
        results.append({'note_id': item['note_id'], 'card_id': record['card_id'],
                        'checks': verify_card(api, receipt['target'], item, record)})
    emit({'verified': results, 'client_rendering': 'not checked by API'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    doctor = commands.add_parser('doctor', help='Connect to or start Anki; no account access')
    scan = commands.add_parser('scan', help='Read selected notes and report compatibility')
    prepare_parser = commands.add_parser('prepare', help='Create local files and previews only')
    for command in (doctor, scan, prepare_parser):
        command.add_argument('--anki-exe')
    for command in (scan, prepare_parser):
        sources = command.add_mutually_exclusive_group(required=True)
        sources.add_argument('--note-id', type=int, action='append', help='Repeat for multiple notes')
        sources.add_argument('--query', help='Anki search expression')
        command.add_argument('--max-notes', type=int, default=500)
    scan.add_argument('--show', type=int, default=20, help='Display limit; all selected notes are scanned')
    prepare_parser.add_argument('--out', required=True, help='A new directory; never overwrites existing packages')
    targets = commands.add_parser('targets', help='List matching deck and its existing chapters')
    importer = commands.add_parser('import', help='Upload and create authorized cards')
    for command in (targets, importer):
        group = command.add_mutually_exclusive_group(required=True)
        group.add_argument('--deck')
        group.add_argument('--deck-id')
    group = importer.add_mutually_exclusive_group()
    group.add_argument('--chapter')
    group.add_argument('--chapter-id')
    importer.add_argument('--package', required=True)
    importer.add_argument('--write', action='store_true')
    verifier = commands.add_parser('verify', help='Read back imported cards without modifying anything')
    verifier.add_argument('--package', required=True)
    args = parser.parse_args()
    if args.command == 'doctor':
        emit(ensure_running(args.anki_exe))
    elif args.command == 'scan':
        ensure_running(args.anki_exe)
        sources = inspect_sources(selection(args))
        supported = [s for s in sources if 'unsupported' not in s]
        rows = []
        for source in supported[:max(0, args.show)]:
            _, counts = convert(source['groups'], (1, 1))
            rows.append({k: source[k] for k in ('note_id', 'model', 'title')} |
                        {'groups': counts['group_count'], 'masks': counts['mask_count'],
                         'flattened_groups': counts['flattened_groups']})
        emit({'total': len(sources), 'supported': len(supported),
              'flattened_notes': sum(1 for s in supported
                                     if any(len(g) > 1 for g in s['groups'])),
              'unsupported': [s for s in sources if 'unsupported' in s],
              'examples': rows})
    elif args.command == 'prepare':
        prepare(args)
    elif args.command == 'targets':
        deck, chapters = resolve_target(API(), args)
        emit({'deck': {'id': deck['id'], 'name': deck['name'], 'cards': deck['card_count']},
              'chapters': [{'id': c['id'], 'name': c['name'], 'cards': len(c.get('card_ids', []))} for c in chapters]})
    elif args.command == 'import':
        import_package(args)
    elif args.command == 'verify':
        verify_package(args)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        print(f'{type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(1)
