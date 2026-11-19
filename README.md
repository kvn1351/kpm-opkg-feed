# Kindle KPM to OPKG Feed

Automated package feed bridge that compiles homebrew packages from **KindleTweaks** and **KindleModding (KMC)** into standard `.ipk` packages for `opkg` on jailbroken Kindle devices running [eink-opkg-beta](https://github.com/katadelos/eink-opkg-beta).

Published at: **https://kvn1351.github.io/kpm-opkg-feed/**

---

## Quick Setup (on your Kindle)

### 1. Add the feed source
Append the appropriate feed URL for your device architecture to `/mnt/us/.eink-sdk/opkg/opkg.conf`:

#### For `kindlehf` devices (Paperwhite 3/4/5, Oasis, Voyage, Basic 2/3):
```text
src/gz kpm https://kvn1351.github.io/kpm-opkg-feed/kindlehf
```

#### For `kindlepw2` devices (Paperwhite 2):
```text
src/gz kpm https://kvn1351.github.io/kpm-opkg-feed/kindlepw2
```

---

### 2. Update and Install

Update your package lists:
```sh
opkg update
```

Install any homebrew package natively via `opkg`:
```sh
# Kindle jailbreak manager & SSH recovery tools
opkg install jobman

# E-book reader
opkg install koreader

# Terminal emulator
opkg install kterm

# KUAL-replacement application launcher
opkg install kuala

# Audio player / Radio
opkg install kinamp

# Audiobook player
opkg install larkplayer

# Anki flashcard reviewer
opkg install ranki
```

To remove any package:
```sh
opkg remove <package_name>
```

---

## Included Upstream Repositories

- **KindleTweaks/Repo**: `kuala`, `gargoyle`, `kinamp`, `larkplayer`, `ranki`
- **KindleModding/repo (KMC)**: `jobman`, `koreader`, `kpm`, `kompanion`, `kterm`

Native release imports are supported through `native-packages.json`, currently
empty. Only add packages once checksum-verified assets are publicly available;
private or unpublished releases cannot be imported by the public feed.

---

## How It Works

1. The workflow on `main` rebuilds both upstream KPM feeds daily at 04:00 UTC,
   on pushes to `main`, and when `Publish OPKG feed` is triggered manually.
2. It fetches manifests and converts the newest `.kpkg` for each platform to
   `.ipk`, preserving the upstream install/uninstall hooks.
3. Any source, download, conversion or native-release error fails the build;
   incomplete feed indexes are not published.
4. Native releases configured in `native-packages.json` are checked against their
   published `SHA256SUMS` before inclusion.
5. The workflow saves generated files to `gh-pages`, then explicitly uploads and
   deploys a GitHub Pages artifact. Pages must use the **GitHub Actions** build
   source; a branch push using `GITHUB_TOKEN` alone does not trigger a Pages build.
   No cross-repository PAT is needed.
