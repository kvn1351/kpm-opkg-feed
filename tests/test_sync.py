import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest


class CompleteFeedTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory(prefix='kpm-feed-')
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)
        self.source = self.root / 'upstream'
        self.source.mkdir()
        self.out = self.root / 'site'
        (self.out / 'kindlehf').mkdir(parents=True)
        self.index = self.out / 'kindlehf' / 'Packages'
        self.previous = 'Package: previous\nVersion: 1.0.0\nArchitecture: kindlehf\n'
        self.index.write_text(self.previous)

    def run_sync(self):
        return subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1] / 'sync.py'),
             str(self.source), '--out', str(self.out)],
            capture_output=True, text=True,
        )

    def test_unavailable_source_fails_without_replacing_published_index(self):
        result = self.run_sync()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.index.read_text(), self.previous)
        self.assertFalse((self.out / 'index.html').exists())

    def test_broken_package_does_not_publish_partial_feed(self):
        with tarfile.open(self.source / 'good.kpkg', 'w:gz') as archive:
            payload = b'#!/bin/sh\nexit 0\n'
            member = tarfile.TarInfo('install.sh')
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
        (self.source / 'broken.kpkg').write_bytes(b'not a package archive')
        packages = {
            name: {'artifacts': [{'version': [1, 0, 0],
                                  'url': name + '.kpkg',
                                  'supported_platforms': ['kindlehf']}]}
            for name in ('good', 'broken')
        }
        (self.source / 'manifest.v2.json').write_text(json.dumps({'packages': packages}))
        result = self.run_sync()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.index.read_text(), self.previous)
        self.assertFalse((self.out / 'index.html').exists())


if __name__ == '__main__':
    unittest.main()
