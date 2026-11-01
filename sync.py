#!/usr/bin/env python3
"""
kpm-feed-sync.py: Programmatic fetcher and converter that transforms KPM
(Kindle Package Manager) repositories into standard OPKG package feeds.
"""

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import sys
import tarfile
import urllib.parse
import urllib.request

KPM_COMPAT_VERSION = (0, 2, 4)
USER_AGENT = "kpm-feed-sync/1.0"


def fetch_url(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def download_kpkg(base_url, artifact_rel_url, cache_dir):
    """
    Download a .kpkg artifact. If the returned content is a Git LFS pointer,
    transparently resolve it from GitHub's media server.
    """
    os.makedirs(cache_dir, exist_ok=True)
    filename = os.path.basename(artifact_rel_url)
    cache_path = os.path.join(cache_dir, filename)

    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 1024:
        return cache_path

    full_url = urllib.parse.urljoin(base_url.rstrip("/") + "/", artifact_rel_url.lstrip("/"))
    print(f"    Fetching {full_url} ...")
    content = fetch_url(full_url)

    if content.startswith(b"version https://git-lfs.github.com/spec/v1"):
        print("    [!] Detected Git LFS pointer. Resolving via GitHub media endpoint...")
        parsed = urllib.parse.urlparse(full_url)
        path_parts = parsed.path.strip("/").split("/")

        if "raw.githubusercontent.com" in parsed.netloc:
            owner, repo, branch = path_parts[0], path_parts[1], path_parts[2]
            rel = "/".join(path_parts[3:])
            media_url = f"https://media.githubusercontent.com/media/{owner}/{repo}/{branch}/{rel}"
        elif "github.com" in parsed.netloc:
            owner, repo = path_parts[0], path_parts[1]
            rel = "/".join(path_parts[4:]) if len(path_parts) > 4 else artifact_rel_url
            media_url = f"https://media.githubusercontent.com/media/{owner}/{repo}/main/{rel}"
        else:
            raise ValueError(f"Git LFS pointer encountered on non-GitHub host: {full_url}")

        print(f"    Fetching LFS object from {media_url} ...")
        content = fetch_url(media_url, timeout=180)

    with open(cache_path, "wb") as f:
        f.write(content)

    return cache_path


def kpkg_to_ipk(kpkg_path, pkg_id, pkg_name, author, description, version_str, platform, out_ipk_path):
    """
    Convert a single .kpkg (tar.gz or tar.xz) into a standard .ipk package.
    """
    with tarfile.open(kpkg_path, "r:*") as ktar:
        data_buf = io.BytesIO()
        with tarfile.open(fileobj=data_buf, mode="w:gz") as dtar:
            for member in ktar.getmembers():
                f = ktar.extractfile(member) if member.isreg() else None
                new_name = os.path.normpath(os.path.join("./mnt/us/kmc/kpm/packages", pkg_id, member.name))
                m_copy = tarfile.TarInfo(name=new_name)
                m_copy.size = member.size
                m_copy.mode = member.mode
                m_copy.mtime = member.mtime
                m_copy.type = member.type
                m_copy.linkname = member.linkname
                m_copy.uname = "root"
                m_copy.gname = "root"
                m_copy.uid = 0
                m_copy.gid = 0
                if f:
                    dtar.addfile(m_copy, f)
                else:
                    dtar.addfile(m_copy)
        data_bytes = data_buf.getvalue()

    desc_clean = description.replace("\r", "").strip()
    synopsis = desc_clean.split("\n")[0]

    control_text = (
        f"Package: {pkg_id}\n"
        f"Version: {version_str}\n"
        f"Architecture: {platform}\n"
        f"Maintainer: {author}\n"
        f"Section: homebrew\n"
        f"Priority: optional\n"
        f"Installed-Size: {len(data_bytes)}\n"
        f"Description: {pkg_name} - {synopsis}\n"
    )

    postinst_text = f"""#!/bin/sh
set -e
umask 022
[ -z "${{IPKG_INSTROOT:-}}" ] || exit 0
PKG_DIR="/mnt/us/kmc/kpm/packages/{pkg_id}"
if [ -d "$PKG_DIR" ] && [ -f "$PKG_DIR/install.sh" ]; then
    cd "$PKG_DIR"
    KPM_VERSION_MAJOR={KPM_COMPAT_VERSION[0]} \\
    KPM_VERSION_MINOR={KPM_COMPAT_VERSION[1]} \\
    KPM_VERSION_PATCH={KPM_COMPAT_VERSION[2]} \\
    KPM_PLATFORM="{platform}" \\
    /bin/sh install.sh
fi
exit 0
"""

    prerm_text = f"""#!/bin/sh
[ -z "${{IPKG_INSTROOT:-}}" ] || exit 0
PKG_DIR="/mnt/us/kmc/kpm/packages/{pkg_id}"
if [ -d "$PKG_DIR" ] && [ -f "$PKG_DIR/uninstall.sh" ]; then
    cd "$PKG_DIR"
    KPM_PLATFORM="{platform}" \\
    /bin/sh uninstall.sh || true
fi
exit 0
"""

    postrm_text = f"""#!/bin/sh
[ -z "${{IPKG_INSTROOT:-}}" ] || exit 0
rm -rf "/mnt/us/kmc/kpm/packages/{pkg_id}"
exit 0
"""

    control_buf = io.BytesIO()
    with tarfile.open(fileobj=control_buf, mode="w:gz") as ctar:
        for name, text, mode in [
            ("control", control_text, 0o644),
            ("postinst", postinst_text, 0o755),
            ("prerm", prerm_text, 0o755),
            ("postrm", postrm_text, 0o755),
        ]:
            b = text.encode("utf-8")
            ti = tarfile.TarInfo(name=name)
            ti.size = len(b)
            ti.mode = mode
            ti.uname = "root"
            ti.gname = "root"
            ti.uid = 0
            ti.gid = 0
            ctar.addfile(ti, io.BytesIO(b))
    control_bytes = control_buf.getvalue()

    os.makedirs(os.path.dirname(out_ipk_path), exist_ok=True)
    with tarfile.open(out_ipk_path, "w:gz") as ipk_tar:
        deb_bin = b"2.0\n"
        for name, data in [
            ("./debian-binary", deb_bin),
            ("./control.tar.gz", control_bytes),
            ("./data.tar.gz", data_bytes),
        ]:
            ti = tarfile.TarInfo(name=name)
            ti.size = len(data)
            ti.mode = 0o644
            ipk_tar.addfile(ti, io.BytesIO(data))

    return len(data_bytes)


def sync_repository(repo_source, out_dir, cache_dir):
    print(f"\n[*] Processing source: {repo_source}")

    if os.path.isdir(repo_source):
        base_url = repo_source
        manifest_path = os.path.join(repo_source, "manifest.v2.json")
        if not os.path.exists(manifest_path):
            manifest_path = os.path.join(repo_source, "manifest.json")
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        is_local = True
    else:
        is_local = False
        if re.match(r"^[\w-]+/[\w-]+$", repo_source):
            base_url = f"https://raw.githubusercontent.com/{repo_source}/main/"
        else:
            base_url = repo_source.rsplit("/", 1)[0] + "/"

        manifest_url = urllib.parse.urljoin(base_url, "manifest.v2.json")
        try:
            print(f"  Attempting manifest: {manifest_url}")
            manifest = json.loads(fetch_url(manifest_url).decode("utf-8"))
        except Exception:
            manifest_url = urllib.parse.urljoin(base_url, "manifest.json")
            print(f"  Falling back to: {manifest_url}")
            manifest = json.loads(fetch_url(manifest_url).decode("utf-8"))

    repo_id = manifest.get("id", "kpm-repo")
    print(f"  Repo name: {manifest.get('name')} (ID: {repo_id})")

    feed_stanzas = {}
    packages = manifest.get("packages", {})

    for pkg_id, pkg_info in packages.items():
        pkg_name = pkg_info.get("name", pkg_id)
        author = pkg_info.get("author", "Unknown")
        description = pkg_info.get("description", pkg_name)

        artifacts = pkg_info.get("artifacts", [])
        for art in artifacts:
            rel_url = art.get("url")
            v = art.get("version", [1, 0, 0])
            version_str = ".".join(map(str, v))
            platforms = art.get("supported_platforms", ["kindlehf"])

            print(f"  --> Package {pkg_id} v{version_str} for {platforms}")

            if is_local:
                kpkg_path = os.path.join(base_url, rel_url)
            else:
                try:
                    kpkg_path = download_kpkg(base_url, rel_url, cache_dir)
                except Exception as e:
                    print(f"      [!] Failed to download {rel_url}: {e}", file=sys.stderr)
                    continue

            for platform in platforms:
                try:
                    ipk_filename = f"{pkg_id}_{version_str}_{platform}.ipk"
                    arch_feed_dir = os.path.join(out_dir, platform)
                    ipk_path = os.path.join(arch_feed_dir, ipk_filename)

                    inst_size = kpkg_to_ipk(
                        kpkg_path=kpkg_path,
                        pkg_id=pkg_id,
                        pkg_name=pkg_name,
                        author=author,
                        description=description,
                        version_str=version_str,
                        platform=platform,
                        out_ipk_path=ipk_path,
                    )

                    file_size = os.path.getsize(ipk_path)
                    with open(ipk_path, "rb") as f:
                        sha256 = hashlib.sha256(f.read()).hexdigest()

                    synopsis = description.replace("\r", "").strip().split("\n")[0]
                    stanza = (
                        f"Package: {pkg_id}\n"
                        f"Version: {version_str}\n"
                        f"Architecture: {platform}\n"
                        f"Maintainer: {author}\n"
                        f"Section: homebrew\n"
                        f"Priority: optional\n"
                        f"Installed-Size: {inst_size}\n"
                        f"Filename: {ipk_filename}\n"
                        f"Size: {file_size}\n"
                        f"SHA256sum: {sha256}\n"
                        f"Description: {pkg_name} - {synopsis}\n"
                    )

                    if platform not in feed_stanzas:
                        feed_stanzas[platform] = {}
                    feed_stanzas[platform][f"{pkg_id}_{version_str}"] = stanza
                except Exception as ex:
                    print(f"      [!] Error converting {pkg_id} for {platform}: {ex}", file=sys.stderr)

    return feed_stanzas


def generate_index_html(out_dir, all_stanzas):
    """
    Generate a landing page explaining the feed and showing setup instructions.
    """
    platforms_html = ""
    for platform, pkg_dict in all_stanzas.items():
        packages_list = "".join(f"<li><code>{k}</code></li>" for k in sorted(pkg_dict.keys()))
        platforms_html += f"""
        <div class="card">
            <h2>Architecture: <code>{platform}</code> ({len(pkg_dict)} packages)</h2>
            <p>Feed URL: <code>{platform}/Packages.gz</code></p>
            <p><strong>Config snippet for <code>/mnt/us/.eink-sdk/opkg/opkg.conf</code>:</strong></p>
            <pre><code>src/gz kpm https://kvn1351.github.io/kpm-opkg-feed/{platform}</code></pre>
            <details>
                <summary>View {len(pkg_dict)} Available Packages</summary>
                <ul>{packages_list}</ul>
            </details>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Kindle KPM to OPKG Feed</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; line-height: 1.6; max-width: 800px; margin: 40px auto; padding: 0 20px; color: #222; }}
        h1 {{ border-bottom: 2px solid #eaeaea; padding-bottom: 10px; }}
        pre {{ background: #f6f8fa; padding: 12px; border-radius: 6px; overflow-x: auto; }}
        code {{ font-family: ui-monospace, SFMono-Regular, monospace; background: #f0f2f5; padding: 2px 4px; border-radius: 4px; }}
        pre code {{ background: none; padding: 0; }}
        .card {{ background: #fff; border: 1px solid #e1e4e8; border-radius: 6px; padding: 16px; margin: 20px 0; }}
        details {{ margin-top: 10px; cursor: pointer; }}
    </style>
</head>
<body>
    <h1>Kindle KPM Homebrew Feed for OPKG</h1>
    <p>Automated bridge compiling Kindle Package Manager (KPM) packages from <strong>KindleTweaks</strong> and <strong>KindleModding (KMC)</strong> into standard OPKG <code>.ipk</code> packages.</p>

    <h3>Quick Setup</h3>
    <p>Add the appropriate line to your <code>/mnt/us/.eink-sdk/opkg/opkg.conf</code>, then update and install:</p>
    <pre><code>opkg update
opkg install jobman
opkg install koreader</code></pre>

    {platforms_html}

    <p style="color: #666; font-size: 0.9em; margin-top: 40px;">Updated automatically via GitHub Actions.</p>
</body>
</html>
"""
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)


