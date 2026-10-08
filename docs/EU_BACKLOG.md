# EU disc backlog: where the USA disc is assumed

Inventory at `dev` `589f7ea` of every place that assumes the USA retail disc
(MS-2505, media `2DC7007B`, version 0.0.0.10, `default.xex` SHA-256
`DB40DF60…`). Each row says what an EU build needs.

Read from the user's EU dump (execution-info header of each module): title ID
**`4D5309C9`** (same as USA), media **`4000D145`**, version **0.0.0.12**,
with `default.xex` and both facades the same size as the USA modules. The
v4 title update in `supported-title-updates.json` was built for exactly this
media and version, so EU + v4 is the update's native pairing. Section 6 below
therefore holds unchanged for EU.

## 1. Disc identity and verification

**Done (`eu-identity`, 2026-10-08).** The EU dump is in the table with
`build_support: pending` and its own `game_root`. Both verifiers report the
region, setup extracts the disc beside the USA one and stops with exit code 3,
and the launcher shows that state as verified rather than failed. The Rally
adapter and artifact tools pick dumps by capability instead of by id or position.

| Location | Assumption | EU work |
| --- | --- | --- |
| `config/supported-dumps.json` | Single dump `forza-horizon-usa-ms-2505-retail-base`: ISO size/hash, extraction file count/size, per-executable hashes, language list | Add an EU entry read from the user's dump |
| `config/supported-extracted-ms-2505.json` | Extracted-folder manifest for MS-2505 only | Per-dump extracted manifest |
| `tools/verify-game.ps1` | Iterates dumps generically (OK), but the result has no region field | Report region; the launcher shows it |
| `tools/prepare-fh1-rally.py:317` | Looks up dump id `forza-horizon-usa-ms-2505-retail-base` by name | Select the dump by the verified region |
| `tools/tests/test_extracted_game.py`, `test_release_contract.py` | Assert MS-2505 / US hashes | Parametrize per dump |
| `launcher/PinyonShift.Launcher/MainWindow.xaml:160` | UI text "The USA retail disc (MS-2505)" | Region-neutral text plus the detected region |
| `README.md` | Supported disc = USA only | Docs update |

## 2. Recompilation inputs (code addresses)

**EU + v4 done (`eu-v4`, 2026-10-08); EU without the update open
(`eu-image-diff`).** The EU disc is built only with its title update. The
patched images equal the USA v4 images, so the existing `analysis-v4/` and
`fh1_v4_addresses.inc` apply unchanged, and sections 2–4 matter only for an EU
build without the update. Real run: setup builds v4 from
`.local/game/eur-base`; the fresh-profile smoke route reaches the title screen
in English ("PRESS START") and German ("START DRÜCKEN") on an RTX 5060 laptop
GPU.

| Location | Assumption | EU work |
| --- | --- | --- |
| `config/rexglue/pinyon_shift_manifest.toml` | Paths `.local/game/base/*.xex`; one module set | Per-region game root / generated dirs (as v4 does) |
| `config/rexglue/analysis/main-xex.toml` | 121 `[[midasm_hook]]` + function entries/switch tables at USA addresses; header names MS-2505 | Port with `map-fh1-v4-addresses.py`-style mapping → `analysis-eu/` |
| `config/rexglue/analysis/fh1-post-processing.toml` | 4 hooks; keyed to the USA `default.xex` hash | Same |
| `config/rexglue/analysis/speech-facade.toml`, `xmedia-facade.toml` | Facade analysis for the USA modules | Port if the EU facades differ |
| `config/rexglue/accepted-codegen-warnings.json` | Warnings at USA addresses | Port addresses |
| `cmake/PinyonShiftRexGlue.cmake` | Base vs `PINYON_SHIFT_TITLE_UPDATE_V4` only; v4 built "from the USA disc" | Add a region dimension (preset per region × TU) |

## 3. Host code guest addresses

