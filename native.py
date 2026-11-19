"""Import checksum-verified native IPKs from public GitHub Releases."""
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile
import urllib.request


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent':'kpm-opkg-feed/1.0'})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def fields(text):
    result = {}
    for line in text.splitlines():
        if not line or line[0].isspace():
            continue
        key, sep, value = line.partition(':')
        if not sep or key in result:
            raise ValueError('Invalid or duplicate package control field')
        result[key] = value.strip()
    return result


def existing_stanzas(out):
    stanzas = {}
    for index in sorted(Path(out).glob('*/Packages')):
        packages = {}
        for stanza in index.read_text().strip().split('\n\n'):
            if not stanza.strip():
                continue
            data = fields(stanza)
            packages[data['Package']+'_'+data['Version']] = stanza.strip()+'\n'
        stanzas[index.parent.name] = packages
    if not stanzas:
        raise ValueError('Native-only refresh requires existing feed indexes')
    return stanzas


def read_control(ipk):
    with tarfile.open(fileobj=io.BytesIO(ipk),mode='r:gz') as outer:
        controls = [item for item in outer.getmembers() if item.name.lstrip('./') == 'control.tar.gz' and item.isfile()]
        if len(controls) != 1:
            raise ValueError('IPK has no unique control archive')
        packed = outer.extractfile(controls[0]).read()
    with tarfile.open(fileobj=io.BytesIO(packed),mode='r:gz') as archive:
        members = [item for item in archive.getmembers() if item.name.lstrip('./') == 'control' and item.isfile()]
        if len(members) != 1:
            raise ValueError('IPK has no unique package control')
        return archive.extractfile(members[0]).read().decode('utf-8').strip()


def add_releases(manifest_path, out, stanzas):
    manifest = json.loads(Path(manifest_path).read_text())
    for entry in manifest:
        repo, package, arch = entry['repo'], entry['package'], entry['architecture']
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):
            raise ValueError('Invalid native repository')
        if not re.fullmatch(r'[a-z0-9][a-z0-9+.-]*',package) or not re.fullmatch(r'[a-z0-9]+',arch):
            raise ValueError('Invalid native package identity')
        releases = json.loads(fetch('https://api.github.com/repos/'+repo+'/releases?per_page=20'))
        candidates = []
        for release in releases:
            if release['draft'] or (release['prerelease'] and not entry.get('allow_prerelease',False)):
                continue
            version = release['tag_name'].removeprefix('v')
            if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+-alpha\.[0-9]+',version):
                continue
            filename = package+'_'+version+'_'+arch+'.ipk'
            assets = {asset['name']:asset for asset in release['assets']}
            if filename in assets and 'SHA256SUMS' in assets:
                candidates.append((release['published_at'],filename,assets))
        if not candidates:
            raise ValueError('No published native release with IPK and checksums: '+repo)
        _, filename, assets = max(candidates,key=lambda value:value[0])
        checksums = fetch(assets['SHA256SUMS']['browser_download_url']).decode()
        matching = [line.split()[0] for line in checksums.splitlines() if len(line.split()) == 2 and line.split()[1] == filename]
        if len(matching) != 1 or not re.fullmatch('[0-9a-f]{64}',matching[0]):
            raise ValueError('No unique checksum for '+filename)
        data = fetch(assets[filename]['browser_download_url'])
        digest = hashlib.sha256(data).hexdigest()
        if digest != matching[0]:
            raise ValueError('Native artifact checksum mismatch: '+filename)
        control = read_control(data)
        info = fields(control)
        if info.get('Package') != package or info.get('Architecture') != arch or filename != package+'_'+info.get('Version','')+'_'+arch+'.ipk':
            raise ValueError('Native control identity mismatch')
        for reserved in ('Filename','Size','SHA256sum'):
            if reserved in info:
                raise ValueError('Unexpected index-only control field: '+reserved)
        folder = Path(out)/arch
        folder.mkdir(parents=True,exist_ok=True)
        stage = folder/(filename+'.tmp')
        stage.write_bytes(data)
        stage.replace(folder/filename)
        # Replace only this owned native package; preserve all upstream entries.
        packages = stanzas.setdefault(arch,{})
        for key in list(packages):
            if fields(packages[key]).get('Package') == package:
                del packages[key]
        packages[package+'_'+info['Version']] = control+'\nFilename: '+filename+'\nSize: '+str(len(data))+'\nSHA256sum: '+digest+'\n'
        print('Native release: '+repo+' '+info['Version'])
