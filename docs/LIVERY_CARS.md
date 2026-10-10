# Promotional livery cars

Seven Forza Horizon promotional and VIP liveries were sent by Turn 10's online
gift system and never shipped as packages. This work rebuilds them as separate
cars, generated on the player's machine from their own disc: a stock car is
cloned under a new car ID, its body textures are repainted with a recreated
livery, and the result is installed like owned DLC and bought in the Autoshow.
No game files, generated cars or livery art are committed; livery art lives in
`.local/livery-art/`.

| Module | Tool | State |
|---|---|---|
| `xds-codec` | `tools/fh1_xds.py` | done (layout, read/write, decode, encode, in-game check) |
| `car-clone` | `tools/clone-fh1-car.py` | sources, rows, names, files (CLI next) |
| `livery-paint`, `livery-package`, `promo-cars` | — | planned |

## Car textures (`tools/fh1_xds.py`)

`.xds` = 0x34-byte D3D texture header + data. Car body textures are DXT5
(format 53), tiled, 8-in-16 endian, with a full packed mip chain; interiors use
DXT1 (format 51); normal maps (format 49) are out of scope. Each level is padded
to whole 32×32-block tiles, and the levels from the first one whose shorter side
is 16 texels or less share one packed tile.

The packed tile's small levels are placed by the **base texture's** shape: for a
wide texture the 4×2, 2×1 and 1×1 levels of the FR-S's 128×64 `wood.xds` sit at
blocks (4,0), (2,0) and (1,0). The SDK's `GetPackedTileOffset`
(`texture/info.cpp`) computes per level with a fixed 16-texel step and agrees only
for square textures, which is every body texture.

Encoding picks DXT endpoints from each block's principal colour axis with one
least-squares pass; opaque DXT1 blocks also try the three-colour mode, whose
exact midpoint some stock interior textures use. Mips are box-filtered in linear
light. Identical blocks are encoded once, so large flat paint areas cost little.

```powershell
python tools\fh1_xds.py roundtrip [--encode] <file.xds> [...]  # layout check (+ re-encode error and time)
python tools\fh1_xds.py decode <file.xds> <out.png> [--level N]
python tools\fh1_xds.py encode <stock.xds> <in.png> <out.xds>   # header and size come from the stock file
```

### Evidence

| Date | Check | Result |
|---|---|---|
| 2026-10-09 | `roundtrip` on every `.xds` of the stock Challenger SRT8 392 (1557, disc), Scion FR-S (1548, disc) and Mustang Boss 302 (1569, October Car Pack) | 60 textures: **54 DXT1/DXT5 byte-exact** (2048², 1024², 512², 128², 64² and non-square 220×100, 150×40, 128×64, 120×40, 128×16, 64×16, 32×16); 6 normal maps (format 49) skipped by design |
| 2026-10-09 | `roundtrip --encode` (decode level 0, re-encode with mips, decode again) on the same 54 textures | level-0 error: worst mean **1.16/255**, worst max **33/255** (spec: 3 and 48); a 2048² texture with 12 levels in **5–21 s**; a car's body textures (incl. the stock colour variants) in 47–83 s (spec: 90 s per texture, 5 min per car) |
| 2026-10-09 | In game, EU v4 build, `fh1-opening-sync` from a fresh profile in a scratch state: a private asset mod replaces all 8 `nodamage*` textures of the opening Viper (`VIP_Viper_13`, whose stripes are painted in its body texture) with `fh1_xds` re-encodes; the launcher rebuilds the archive (`zz-archive-patches`) and the game opens it 8 times (`mod.file.override`) | Opening drive reached; the car renders like the stock run: **1.4–1.6/255** mean difference over the car region (whole frame 7.0–7.6/255 from wall-time scenery motion); the same two pre-existing log errors as the stock run, nothing new |

## Cloning a car (`tools/clone-fh1-car.py`)

The clone reads only the player's files: the title update's `gamedb.slt` with
the update's and every enabled package's merge applied on top (merge-number
order), so a car shipped in a package clones like a disc car. `clone_rows`
copies the stock car's car-defining rows to the new ID in a separate merge
database, the way Turn 10 made the Pizza Hut Mustang (1686) from the Boss 302
(1569):

| Rows | Clone |
|---|---|
| Car: `Data_Car`, `CameraOverrides`, `CarExceptions`, `CarPartPositions`, `Combo_Colors`, `Combo_Colors_Exceptions`, `List_AntiSwayPhysics`, `List_SpringDamperPhysics`, every `List_Upgrade*` keyed by `Ordinal` (and `CarPIOverrides`, `CarUpgradeExceptions`, `CarTrackOffsets`, `Combo_Engines`, `StripeColors` when the car has them) | keyed by the new car ID; row IDs `car × 1000 + n` renumbered under it |
| Stock engine (the `IsStock` row of `List_UpgradeEngine`): `Data_Engine`, `List_UpgradeEngine*`, the torque curves its camshaft rows name | engine ID = new car ID; rows and curves `engine × 1000 + n`; `Data_Engine.MediaName` takes the new media name (every stock engine's media name is its car's, and Turn 10 renamed it on the Pizza Hut) |
| Car body: `Data_CarBody`, `List_UpgradeCarBody*` (`CarBodyID`, `CarBodyId`, `CarbodyId`) | new car ID × 1000; rows body + n |
| Drivetrain: `Data_Drivetrain`, `List_UpgradeDrivetrain*` | drivetrain ID = new car ID; rows `drivetrain × 1000 + n` |
| Rows Turn 10 numbers 1, 2, 3, … (`Combo_Colors_Exceptions.ID`, `Combo_Engines.EngineComboID`) | new car × 1000 + n, so two clones never collide |
| Wheels, family, powertrain, aero, swap engines (other cars' stock engines, such as the Fiesta's 753 and 1003) | shared with the stock car, not copied |
| Gameplay rows that mention the car (`CarChallenges`, `CarChallengeTitles`, `EventParticipants`, `EventRecommendedCars`, `Rewards_*`, AI drivers) | never copied |