| Location | Assumption | EU work |
| --- | --- | --- |
| `src/fh1_guest_address.h` | `FH1_ADDR` = USA 0.0.0.10 address; only base↔v4 translation | Generalize to a per-build table (USA base / USA v4 / EU base / EU v4) |
| `src/fh1_v4_addresses.inc` | 83 USA→v4 pairs | One generated table per target build |
| `src/pinyon_shift_runtime_hooks.cpp` | 83 wrapped `FH1_ADDR` uses across files, plus **unwrapped** literals, e.g. `0x8269B4F8`, `0x833CE0EC`, `0x824D8300`, `0x827EC3C0`, `0x824D20B8` (≈2199–2241) and `kTitleUpdateV4 ? v4 : base` ternaries (9 sites, e.g. 6873–6875) | Wrap every guest address; replace ternaries with table lookups |
| `src/dlc_token_unlocks.cpp:39-45` | 6 **unwrapped** constants (`kProfileHolder 0x833F4A80`, `kGetProfile 0x82915BE0`, `kMakeBool`, `kSetPath`, `kDestroyValue`, `kPathString`) | Wrap them in `FH1_ADDR` |
| `src/cheats_map.cpp`, `src/dlc_treasure_map.cpp`, `src/native_renderer/graphics_hooks.cpp`, `src/save/profile_body.h` | A few unwrapped literals (some are range checks `0x82000000–0x83000000`, which are fine) | Review each |
| `FH1_BASE_ONLY_ADDR` (3 uses, Rally hub adapter) | USA base-only | Port for EU base, or keep Rally on v4 only for EU |
| Struct offsets (e.g. pause object `0xD48`, front-end `0x168/0x179`) | USA layout; v4 already shifts them | Re-verify on the EU executable |

## 4. Mod symbols

| Location | Assumption | EU work |
| --- | --- | --- |
| `config/mod/fh1-symbols.toml` | 38 addresses, keyed to the USA `default.xex` SHA-256 | Per-build symbol tables |
| `src/mod/fh1_symbols.inc`, `fh1_symbols_v4.inc` | Generated for USA base / v4 | Add EU outputs |
| `mods_src/samples/*/mod.toml` | Target the USA `default.xex` hash | Accept a list of compatible hashes |

## 5. Title update

**Done (`tu-autodownload`, 2026-10-08).** EU `4000D145` is a verified base: the
patched EU images equal the USA v4 images, so the existing v4 port applies to
EU unchanged; only the headers differ (media ID and version). Setup downloads,
verifies and installs the update automatically, the verifier picks the
installed disc as its base, and the launcher can download it from the update
row. Building and running EU + v4 is the `eu-v4` module.

| Location | Assumption | EU work |
| --- | --- | --- |
| `config/supported-title-updates.json` | `verified_bases` has only USA `2DC7007B` 0.0.0.10 (the TU's own target is media `4000D145` 0.0.0.12) | Add the EU base once verified (EU may be the TU's native target) |
| `tools/verify-fh1-title-update.py`, `tools/tests/test_title_update.py` | Tests use `2DC7007B` / `0000000A` | Parametrize |
| `tools/build-v4.ps1`, `config/rexglue/pinyon_shift_v4_manifest.toml`, `analysis-v4/*` | v4 from the USA disc | Per-region v4 |
| `tools/manage-title-update.ps1` | Import from a local file only | Add auto-download (SPEC decision 2) |

## 6. Title ID `4D5309C9` (verified identical on the EU disc)

`config/supported-dlc.json` (catalog-wide `title_id`),
`tools/manage-fh1-dlc.py:20,297` (content path `0000000000000000/4D5309C9`),
`src/pinyon_shift_runtime_hooks.cpp:4750` (user content path),
`tools/build-fh1-gpu-prewarm.py:17` and `tools/extract-fh1-shader-corpus.py:385`
(shader cache file names), and tests in `tests/dlc/content_roots_test.cpp`,
`tests/save/*`, `tests/native_renderer/fh1_shader_pack_test.cpp`.

## 7. Content and language

| Location | Assumption | EU work |
| --- | --- | --- |
| `supported-dumps.json` `languages` | 18 languages for the USA disc | EU list from the dump (archive label suggests En, Fr, De, Es, It, Nl) |
| `mods_src/samples/english_strings` | English string tables | Verify EU string file layout |
| Shader packs / prewarm (`build-fh1-gpu-prewarm.py`, shader corpus) | Built from USA shader corpus | Regenerate per region (local, never committed) |
| Render-test seeds (`config/render-tests/*.fh1test`) | Recorded on USA saves/routes | Re-run per region; routes may need EU-specific inputs |
