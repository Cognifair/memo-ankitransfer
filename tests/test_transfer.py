"""Offline behavior tests. No Anki or Markji writes are performed."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from PIL import Image
import transfer as t
from anki_source import source_data


class FakeAPI:
    def __init__(self):
        self.cards = {}
        self.files = {}
        self.uploads = 0
        self.creates = 0
        self.lose_create_response = False
        self.fail_upload_at = 0

    def decks(self):
        return [{'id': 'deck', 'name': 'Target', 'card_count': len(self.cards)}]

    def chapters(self, deck, cards=False):
        response = {'chapters': [{'id': 'chapter', 'name': 'Default', 'card_ids': list(self.cards)}]}
        if cards:
            response['cards'] = list(self.cards.values())
        return response

    def upload(self, path, mime, deck):
        self.uploads += 1
        if self.uploads == self.fail_upload_at:
            raise RuntimeError('Simulated lost upload response')
        fid = f'file{self.uploads}'
        self.files[fid] = {'id': fid, 'mime': mime,
                           'info': {'width': 100, 'height': 80} if mime.startswith('image/') else {}}
        return fid

    def call(self, method, path, payload=None):
        if method == 'GET':
            return {'card': self.cards[path.rsplit('/', 1)[1]]}
        self.creates += 1
        cid = f'card{self.creates}'
        card = {'id': cid, 'deck_id': 'deck', **payload['card'], 'files': list(self.files.values())}
        self.cards[cid] = card
        if self.lose_create_response:
            self.lose_create_response = False
            raise RuntimeError('Simulated lost create response')
        return {'card': card}


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='memo-ankitransfer-test-')
        self.addCleanup(self.temporary.cleanup)
        self.package = Path(self.temporary.name)
        source = {'note_id': 123, 'model': 'Example', 'title': 'Sample', 'filename': 'image.png',
                  'groups': [[[.2312, .188, .2189, .0146]]], 'template_sha256': 'template-digest'}
        raw = io.BytesIO()
        Image.new('RGB', (100, 80), 'white').save(raw, format='PNG')
        (self.package / 'image.png').write_bytes(raw.getvalue())
        masks, errors = t.convert(source['groups'], [100, 80])
        (self.package / 'mask.msk1').write_bytes(t.canonical(masks))
        item = {**source, 'source_sha256': t.digest(t.canonical(source)),
                'image': 'image.png', 'mask': 'mask.msk1', 'preview': 'preview.png',
                'image_sha256': t.digest(raw.getvalue()), 'mask_sha256': t.digest(t.canonical(masks)),
                'mime': 'image/png', 'size': [100, 80], 'mask_count': 1, **errors}
        t.save(self.package / 'manifest.json', {'format': 'memo-ankitransfer/1', 'complete': True, 'items': [item]})
        self.api = FakeAPI()
        self.args = SimpleNamespace(write=True, package=str(self.package), command='import',
                                    deck='Target', deck_id=None, chapter=None, chapter_id=None)

    def run_import(self):
        with patch.object(t, 'API', return_value=self.api), redirect_stdout(io.StringIO()) as output:
            t.import_package(self.args)
        return json.loads(output.getvalue())

    def test_four_decimal_coordinates_are_exact(self):
        masks, errors = t.convert([[[.2312, .188, .2189, .0146]]], [2481, 3509])
        self.assertEqual(masks[0], dict(left=2312, top=1880, width=2189, height=146, index=1, type='rect'))
        self.assertEqual(errors['max_edge_error_pixels'], 0)

    def test_quantization_error_is_reported(self):
        _, errors = t.convert([[[.123456, .234567, .111111, .222222]]], [4000, 3000])
        self.assertGreater(errors['max_parameter_error_pixels'], 0)
        self.assertLessEqual(errors['max_parameter_error_pixels'], .2)
        self.assertLessEqual(errors['max_edge_error_pixels'], .4)

    def test_unsupported_or_invalid_rectangles_fail(self):
        for groups in ([[[True, 0, .1, .1]]], [[[float('nan'), 0, .1, .1]]],
                       [[[.9, 0, .2, .1]]], [[[0, 0, .000001, .1]]],
                       [[]], [[[0, 0, .1, .1], [.2, .2]]]):
            with self.subTest(groups=groups), self.assertRaises(ValueError):
                t.convert(groups, (100, 80))

    def test_multi_rectangle_groups_flatten_in_source_order(self):
        groups = [[[.1, .1, .1, .1]], [[.2, .2, .1, .1], [.3, .3, .1, .1]], [[.4, .4, .1, .1]]]
        masks, counts = t.convert(groups, (100, 80))
        self.assertEqual([m['index'] for m in masks], [1, 2, 3, 4])
        self.assertEqual([m['left'] for m in masks], [1000, 2000, 3000, 4000])
        self.assertEqual((counts['group_count'], counts['mask_count'], counts['flattened_groups']), (3, 4, 1))

    def test_tampered_mask_and_path_traversal_fail(self):
        (self.package / 'mask.msk1').write_text('[]')
        with self.assertRaises(ValueError):
            t.read_package(str(self.package))
        with self.assertRaises(ValueError):
            t.safe_path(self.package, '../outside')

    def test_manifest_dimension_tampering_fails_before_upload(self):
        manifest = t.load(self.package / 'manifest.json')
        manifest['items'][0]['size'] = [200, 80]
        t.save(self.package / 'manifest.json', manifest)
        with self.assertRaises(ValueError):
            self.run_import()
        self.assertEqual(self.api.uploads, 0)

    def test_import_is_idempotent_for_same_package(self):
        self.assertEqual(self.run_import()['created'], 1)
        second = self.run_import()
        self.assertEqual(second['created'], 0)
        self.assertEqual(second['reused'], 1)
        self.assertEqual((self.api.uploads, self.api.creates), (2, 1))
        self.assertFalse((self.package / 'import.lock').exists())

    def test_create_response_loss_reconciles_without_duplicate(self):
        self.api.lose_create_response = True
        with self.assertRaises(RuntimeError):
            self.run_import()
        self.assertEqual(t.load(self.package / 'receipt.json')['items']['123']['stage'], 'card_pending')
        self.assertEqual(self.run_import()['reused'], 1)
        self.assertEqual(self.api.creates, 1)

    def test_unknown_create_without_match_is_not_retried(self):
        self.api.lose_create_response = True
        with self.assertRaises(RuntimeError):
            self.run_import()
        self.api.cards.clear()
        with self.assertRaises(RuntimeError):
            self.run_import()
        self.assertEqual(self.api.creates, 1)

    def test_upload_response_loss_blocks_reupload(self):
        self.api.fail_upload_at = 2
        with self.assertRaises(RuntimeError):
            self.run_import()
        with self.assertRaises(RuntimeError):
            self.run_import()
        self.assertEqual((self.api.uploads, self.api.creates), (2, 0))

    def test_lock_prevents_simultaneous_same_package_import(self):
        (self.package / 'import.lock').write_text('another-process')
        with self.assertRaises(FileExistsError):
            self.run_import()
        self.assertEqual(self.api.uploads, 0)

    def test_explicit_write_flag_required(self):
        self.args.write = False
        with self.assertRaises(ValueError):
            self.run_import()
        self.assertEqual(self.api.uploads, 0)

    def test_changing_target_does_not_reuse_receipt(self):
        self.run_import()
        self.api.decks = lambda: [{'id': 'different', 'name': 'Target'}]
        with self.assertRaises(ValueError):
            self.run_import()
        self.assertEqual(self.api.creates, 1)

    def test_unknown_template_and_transformed_image_are_rejected(self):
        template = {'Card': {'Front': ''.join(f'maskArea.style.{name}=mask[{index}]*img{dimension}+"px";'
                     for name, index, dimension in [('left', 0, 'Width'), ('top', 1, 'Height'),
                                                   ('width', 2, 'Width'), ('height', 3, 'Height')])}}
        note = {'noteId': 123, 'modelName': 'Example', 'fields': {
            'Image': {'value': '<img src="image.png" style="transform:rotate(90deg)">'},
            'Masks': {'value': '[[[0.1,0.1,0.2,0.2]]]'}, 'Mode': {'value': 'free_guess'}}}
        with self.assertRaises(ValueError):
            source_data(note, template)
        note['fields']['Image']['value'] = '<img src="image.png">'
        with self.assertRaises(ValueError):
            source_data(note, {'Card': {'Front': 'unknown'}})
        self.assertEqual(source_data(note, template)['filename'], 'image.png')

    def test_grouped_masks_are_accepted_and_flattened(self):
        template = {'Card': {'Front': ''.join(f'maskArea.style.{name}=mask[{index}]*img{dimension}+"px";'
                     for name, index, dimension in [('left', 0, 'Width'), ('top', 1, 'Height'),
                                                   ('width', 2, 'Width'), ('height', 3, 'Height')])}}
        note = {'noteId': 123, 'modelName': 'Example', 'fields': {
            'Image': {'value': '<img src="image.png">'},
            'Masks': {'value': '[[[0.1,0.1,0.2,0.2],[0.4,0.4,0.2,0.2]],[[0.6,0.6,0.1,0.1]]]'},
            'Mode': {'value': 'free_guess'}}}
        source = source_data(note, template)
        self.assertEqual(len(source['groups']), 2)
        masks, counts = t.convert(source['groups'], (100, 80))
        self.assertEqual([m['index'] for m in masks], [1, 2, 3])
        self.assertEqual(counts['flattened_groups'], 1)
        note['fields']['Masks']['value'] = '[[],[[0.1,0.1,0.2,0.2]]]'
        with self.assertRaises(ValueError):
            source_data(note, template)


if __name__ == '__main__':
    unittest.main()
