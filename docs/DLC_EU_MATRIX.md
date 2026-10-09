# EU + v4 DLC qualification matrix

Build: EU disc (media `4000D145`) + title update v4, `out/build/win-amd64-v4`.
Packages were installed from a personal folder with `manage-fh1-dlc.py install-folder` and all are enabled.
"Mounted" and "read at start" come from a scripted `fh1-free-roam` run on a private copy of an EU save
(2026-10-08, runtime trace `content.create.result` and file opens on `DLCRoot<n>:`). The remaining columns need
a playtest in the Autoshow and events and are pending.

| Package | Licence mask | Installed | Mounted | Read at start | In Autoshow | Bought + driven | Save reload |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Pre-Order Car Pack | `FFFFFFFF` | yes | yes | db, effects | yes (player check 2026-10-08) | pending | pending |
| Season Pass: 2006 Lamborghini Miura Concept | `00000001` | yes | yes | not yet | yes (player check 2026-10-08) | pending | pending |
| VIP Membership & Cars Pack (`210BB005…`, offer 2100) | `FFFFFFFF` | yes | yes | db, effects | yes (player check 2026-10-08) | pending | pending |
| VIP Membership & Cars Pack (`A5B171B8…`, offer 1006) | `00000001` | yes (2026-10-08, later supply) | pending | pending | pending | pending | pending |
| February Jalopnik Car Pack | `FFFFFFFF` | yes | yes | db, effects | yes (player check 2026-10-08) | pending | pending |
| LCE: Day1 DLC Pack | `00000001` | yes | yes | db, effects | yes (player check 2026-10-08) | pending | pending |
| March Meguiar's Car Pack | `FFFFFFFF` | yes | yes | db, effects | yes (player check 2026-10-08) | pending | pending |
| 2010 Ferrari 458 Italia | `00000001` | yes | yes | strings | yes (player check 2026-10-08) | pending | pending |
| April TopGear Car Pack | `00000001` | yes | yes | db, effects | yes (player check 2026-10-08) | pending | pending |
| 2012 Aston Martin Virage | `00000001` | yes | yes | strings | yes (player check 2026-10-08) | pending | pending |
| 2013 Ford Shelby GT500 - Rockstar Energy | `00000001` | yes | yes | not yet | **yes**, with the Rockstar livery (player check 2026-10-08) | pending | pending |
| November Bondurant Car Pack | `FFFFFFFF` | yes | yes | db, effects | yes (player check 2026-10-08) | pending | pending |
| October Car Pack | `FFFFFFFF` | yes | yes | db, effects | yes (player check 2026-10-08) | pending | pending |
| December IGN Car Pack | `FFFFFFFF` | yes | yes | db, effects | yes (player check 2026-10-08) | pending | pending |
| 2011 Mercedes-Benz SLS AMG | `00000001` | yes | yes | strings | yes (player check 2026-10-08) | pending | pending |
| 2010 Volkswagen Golf R | `00000001` | yes | yes | strings | yes (player check 2026-10-08) | pending | pending |
| 2013 Ford Mustang Boss 302 - Pizza Hut Edition | `00000001` (catalog grant; the package supplies `00000000`) | yes | yes (`DLCRoot17`) | not yet | yes (player check 2026-10-09); before the grant only the base Boss 302 appeared (player check 2026-10-08) | yes (player check 2026-10-09) | pending |
| Honda Challenge Car Pack | `00000001` | yes | yes | db, effects | yes (player check 2026-10-08) | yes: Civic Si bought | yes: kept after restart |
| January Recaro Car Pack | `FFFFFFFF` | yes | yes | db, effects | yes (player check 2026-10-08) | pending | pending |
| 2010 Nissan 370Z | `00000001` | yes | yes | strings | yes (player check 2026-10-08) | pending | pending |
| 1000 Club Expansion Pack | `00000001` | yes | yes | db, effects | yes (player check 2026-10-08) | pending | pending |
| Rally Expansion Pack | `FFFFFFFF` here (accepted copy `00000001`, catalog grant `00000004`, licence-only copy `AA7BD510…`); `00000005` from the accepted copy alone | yes (accepted copy `0D9F6833…`) | yes (`DLCRoot8`) | yes | yes; the 2003 Ford Focus SVT (Season Pass offer, mask `00000004`) is owned, visible and selectable (native entitlement trace and player check 2026-10-09) | yes, including the Focus SVT (player check 2026-10-09) | yes; championships finished (player checks 2026-10-08 and 2026-10-09) |

Notes:
- Purchases persist: a Civic Si and a GMC Vandura bought on the EU save were still owned after a restart (player check 2026-10-08).
- 1000 Club runs with the update's offline setting on (setup turns it on for the EU disc).
- "Not yet" means the package mounted but no file was opened before the route ended; the Autoshow check decides.
  The Mustang's licence mask is `00000000` as supplied; licence masks may be changed or modified within the project.
  The catalog grants it `00000001` (offer 2800) and Rally `00000004` (the Focus SVT's Season Pass offer), so the
  accepted Rally copy alone is enough. Rally's corrupt copy may still add its `FFFFFFFF` licence, imported beside the
  accepted copy without installing that copy's files (2026-10-09).

- Later supplies (2026-10-08): two more Mustang Pizza Hut copies were byte-identical to the first (no licence), and a
  multi-pack archive held the same rejected Rally variant; its second VIP package was new and is installed. A further supply held the accepted Rally package (`0D9F6833…`), now installed; the earlier rejected and truncated copies are no longer needed.
- The Challenger SRT8 392 Rockstar livery belongs to a package that is not among the supplied files; only the
  base Challenger appears, as expected. It is a livery, not a separate car: the only Rockstar car is the Shelby GT500
  above. All 236 cars of the reference list are present; see [the car list check](CAR_LIST_CHECK.md).

## Known issues found during qualification

| Issue | Evidence | Status |
| --- | --- | --- |
| The achievements screen reopens every ~150 ms after closing, so the game cannot be resumed | Session `20261008T172437Z`: repeating `xam.dialog.open kind=achievements` → `hostui.open` → `hostui.closed` until a forced exit | Fixed in `8e40e24`: the host UI swallowed the release of the key that chose Achievements, so the keyboard emulation kept it held. Needs a manual keyboard check (scripted routes drive the pad) |
| The archive extractor crashes (0xC0000005) on a truncated STFS package instead of reporting an error | Rally copy `53037F21…` | Open: SDK package reader should bound reads by the file size |
| Rally froze on the loading screen after the fourth stage of championship 2, before the results; the championship's progress was lost | Session `20261009T140306Z`: no save writes during the championship (v4 saves at its end); at the freeze audio stopped and every frame drew the same picture, with no crash or error logged | Seen once: replaying the championship finished normally (player check 2026-10-09). If it recurs, keep the game on that screen and capture the process state |
| Visual artifacts when driving fast | Player report. Same session: no dropped draws (`skips={}`), no shader-pack misses; frame time median 8.3 ms, p99 20 ms, 81 frames over 100 ms (max 1.4 s), consistent with first-use shader translation before shader preparation worked (`5cf0740`); peak VRAM 1.3 GB of a 7.1 GB budget | Resolved: no excessive stutter after shader preparation (player check 2026-10-08) |
