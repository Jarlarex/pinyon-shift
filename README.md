# Pinyon Shift: EU + DLC fork

<p align="center">
  <img src=".github/pinyon-shift-banner.png" alt="Pinyon Shift logo" width="800">
</p>

<p align="center">
  <b><i>Forza Horizon</i> (Xbox 360) recompiled to run natively on Windows: the European disc, its title update and your own DLC.</b><br>
  Built on your own PC from your own disc. No game files are included here.
</p>

This is a fork of [Pinyon Shift](https://github.com/arcanite24/pinyon-shift) by
arcanite24. Pinyon Shift translates the game's PowerPC code ahead of time into
C++ with [ShiftGlue](https://github.com/arcanite24/shiftglue-sdk) (a fork of
ReXGlue) and runs it with a native Vulkan renderer written for *Forza Horizon*.
Upstream supports the USA disc. This fork adds:

- the **European disc** (media `4000D145`, version 0.0.0.12), built with its
  title update;
- the **title update (v4)**, downloaded, verified and installed automatically;
- **all of your DLC installed and enabled from the start**, from one folder;
- fixes found while getting there (GPU choice on hybrid laptops, setups without
  a USA build, the achievements screen, shader preparation).

Every change is a small commit on top of upstream `dev`; see
[What this fork changes](#what-this-fork-changes).

## What works

Tested on Windows 11 with an NVIDIA GeForce RTX 5060 Laptop GPU (8 GB) beside
an AMD Radeon 860M.

| Area | Status |
| --- | --- |
| EU disc recognized by exact hash, extracted beside a USA disc | Working |
| Title update v4: download, page-by-page verification against the EU disc, install | Working (the EU disc is the update's own base; its patched code is byte-identical to the USA v4 code) |
| EU + v4 build from a fresh checkout (no USA files needed) | Working: about 18 minutes the first time, 4–8 minutes after a change |
| Title screen, free roam, races, save and reload | Working |
| English and German (text and voice); other voices on the disc: French, Spanish, Italian, Dutch | Working; choose in the launcher's graphics panel or the in-game settings |
| Discrete GPU on hybrid laptops | Working (fork of ShiftGlue, see below) |
| Video memory | Peak 1.3 GB of an 8 GB card in a long session |
| DLC installed and enabled automatically | 22 packages, see [the DLC matrix](docs/DLC_EU_MATRIX.md) |
| DLC cars in the Autoshow, bought, driven, kept after a restart | Checked by playing |
| Rally Expansion (native, from the title update) | Installed and loading; stages still to be played through |
| 1000 Club | Offline mode on by default (its online goals are confirmed locally) |
| Fast Travel Anywhere | Granted automatically on the title update (it was a token-store unlock) |
| EU disc **without** the title update | Not buildable yet; setup stops and asks for the update |
| Android package | USA base build only; not for this EU build |

A DLC car appears only when its package carries a licence for it, exactly as
on a console. For example, the Rally Expansion's 2003 Ford Focus SVT needs the
Season Pass licence inside the Rally package, and a package without a licence
shows none of its cars. Licences are never added or changed.

## Requirements

- Your own dump of the European (or USA) retail disc, as an ISO.
- Optionally your own DLC packages (raw packages or ZIPs holding them).
- Windows 10 or 11, x64; a GPU with Vulkan 1.3; about 40 GB of free disk space.
- An internet connection for the build tools and the title update.

Setup installs the Visual Studio C++ Build Tools (with Windows' permission
prompt) and pinned, checksummed portable tools (CMake, LLVM, Python, MinGit,
extract-xiso) into `.local/toolchain`; see
[Third-party notices](THIRD_PARTY_NOTICES.md).

## Set up and play

Keep your dumps in a `gamefiles` folder **beside** the repository, never inside
it:

```text
workspace\
  pinyon-shift\        this repository
  gamefiles\           your ISO, DLC packages and ZIPs (any layout)
```

Then, from PowerShell in `pinyon-shift`:

```powershell
.\tools\setup-preview.ps1 -IsoPath ..\gamefiles\your-disc.iso
```

Setup verifies the disc by SHA-256, provisions the tools, extracts the disc
into `.local/game/eur-base`, downloads and verifies the title update, builds the
game, prepares Vulkan shaders and installs every verified DLC package it finds
in `..\gamefiles` (or the folder given with `-DlcPath`). Anything it cannot use
(a disc image, an unknown or damaged package, a title update file) is listed
with its reason and does not stop the rest.

To play, start the launcher (`launcher\PinyonShift.Launcher\bin\Release\net8.0-windows\win-x64\PinyonShiftLauncher.exe`
after `dotnet build -c Release` of `launcher/PinyonShift.Launcher`), or run:

```powershell
.\tools\launch-preview.ps1 -TitleUpdateV4 -StateRoot .local\preview
```

Your save, settings and installed DLC live in `.local/preview`.

### Controls

A controller works as on the console. With the keyboard:

| Key | Controller | Key | Controller |
| --- | --- | --- | --- |
| E or O | Right trigger (accelerate) | Space, left mouse, `;` | A |
| Q or I | Left trigger (brake) | Backspace or `'` | B |
| A / D | Steer | L | X |
| W / S | Left stick up / down | P | Y |
| Arrow keys | Right stick (camera) | 1 / 3 | Left / right shoulder |
| Shift + arrows | D-pad | Enter | Start |
| Tab or Z | Back | F / K | Stick presses |

F6 opens Pinyon Shift's settings (graphics, audio, controls, language), F10 the
trainer, and the map's Y fast travels anywhere on a road. Bindings are the
`keybind_*` lines in `.local/preview/config/pinyon_shift.toml`.

### Portable install

The packaged launcher can keep everything in one folder: put an empty
`portable.txt` beside `PinyonShiftLauncher.exe`, or start it with `--portable`.
Its data then lives in a `data` folder beside it, and the setup screen shows
**Portable:** followed by that folder. Details are in
[Troubleshooting](docs/TROUBLESHOOTING.md).

## DLC

`tools/manage-fh1-dlc.py install-folder --state-root <state> --source <folder>`
installs every package in a folder through the verified importer and enables
it; setup runs it for you. Packages are accepted only when their whole-package
SHA-256 and extracted payload match [the catalog](config/supported-dlc.json),
so damaged or truncated copies are rejected with a reason. The catalog covers
the monthly car packs (October to April), the 1000 Club and Rally expansions,
both VIP packages, the Season Pass Miura, Pre-Order, LCE Day1, Honda Challenge,
the single-car packs and, in this fork, the 2013 Ford Mustang Boss 302 Pizza Hut
Edition. Per-package results are in [the DLC matrix](docs/DLC_EU_MATRIX.md).

## Title update

The v4 update (15,728,640 bytes, SHA-256 `CC49029A…9112`) is downloaded from the
sources in [`config/title-update-sources.json`](config/title-update-sources.json)
into `<state>/downloads/title-update`, used only at its pinned size and hash,
then verified page by page against your disc before it is installed. Offline,
or on any failure, setup reports it and continues. The launcher's DLC panel can
also download it, or import your own copy.

## What this fork changes

| Area | Change |
| --- | --- |
| Disc identity | EU entry and per-file catalog in `supported-dumps.json`; region, media ID, version and voice languages reported by both verifiers; each disc extracted into its own `game_root` |
| Setup | `build_support` per disc (`supported`, `v4`, `pending`); EU builds v4; exit code 3 for a recognized disc that cannot be built yet; `-StateRoot` and `-DlcPath` |
| Title update | EU as a verified base; automatic download (`tools/fetch-title-update.py`); the verifier picks the installed disc; `tools/build-title-update-tools.ps1` builds the verifier's extractor before the game exists |
| Builds | The code generator and v4 generated code are built on a fresh checkout (`Invoke-PinyonCodeGeneratorBuild`); launch and v4 builds use the last setup's game root |
| Graphics | ShiftGlue fork prefers a discrete GPU for Vulkan; shader preparation mounts the title update |
| DLC | `install-folder`; catalog entry for the Pizza Hut Mustang; offline 1000 Club by default |
| Launcher | Detects and plays EU v4 setups; title-update download with a plan shown first; game language choice; verified-but-not-buildable state |
| Host UI | Releases of keys pressed before a menu opened reach the game (fixes the achievements screen reopening forever); menu notes are not drawn |
| Repository | Title-update packages and downloads are refused by the boundary check |

Design notes: [architecture](docs/ARCHITECTURE.md), [EU backlog](docs/EU_BACKLOG.md),
[DLC matrix](docs/DLC_EU_MATRIX.md), [building](docs/BUILDING.md),
[upstream DLC backlog](docs/DLC_BACKLOG.md),
[title update v4 backlog](docs/TITLE_UPDATE_V4_BACKLOG.md).

### ShiftGlue fork

The `thirdparty/shiftglue-sdk` submodule points at
[Jarlarex/shiftglue-sdk](https://github.com/Jarlarex/shiftglue-sdk), branch
`feat/prefer-discrete-gpu`: upstream ShiftGlue plus one change that makes Vulkan
auto-selection try a discrete GPU before an integrated one. `vulkan_device` in
the config still forces a specific device.

## Known issues

- Rally stages, co-driver calls and the Rally hub have not been played through
  on the EU build yet.
- An early session showed hitches of up to 1.4 s while driving fast, from shaders
  being translated during play before shader preparation worked; recheck after
  shader preparation.
- The archive extractor crashes on a truncated package instead of reporting it.
- The EU disc cannot be built without the title update.
- See upstream's [BUGS.md](BUGS.md) for renderer issues shared with the USA build.

## Project boundaries

This repository contains the launcher, build tools, host code and configuration.
It does **not** contain the game, its assets, its title update, DLC, generated
translations or a built executable, and its checks refuse them. Game files come
only from your own copies.

Only independently authored project files are licensed under the
[BSD 3-Clause License](LICENSE). Microsoft, Xbox, Turn 10 Studios, Playground
Games, *Forza Horizon*, and third-party dependencies remain the property of
their respective owners. This project is not affiliated with or endorsed by
them. See [Legal and distribution](docs/LEGAL.md) and
[Third-party notices](THIRD_PARTY_NOTICES.md).

## Credits

Pinyon Shift, its native renderer, DLC importer, title-update support and almost
everything this fork builds on are the work of
[arcanite24 and the Pinyon Shift contributors](https://github.com/arcanite24/pinyon-shift).
ShiftGlue is arcanite24's fork of [ReXGlue](https://github.com/rexglue/rexglue-sdk).
If you want to support that work, see
[upstream's support options](https://github.com/arcanite24/pinyon-shift#supporting-the-project).
