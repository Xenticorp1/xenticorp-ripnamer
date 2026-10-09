# Xenticorp Ripnamer  (v3.1.0)

Renames MakeMKV TV rips (.mkv, plus .mp4/.m4v) to Jellyfin format using TMDb.

`title_t01.mkv` → `Show (Year) [tmdbid-123]/Season 01/Show (Year) - S01E10 - Episode Title.mkv`

## Download
Prebuilt apps are on the [Releases page](../../releases/latest):

| Platform | File |
|---|---|
| Windows | `Xenticorp-Ripnamer-v<version>.exe` on the [latest release](../../releases/latest) |
| Linux (x86_64, Ubuntu 22.04+) | `xenticorp-ripnamer-v<version>-linux-x86_64` on the [latest release](../../releases/latest) |
| Checksums | [`SHA256SUMS.txt`](../../releases/latest/download/SHA256SUMS.txt) |

**Bring your own free TMDb key.** Release builds have no key built in: on first launch open ⚙ Settings and paste yours. Free TMDb key: themoviedb.org → Settings → API. The v3 "API Key" or v4 "Read Access Token" both work.

- **Windows:** the exe is unsigned, so SmartScreen may warn the first time → "More info → Run anyway".
- **Linux:** `chmod +x xenticorp-ripnamer-*-linux-x86_64 && ./xenticorp-ripnamer-*-linux-x86_64`

**Verify the download** (optional): compare against `SHA256SUMS.txt`.
- Windows (PowerShell): `Get-FileHash .\Xenticorp-Ripnamer-*.exe -Algorithm SHA256`
- Linux: `sha256sum -c SHA256SUMS.txt --ignore-missing`

## Files
Keep these together in one folder:

| File | What it's for |
|---|---|
| `ripnamer.py` | Launcher (same for Windows and Linux) |
| `ripnamer_app/` | The app itself: **keep this folder next to `ripnamer.py`** |
| `tests/` | Automated tests (optional, not needed to build) |
| `build.bat` | Builds the Windows .exe |
| `build.sh` | Builds the Linux version |
| `xenticorp.ico` | Windows icon (optional — swap in your own, must be a real .ico or PNG) |
| `xenticorp.png` | Linux icon (optional) |
| `version_info.txt` | Company/product info shown in Properties → Details (optional, Windows) |

## Build (Windows)
1. Needs Python 3.10+. If missing: `winget install Python.Python.3.12` (then reopen the terminal).
2. Double-click `build.bat`.
3. It asks for a TMDb API key to bake into the exe — paste it, or press Enter to skip.
4. Output: `dist\Xenticorp Ripnamer.exe`

Free TMDb key: themoviedb.org → Settings → API. The v3 "API Key" or v4 "Read Access Token" both work.