def main():
    parser = argparse.ArgumentParser(description="Fetch and convert KPM repositories into OPKG feeds")
    parser.add_argument(
        "sources",
        nargs="+",
        help="Local directories, GitHub slugs (e.g. KindleTweaks/Repo), or remote manifest URLs",
    )
    parser.add_argument("--out", "-o", default="./opkg-feed", help="Output feed directory")
    parser.add_argument("--cache", "-c", default="./.kpm-cache", help="Artifact cache directory")
    args = parser.parse_args()

    out_dir = os.path.abspath(args.out)
    cache_dir = os.path.abspath(args.cache)

    all_stanzas = {}

    for src in args.sources:
        try:
            stanzas = sync_repository(src, out_dir, cache_dir)
            for plat, pkgs in stanzas.items():
                if plat not in all_stanzas:
                    all_stanzas[plat] = {}
                all_stanzas[plat].update(pkgs)
        except Exception as e:
            print(f"[!] Error syncing {src}: {e}", file=sys.stderr)

    print("\n[+] Writing feed indexes...")
    for platform, pkg_dict in all_stanzas.items():
        arch_feed_dir = os.path.join(out_dir, platform)
        os.makedirs(arch_feed_dir, exist_ok=True)

        packages_txt = os.path.join(arch_feed_dir, "Packages")
        packages_gz = os.path.join(arch_feed_dir, "Packages.gz")

        body = "\n".join(pkg_dict.values()) + "\n"
        with open(packages_txt, "w", encoding="utf-8") as f:
            f.write(body)
        with gzip.open(packages_gz, "wb") as f:
            f.write(body.encode("utf-8"))

        print(f"  --> {platform}: {len(pkg_dict)} packages indexed in Packages and Packages.gz")

    generate_index_html(out_dir, all_stanzas)
    print("\n[✓] Done. Feed ready at:", out_dir)


if __name__ == "__main__":
    main()