`Data_Car` changes only `Id`, `ModelId`, `MediaName`, `DisplayName`,
`ModelShort`, `Thumbnail` and `HasRaceLivery` (1). Every new ID is checked
against the rows already installed, and a row that breaks Turn 10's
numbering is refused rather than guessed. The 1100 and 1200 car packs both
ship the Boss 302, so tables without a key hold its rows twice after merging
(370 repeated `CarPartPositions` rows in all); each row is copied once.

Names are string-table entries, as on Turn 10's cars: `DisplayName` and
`ModelShort` hold `_&<(0xCD49 << 16) | key>`, a key of the `Data_Car` table
(the Pizza Hut's name `_&3444120859` is key 7451, "Mustang Boss 302: Pizza
Hut Edition"). A clone takes two keys unused by every installed table and
every car, searched from 2 × the car ID, so the livery cars 3001–3007 get
6002–6015 even when built before each other's packages are installed. The
display key holds the new name; the ModelShort key holds the stock car's
short name, as the Pizza Hut's key 6879 holds the Boss 302's "Ford Mustang
'13". `livery-package` writes both into every language's table.

The model tree is the stock car's archive under `media/cars/<NewMedia>/`,
byte for byte, with the stock media name replaced, in the case each file
wrote it, wherever a file name carries it: the model files, the lowercase
`stripped_` copies, the build report and exporter settings (`Last_*.xml`).
In `DigitalGauge/` only `Dash_<media>.bgf/.bsg/.fbf` are renamed, because
the v4 title opens `<car>\digitalgauge\Dash_<media>.bgf` by media name;
the gauge textures keep their names. The dash `.fbf` is the one file that
names the car's folder: its textures are absolute paths
(`GAME:\MEDIA\CARS\<MEDIA>\DIGITALGAUGE\…`, a big-endian u32 length then
the text), which are pointed at the new folder. `CarAttribs.xml`,
`ShaderSettings.xml`, the carbins and the audio XMLs name no car. The two
audio tuning files are renamed into `media/audio/cars/CarModelTuning/` and
`media/audio/cars/Engines/EngineTuning/`.

### Evidence

| Date | Check | Result |
|---|---|---|
| 2026-10-10 | Boss 302 (1569) cloned to test ID 3999 from the v4 database with all 16 enabled packages merged, compared with Turn 10's Pizza Hut merge (`2800000_merge.slt`) | **145 rows in 48 tables**. Table set = the Pizza Hut's minus its package rows (`ContentOffers`, `ContentOffersMapping`) and its own-wheel rows (`List_Wheels`, `List_FamilyModel`). Key structure identical in **46 of 48** tables; the two that differ are Turn 10's livery choices: `Combo_Colors` (the Pizza Hut has one paint, colour class 15; the Boss 302 five) and `Data_Car.StockWheelID` (its own wheel 15019). **Every value equals the Boss 302's** apart from re-keyed IDs and the documented fields above plus `Data_Engine.MediaName` |
| 2026-10-10 | `clone_rows` for the seven livery stock cars (1557, 1548 twice, 1516, 1173, 1082, 1009 → 3001–3007) | all clone: 103–195 rows in 45–49 tables; the Challenger's 19 colour exceptions and the Murciélago's stripe colour copied; the Fiesta's two swap engines shared |
| 2026-10-10 | `clone_names` against all 484 installed `Data_Car` tables (22 on the disc, the rest in 22 packages' `StringTables_pri_*` archives, every language): 516 keys, among them all 502 keys the 251 cars name | 3001–3007 get keys 6002–6015, all free; ModelShort copies stock keys 23100, 7612 (FR-S, twice), 50476, 55484, 6175, 7581 |
| 2026-10-10 | `clone_files` on the Boss 302 under the Pizza Hut's media name, against Turn 10's Pizza Hut package | **58 files with exactly Turn 10's 58 names**; 46 byte-identical; the other 12 are files Turn 10 re-exported or repainted (the three main carbins and their stripped copies, `BuildNumber.txt`, the build report, `Dash_*.bgf`, `nodamage.xds`, `nodamage_LOD0.xds`); our rewritten `.fbf` differs from Turn 10's only in its own font and placeholder text. The Pizza Hut's `damage*.xds` are the Boss 302's unchanged |
| 2026-10-10 | `clone_files` on the Challenger (1557) and FR-S (1548) | 67 and 58 files (63.4 and 33.0 MB), 28 renamed each, one `.fbf` rewritten each; gauge textures kept (`DOD_SRT8_09_GEARBASE.XDS`, `SCI_FRS_13_TXT_MPH.XDS`, …); the six livery stock cars' archives embed their folder only in the dash `.fbf` (the RUF has no dash) |
