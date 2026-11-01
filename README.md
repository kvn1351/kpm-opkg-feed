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

---

## How It Works

1. A GitHub Actions workflow runs daily at 04:00 UTC (and can be triggered manually).
2. It fetches upstream manifests (`manifest.v2.json` / `manifest.json`) from both repositories.
3. It resolves and downloads `.kpkg` packages (including transparent resolution of Git LFS objects).
4. It converts `.kpkg` archives into standard Debian-format `.ipk` packages, wiring existing `install.sh` / `uninstall.sh` lifecycle hooks into `postinst` and `prerm`.
5. It computes SHA-256 digests and compiles RFC 822 `Packages` and `Packages.gz` feeds.
6. Feeds are deployed automatically to GitHub Pages.
