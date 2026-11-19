import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import native


def packed(name,data):
    result=io.BytesIO()
    with tarfile.open(fileobj=result,mode='w:gz') as archive:
        info=tarfile.TarInfo(name); info.size=len(data)
        archive.addfile(info,io.BytesIO(data))
    return result.getvalue()


class NativeFeedTests(unittest.TestCase):
    def setUp(self):
        self.work=tempfile.TemporaryDirectory(prefix='fluidpdf-feed-')
        self.addCleanup(self.work.cleanup)
        self.root=Path(self.work.name)
        self.manifest=self.root/'native.json'
        self.manifest.write_text(json.dumps([dict(repo='kvn1351/FluidPDF',package='fluidpdf-alpha',architecture='kindlehf',allow_prerelease=True)]))
        self.vendor='Package: jobman\nVersion: 1.2.1\nArchitecture: kindlehf\nFilename: jobman.ipk\n'
        self.stanzas={'kindlehf':{'jobman_1.2.1':self.vendor,'fluidpdf-alpha_0.0.1-alpha.1':'Package: fluidpdf-alpha\nVersion: 0.0.1-alpha.1\nArchitecture: kindlehf\n'}}
        self.filename='fluidpdf-alpha_0.1.0-alpha.1_kindlehf.ipk'
        control=b'Package: fluidpdf-alpha\nVersion: 0.1.0-alpha.1\nArchitecture: kindlehf\nDescription: Native PDF alpha\n'
        self.ipk=packed('./control.tar.gz',packed('control',control))
        self.release=[dict(draft=False,prerelease=True,tag_name='v0.1.0-alpha.1',published_at='2026-11-01T00:00:00Z',assets=[dict(name=self.filename,browser_download_url='https://example.invalid/package'),dict(name='SHA256SUMS',browser_download_url='https://example.invalid/checksums')])]
        self.digest=hashlib.sha256(self.ipk).hexdigest()

    def fetch(self,url):
        if 'api.github.com' in url: return json.dumps(self.release).encode()
        if url.endswith('/checksums'): return (self.digest+'  '+self.filename+'\n').encode()
        if url.endswith('/package'): return self.ipk
        raise AssertionError('Unexpected fetch '+url)

    def test_native_refresh_preserves_upstream_and_replaces_only_owned_version(self):
        with patch.object(native,'fetch',self.fetch):
            native.add_releases(self.manifest,self.root/'site',self.stanzas)
        self.assertEqual(self.stanzas['kindlehf']['jobman_1.2.1'],self.vendor)
        self.assertNotIn('fluidpdf-alpha_0.0.1-alpha.1',self.stanzas['kindlehf'])
        actual=native.fields(self.stanzas['kindlehf']['fluidpdf-alpha_0.1.0-alpha.1'])
        self.assertEqual(actual['SHA256sum'],self.digest)
        self.assertEqual(actual['Filename'],self.filename)
        self.assertEqual((self.root/'site/kindlehf'/self.filename).read_bytes(),self.ipk)

    def test_checksum_mismatch_keeps_existing_feed_untouched(self):
        self.digest='0'*64
        before=json.dumps(self.stanzas,sort_keys=True)
        with patch.object(native,'fetch',self.fetch):
            with self.assertRaisesRegex(ValueError,'checksum mismatch'):
                native.add_releases(self.manifest,self.root/'site',self.stanzas)
        self.assertEqual(json.dumps(self.stanzas,sort_keys=True),before)
        self.assertFalse((self.root/'site').exists())

    def test_control_identity_mismatch_is_rejected(self):
        self.ipk=packed('./control.tar.gz',packed('control',b'Package: unrelated\nVersion: 0.1.0-alpha.1\nArchitecture: kindlehf\n'))
        self.digest=hashlib.sha256(self.ipk).hexdigest()
        with patch.object(native,'fetch',self.fetch):
            with self.assertRaisesRegex(ValueError,'identity mismatch'):
                native.add_releases(self.manifest,self.root/'site',self.stanzas)
        self.assertEqual(self.stanzas['kindlehf']['jobman_1.2.1'],self.vendor)


if __name__ == '__main__':
    unittest.main()
