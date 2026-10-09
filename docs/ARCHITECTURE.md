# Architecture overview

Summary of Pinyon Shift as of `dev` `589f7ea` (ShiftGlue `797eebc`), written
as the starting point for EU-disc and title-update work. Deeper, authoritative
records live in [DEVELOPMENT.md](DEVELOPMENT.md), [BUILDING.md](BUILDING.md),
[DLC_BACKLOG.md](DLC_BACKLOG.md) and
[TITLE_UPDATE_V4_BACKLOG.md](TITLE_UPDATE_V4_BACKLOG.md).

## Pipeline

```text
user ISO ──verify──> tools ──> extract ──> codegen ──> build ──> shader prep ──> play
(exact hash)  (pinned)   (extract-xiso)  (ReXGlue)  (CMake/clang-cl)  (Vulkan packs)
```

The launcher (`launcher/PinyonShift.Launcher`, C#/WPF) drives these stages
(`RouteStep.StageOrder`: verify, tools, extract, build, play) by running
PowerShell scripts and parsing their `-JsonEvents` output.

| Stage | Entry point | What it does |
| --- | --- | --- |
| verify | `tools/verify-game.ps1` | Exact ISO size + SHA-256 match against `config/supported-dumps.json`; unknown dumps are rejected. After extraction, executables are checked by hash too. |
| tools | `tools/provision-toolchain.ps1`, `tools/install-build-tools.ps1` | VS C++ Build Tools (elevated, signature-checked bootstrapper); pinned portable CMake, MinGit, xz, LLVM/clang-cl, extract-xiso, embedded Python from `config/release-toolchain.json` into `.local/toolchain`. |
| extract | `tools/setup-preview.ps1` | `extract-xiso` into `.local/game/base`, skipping the system update; `-ExtractedPath` accepts an already extracted folder ([EXTRACTED_GAME_INPUT.md](EXTRACTED_GAME_INPUT.md), `config/supported-extracted-ms-2505.json`). |
| codegen | ReXGlue via `cmake/PinyonShiftRexGlue.cmake` | Recompiles `default.xex`, `SpeechFacade_default.xex`, `XMediaFacade_default.xex` per `config/rexglue/pinyon_shift_manifest.toml` + `analysis/*.toml` into `.local/generated/`. |
| build | `tools/build-preview.ps1` | CMake preset `win-amd64-release` → `out/build/win-amd64-release/pinyon_shift.exe` + `rexgpu-fh1.dll`. |
| shader prep | `tools/prepare-fh1-shaders.ps1` | Private startup run fills offline Vulkan shader packs; misses are recorded and repaired next launch. |
| play | `tools/launch-preview.ps1` | Launches with a state root (`%LOCALAPPDATA%\PinyonShift\...`); `-TitleUpdateV4` selects the v4 build. |

Nothing derived from the disc is committed: inputs and outputs resolve into
ignored `.local/` paths, and `tools/check-repository-boundary.ps1` (CI)
enforces it with `config/repository-policy.json`.

## Components

- **ShiftGlue SDK** (`thirdparty/shiftglue-sdk`, submodule; fork of ReXGlue):
  PowerPC → C++ recompiler, Xbox 360 kernel/XAM HLE, VFS, `ContentManager`
  (STFS reader, content install, header writer), XEX loader incl. `.xexp` delta
  patching (`XexModule::ApplyPatch`, default-off `xex_apply_patches`),
  graphics system. Exports `NvOptimusEnablement` /
  `AmdPowerXpressRequestHighPerformance` (`src/graphics/graphics_system.cpp`),
  so hybrid laptops pick the discrete GPU.
- **Patch system:** game-specific hooks are `[[midasm_hook]]` entries (121 in
  `config/rexglue/analysis/main-xex.toml`, 4 in `fh1-post-processing.toml`)
  plus host code in `src/pinyon_shift_runtime_hooks.cpp` (≈8.5k lines),
  `cheats_map.cpp`, `dlc_treasure_map.cpp`, `dlc_token_unlocks.cpp`.
  `PATCH_DISPOSITIONS.md` records why each SDK patch exists.
- **Guest addresses:** host code writes base-disc (USA 0.0.0.10) addresses as
  `FH1_ADDR(0x…)` (`src/fh1_guest_address.h`, 83 unique) or
  `FH1_BASE_ONLY_ADDR` (3). A v4 build translates them at compile time through
  `src/fh1_v4_addresses.inc`; an unmapped address is a compile error. The
  mapping comes from `tools/map-fh1-v4-addresses.py` (exact normalized bodies →
  call-graph anchoring → context windows → vtable/lis-addi refs → shape
  match), and `tools/port-fh1-v4-analysis.py` ports the analysis TOMLs to
  `config/rexglue/analysis-v4/`. **This is the mechanism to reuse for EU.**
- **Renderer:** `rexgpu-fh1.dll` native executor (PM4 → Vulkan), the only
  renderer; D3D12 is legacy. 1x/2x/3x scales, offline shader packs.
- **Mods:** `include/pinyon_mod.h`, `config/mod/fh1-symbols.toml` (38
  addresses, keyed to the base `default.xex` SHA-256), generated
  `src/mod/fh1_symbols.inc` / `fh1_symbols_v4.inc`.
- **Saves:** `src/save/*`, `save_backups.cpp`; user content under
  `<state>/user/0000000000000000/4D5309C9`.

## DLC and title update (already on `dev`)

- **DLC import:** `tools/manage-fh1-dlc.py` + `tools/manage-dlc.ps1`, launcher
  DLC panel. Accepts raw packages, folders or ZIPs; validates against
  `config/supported-dlc.json` (21 identities, 30 accepted whole-package
  hashes, licence masks, payload hashes, per-package licence grants); imports
  atomically; starts disabled.
  Installs under `<state>/user/0000000000000000/4D5309C9/00000002`.
- **Rally on base disc:** `tools/prepare-fh1-rally.py` builds an adapter cache
  from the owned package + base-disc inputs; `src/dlc/rally_*`.
- **Title update v4:** `config/supported-title-updates.json` pins the world v4
  package (`4D5309C9`, built for media `4000D145` 0.0.0.12 → 0.0.4.12).
  `tools/verify-fh1-title-update.py` applies each `.xexp` and checks every page
  against the patched hash chain. It is proven to apply exactly to the USA
  0.0.0.10 disc (`2DC7007B`). `tools/manage-title-update.ps1` imports a
  user-supplied package (no download), and `tools/build-v4.ps1` / preset
  `win-amd64-v4` build a separate v4 executable with native Rally and
  1000 Club. Base stays the default.

## Status per area (relevant to the EU/DLC goal)

| Area | Status on `dev` |
| --- | --- |
| US base disc | Supported, exact hash |
| US + TU v4 | Built and playable opt-in; TU imported from a user file |
| STFS parsing / DLC import | Done (SDK reader + project importer) |
| DLC gameplay | Rally playable (base adapter and v4); 1000 Club on v4; car packs mostly "import verified, gameplay pending" |
| EU disc | **Not supported**; rejected by hash |
| TU auto-download | **Not implemented** |
| Region abstraction | Compile-time base↔v4 only; no region dimension |

See [EU_BACKLOG.md](EU_BACKLOG.md) for every place the USA
disc is assumed.