The exe is fully standalone (no Python, FFmpeg or MKVToolNix needed — .mkv and .mp4 lengths are read straight from the files). Move it anywhere or copy it to other Windows PCs. After building, `build\`, `dist\` and `*.spec` can be deleted.

Heads-up: unsigned PyInstaller exes can trip SmartScreen/Defender the first time → "More info → Run anyway". Don't share an exe with a baked-in key publicly.

## Linux (Ubuntu)
The `.exe` is Windows-only. For Ubuntu:
- **Prebuilt:** `xenticorp-ripnamer-v<version>-linux-x86_64` from [Releases](../../releases/latest) (Ubuntu 22.04+, normal Intel/AMD PCs). After downloading:
  ```
  cd ~/Downloads
  chmod +x xenticorp-ripnamer-*-linux-x86_64 && ./xenticorp-ripnamer-*-linux-x86_64
  ```
  Linux paths are case-sensitive (`Downloads`, not `downloads`). If the browser renamed it (e.g. `xenticorp-ripnamer-v3.1.0-linux-x86_64(1)`), check with `ls | grep -i ripnamer`.
- **Build it yourself** (needed on Ubuntu older than 22.04, or on a Raspberry Pi / ARM — check with `uname -m`: `aarch64` = ARM): put `ripnamer.py`, `xenticorp.png` and `build.sh` together, then `chmod +x build.sh && ./build.sh`. It installs what it needs, asks about the API key, and can add an app-menu entry.
- **Or just run the script:** `sudo apt install python3-tk && pip install sv-ttk` then `python3 ripnamer.py`.

Settings on Linux live in `~/.config/RipNamer/config.json`. If Auto interface size looks small under GNOME scaling, pick a size in ⚙ Settings.

## Use
1. **Rip folder** → Browse to one disc's rips. Shows how many .mkv / .mp4 files it found.
2. **Show** → type name, Enter, highlight the right result (description shown below), click **Select this show**. It stays locked until you hit **Change**.
3. **Episodes** → pick **Numbering** (see below), then season/volume + first episode on this disc (disc 2 might start at E07). For a disc that crosses into the next season, pick **Continuous (across seasons)**. Optional: tick **Move into Jellyfin library** and pick your TV root; unticked = rename in place.
4. **Preview** → check the table → **Rename N files**.

Changing any setting after a preview disables Rename until you Preview again.

## Numbering schemes (DVD volumes, absolute, story arcs…)
After you select a show, the app checks TMDb for alternate orderings ("episode groups") and lists them under **Numbering**, e.g. `DVD: DVD Volumes`, `Absolute: …`, `Story arc: …`. Community-made, so coverage varies by show.

With a scheme picked:
- **Volume** → the part on this disc (Volume 3, Season 2 DVD, Arc 5…).
- **First episode (# in volume)** → position within that volume, usually 1.
- **Name files with**
  - **Standard SxxExx (recommended)** – files get each episode's normal aired number. Jellyfin matches them with zero setup, even when a volume spans two seasons.
  - **This scheme's numbering** – `S03E01…` = Volume 3, episode 1. Only use this if you also set the series' **Display order** in Jellyfin to the matching ordering, or episodes will mismatch.

## Discs that span seasons / specials
Some discs cross a season break and carry a special in between. Example, a Doctor Who (2005) disc:

| File | Episode |
|---|---|
| `title_t00.mkv` | S01E12 · Bad Wolf |
| `title_t01.mkv` | S01E13 · The Parting of the Ways |
| `title_t02.mkv` | S00E02 · The Christmas Invasion (special, aired 2005-12-25) |
| `title_t03.mkv` | S02E01 · New Earth |
| `title_t04.mkv` | S02E02 · Tooth and Claw |

Pick **Numbering → Continuous (across seasons)**, set **Start at** season 1, episode 12, and Preview. The app lines up the whole show in one run: every season in order, with each special placed right after the last episode that aired on or before it. **Include specials in air-date order** (on by default) controls that. Untick it for discs without specials.

- Specials are named `S00Exx` and, with **Move into Jellyfin library**, go into `Season 00`, which is where Jellyfin looks for them.
- Specials without an air date on TMDb have no place in the order, so they're left out. You can still assign one with **Set episode…** (below).
- If the start season/episode doesn't exist on TMDb, Preview says so instead of guessing.

### Set episode…
Works in every numbering mode. Right-click a row → **Set episode…** opens a searchable list of the episodes in the current mode (in Continuous mode: the whole show, including all specials), shown like `S01E13 · The Parting of the Ways · 45m`. Type to filter (`S02`, `christmas`…), then pick one.

That file gets the episode you picked, and the files after it keep counting from there. Handy when a disc skips an episode or has one out of order. Rows you set show **OK (set)** (or the usual ⚠ runtime warning). Right-click → **Clear set episode** undoes it. Changing the folder, the show or the numbering clears all of them.

## Renaming & moving
- **Same drive:** instant rename.
- **Different drive** (e.g. rips on one disk, Jellyfin library on another or a NAS): files are copied with a live progress bar showing file x/y, MB copied, speed and time left, plus a **Cancel** button.
  - Checks free space first.
  - Copies to `<name>.ripnamer-part`, verifies the size, then swaps it into place and deletes the original. A cancel or crash never leaves a half-copied episode.
  - Cancel stops after the current 8 MB block. The file in progress stays untouched at its original spot; finished files stay moved (and are in the undo log).
- Closing the window mid-move asks first, then cancels cleanly.

## Preview table
- **Green ✔** – ready.
- **Grey –** – skipped: shorter than the Detection setting (extras), or ~2× median length (play-all title).
- **Orange ⚠** – runtime doesn't match TMDb. Usually the order is off or an extra slipped in.
- **Red ✖** – more files than episodes in that season/volume, or the target file already exists. Won't be renamed.

Double-click a row (or right-click → Skip / Include) to include or skip it; episodes renumber automatically. Right-click → **Set episode…** pins a file to a specific episode.
Files are processed in natural filename order (t00, t01 … t10), which is MakeMKV's title order.

## Settings (⚙)
- **TMDb API key** – change it any time; a new key is saved once a search succeeds. "Reset to built-in key" returns to the baked-in one.
- **Theme** – dark / light.
- **Interface size** – Auto (follows Windows scaling) or 100–250%. Saved per device.
- **Detection** – "Skip files shorter than" N minutes (treated as extras). Default 10.
- **About** – version, TMDb credit and a link to themoviedb.org.

Theme and size changes offer to restart the app. Settings live in `%APPDATA%\RipNamer\config.json`, not next to the exe, so moving/replacing the exe keeps them.

## Undo
Each rename writes `ripnamer_undo_<timestamp>.json` in the rip folder, updated after every file (so it's valid even after a cancel or crash). **Undo a rename…** → pick it → files go back to their original names/places, with the same progress/cancel as renaming.

If some files can't be restored, the log is trimmed to just those, so you can fix the problem and run Undo on the same log again. A fully undone log is renamed `….undone.json`.

## Network
TMDb lookups retry automatically (up to 4 tries with growing waits) on timeouts, server errors and rate limiting. If it still fails you get a plain message: offline, bad API key, not found, and so on.

## Troubleshooting
- **"Can't reach TMDb. Check your internet connection"**: you're offline or DNS is down. Already retried 4 times.
- **"The ripnamer_app folder is missing"** (build): download the whole `ripnamer_app` folder and keep it next to `ripnamer.py`.
- **Linux: `No such file or directory`** – terminal isn't in the folder with the file. `cd ~/Downloads` (capital D), then `ls | grep -i ripnamer`. Run `chmod` and `./` as separate commands or joined with `&&`.
- **Linux: `cannot execute binary file`** – you're on ARM (`uname -m` says `aarch64`). Use `build.sh`.
- **`'py' is not recognized`** – Python isn't installed (see Build step 1).
- **Build failed** – screenshot the error above "Build failed".
- **Wrong icon in File Explorer only** – Windows icon cache. Rename the exe, or clear the cache:
  `taskkill /f /im explorer.exe` → `del /a /q "%localappdata%\IconCache.db"` → `del /a /f /q "%localappdata%\Microsoft\Windows\Explorer\iconcache*"` → `start explorer.exe`
- **Everything tiny/huge** – ⚙ → Interface size.
- **Left panel cut off** – it scrolls (mouse wheel) when the window is short.

## Tests
From the RipNamer folder: `python -m unittest discover -s tests -v` (Windows: `py -m …`). Covers MKV/MP4 length reading, planning, continuous timelines with specials, Set episode, TMDb retries, cross-drive copy, cancel, and undo. No internet or real videos needed.

## Known limits
- Alternate orderings only exist if someone added them on TMDb. If yours is missing, use Standard seasons + First episode, or Continuous for discs that cross seasons.
- One file = one episode (no multi-episode files).
- Video types: .mkv, .mp4, .m4v. Each file keeps its own extension when renamed.
- Only the icon uses `xenticorp.ico`; the header logo is drawn in code.

## Releasing
1. Set the new version in `ripnamer_app/__init__.py` (`VERSION = "X.Y.Z"`) and `version_info.txt`, and commit.
2. Push a matching tag and GitHub Actions does the rest:
   ```
   git tag vX.Y.Z && git push --tags
   ```
`.github/workflows/release.yml` checks that the tag matches `VERSION`, runs the tests, builds the Windows exe and Linux binary (no key baked in), and attaches `Xenticorp-Ripnamer-vX.Y.Z.exe`, `xenticorp-ripnamer-vX.Y.Z-linux-x86_64` and `SHA256SUMS.txt` to a GitHub Release named after the tag. Xenticorp.net finds the newest files through the GitHub API, so keep the `Xenticorp-Ripnamer-*.exe` / `xenticorp-ripnamer-*-linux-x86_64` pattern. `SHA256SUMS.txt` keeps its fixed name.

Never commit `ripnamer_key.py` (it's in `.gitignore`).

## Credits
This product uses the TMDB API but is not endorsed or certified by TMDB. ([themoviedb.org](https://www.themoviedb.org/))

## License
MIT, see [LICENSE](LICENSE).
