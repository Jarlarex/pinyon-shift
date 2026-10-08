# EU + v4 DLC qualification matrix

Build: EU disc (media `4000D145`) + title update v4, `out/build/win-amd64-v4`.
Packages were installed from a personal folder with `manage-fh1-dlc.py install-folder` and all are enabled.
"Mounted" and "read at start" come from a scripted `fh1-free-roam` run on a private copy of an EU save
(2026-10-08, runtime trace `content.create.result` and file opens on `DLCRoot<n>:`). The remaining columns need
a playtest in the Autoshow and events and are pending.

| Package | Licence mask | Installed | Mounted | Read at start | In Autoshow | Bought + driven | Save reload |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Pre-Order Car Pack | `FFFFFFFF` | yes | yes | db, effects | pending | pending | pending |
| Season Pass: 2006 Lamborghini Miura Concept | `00000001` | yes | yes | not yet | pending | pending | pending |
| VIP Membership & Cars Pack | `FFFFFFFF` | yes | yes | db, effects | pending | pending | pending |
| February Jalopnik Car Pack | `FFFFFFFF` | yes | yes | db, effects | pending | pending | pending |
| LCE: Day1 DLC Pack | `00000001` | yes | yes | db, effects | pending | pending | pending |
| March Meguiar's Car Pack | `FFFFFFFF` | yes | yes | db, effects | pending | pending | pending |
| 2010 Ferrari 458 Italia | `00000001` | yes | yes | strings | pending | pending | pending |
| April TopGear Car Pack | `00000001` | yes | yes | db, effects | pending | pending | pending |
| 2012 Aston Martin Virage | `00000001` | yes | yes | strings | pending | pending | pending |
| 2013 Ford Shelby GT500 - Rockstar Energy | `00000001` | yes | yes | not yet | pending | pending | pending |
| November Bondurant Car Pack | `FFFFFFFF` | yes | yes | db, effects | pending | pending | pending |
| October Car Pack | `FFFFFFFF` | yes | yes | db, effects | pending | pending | pending |
| December IGN Car Pack | `FFFFFFFF` | yes | yes | db, effects | pending | pending | pending |
| 2011 Mercedes-Benz SLS AMG | `00000001` | yes | yes | strings | pending | pending | pending |
| 2010 Volkswagen Golf R | `00000001` | yes | yes | strings | pending | pending | pending |
| 2013 Ford Mustang Boss 302 - Pizza Hut Edition | `00000000` | yes | yes | not yet | pending | pending | pending |
| Honda Challenge Car Pack | `00000001` | yes | yes | db, effects | pending | pending | pending |
| January Recaro Car Pack | `FFFFFFFF` | yes | yes | db, effects | pending | pending | pending |
| 2010 Nissan 370Z | `00000001` | yes | yes | strings | pending | pending | pending |
| 1000 Club Expansion Pack | `00000001` | yes | yes | db, effects | pending | pending | pending |
| Rally Expansion Pack | — | **no**: the supplied copy is the rejected variant (`AA7BD510…`) | — | — | — | — | — |

Notes:
- 1000 Club runs with the update's offline setting on (setup turns it on for the EU disc).
- "Not yet" means the package mounted but no file was opened before the route ended; the Autoshow check decides.
  The Mustang's licence mask is `00000000` as supplied; it is recorded, never changed.

## Known issues found during qualification

| Issue | Evidence | Status |
| --- | --- | --- |
| The achievements screen reopens every ~150 ms after closing, so the game cannot be resumed | Session `20261008T172437Z`: repeating `xam.dialog.open kind=achievements` → `hostui.open` → `hostui.closed` until a forced exit | Fixed in `8e40e24`: the host UI swallowed the release of the key that chose Achievements, so the keyboard emulation kept it held. Needs a manual keyboard check (scripted routes drive the pad) |
| Visual artifacts when driving fast | Player report. Same session: no dropped draws (`skips={}`), no shader-pack misses; frame time median 8.3 ms, p99 20 ms, 81 frames over 100 ms (max 1.4 s), consistent with first-use shader translation before shader preparation worked (`5cf0740`); peak VRAM 1.3 GB of a 7.1 GB budget | Open: recheck after preparation; needs a description or screenshot if it is not stutter |
