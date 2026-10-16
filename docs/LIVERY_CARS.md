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
| `car-clone` | `tools/clone-fh1-car.py` | done (sources, rows, names, files, CLI; car IDs in `config/livery-cars/ids.json`) |
| `livery-paint` | `tools/paint-fh1-livery.py` | built (repaint, panel tables for six cars, recipes, `paint`, `panels`, probe checked in game on five cars); the player check is open |
| `livery-package` | `tools/package-fh1-livery.py`, `tools/manage-fh1-dlc.py` | in progress (package build, `install-livery`, names refresh; the title mounts the package and lists the car) |
| `promo-cars` | — | planned |

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

`repaint_xds(stock, rgba)` is how liveries are written: the new level 0 must
keep the stock alpha, and only the colour half of the DXT5 blocks whose texels
changed is re-encoded, at level 0 and in each mip block whose footprint holds
a changed texel. Every other byte (alpha halves, untouched blocks, padding,
header) stays the stock file's, so the interior parts and badges that share
the body texture come through unchanged.

### Evidence

| Date | Check | Result |
|---|---|---|
| 2026-10-09 | `roundtrip` on every `.xds` of the stock Challenger SRT8 392 (1557, disc), Scion FR-S (1548, disc) and Mustang Boss 302 (1569, October Car Pack) | 60 textures: **54 DXT1/DXT5 byte-exact** (2048², 1024², 512², 128², 64² and non-square 220×100, 150×40, 128×64, 120×40, 128×16, 64×16, 32×16); 6 normal maps (format 49) skipped by design |
| 2026-10-09 | `roundtrip --encode` (decode level 0, re-encode with mips, decode again) on the same 54 textures | level-0 error: worst mean **1.16/255**, worst max **33/255** (spec: 3 and 48); a 2048² texture with 12 levels in **5–21 s**; a car's body textures (incl. the stock colour variants) in 47–83 s (spec: 90 s per texture, 5 min per car) |
| 2026-10-09 | In game, EU v4 build, `fh1-opening-sync` from a fresh profile in a scratch state: a private asset mod replaces all 8 `nodamage*` textures of the opening Viper (`VIP_Viper_13`, whose stripes are painted in its body texture) with `fh1_xds` re-encodes; the launcher rebuilds the archive (`zz-archive-patches`) and the game opens it 8 times (`mod.file.override`) | Opening drive reached; the car renders like the stock run: **1.4–1.6/255** mean difference over the car region (whole frame 7.0–7.6/255 from wall-time scenery motion); the same two pre-existing log errors as the stock run, nothing new |
| 2026-10-11 | `repaint_xds` on the stock Challenger's `nodamage.xds` and `nodamage_LOD0.xds`: the decoded image unchanged, then a yellow rectangle over the top panel (0.45–0.75 × 0.62–0.70) | unchanged: **byte-identical** (1.7 s, 5.2 s); rectangle: 2,234 of 87,383 and 8,779 of 349,527 blocks re-encoded, **none outside the rectangle's footprint, alpha identical at every level**, 3.5 s and 15.2 s |

## Cloning a car (`tools/clone-fh1-car.py`)

```powershell
python tools\clone-fh1-car.py --state-root .local\preview --game-root .local\game\eur-base `
    --stock-id 1557 --new-id 3001 --media-name DOD_ChallengerSRT8392_RSE_12 `
    --display-name "Challenger SRT8 392 Rockstar Energy" --output <new folder>
```

The output is the car in the layout a package mounts: `media/cars/<NewMedia>/`,
`media/audio/cars/...` and `media/db/patch/<new ID>000_merge.slt`; the JSON
report on stdout lists the stock car and its archive, the new IDs, the shared
references, the two strings to write, rows per table, every file with its
SHA-256 and whether it was renamed or rewritten, and the SHA-256 of every
source read, checked unchanged before the output appears. `clone_car(...)`
returns the same report for `livery-package`. The clone refuses an existing
output, an ID that `config/livery-cars/ids.json` does not reserve for that
stock car (3001–3007), a car ID or media name already used by any installed
car or car folder, an unknown stock car, and a media name that is not a plain
file name; a failed clone leaves no output.

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
| 2026-10-10 | CLI: 1557 → 3001 (`DOD_ChallengerSRT8392_RSE_12`) and 1548 → 3002 (`SCI_FRS_MEG_13`) into scratch folders | **21 s each**; 195 rows in 47 tables and 67 files (61 MB), 171 rows in 48 tables and 58 files (32 MB); keys 6002/6003 and 6004/6005; the **84 source files hashed before and after are unchanged**. Refused as expected: an existing output, ID 3008 (not reserved), 1548 → 3001 (reserved for 1557), media names `SCI_FRS_13` (a disc car) and `FOR_MustangBoss302_PZA_13` (a package car); nothing left behind |

## Painting a livery (`tools/paint-fh1-livery.py`)

Turn 10's livery cars (the Pizza Hut Mustang and the Shelby GT500 Rockstar
Energy) carry their livery in the colour of the paint area, the texels whose
alpha is 0, of `nodamage.xds` and `nodamage_LOD0.xds`, with alpha and the
damage textures stock and `HasRaceLivery = 1`. A livery here is painted the
same way:

```powershell
python tools\paint-fh1-livery.py paint config\livery-cars\<name>.json --clone <car-clone output> `
    [--art .local\livery-art\<name>] [--preview <dir>]
```

A recipe names its car (checked against `config/livery-cars/ids.json`), the
stock car's media name (whose panel table, `config/livery-cars/panels/<StockMedia>.json`,
gives each body panel an outline and a frame of three corners) and ordered
layers: `fill` (panels or the whole paint area), `band` (a rectangle in panel
coordinates) and `image` (an 8-bit RGBA PNG from the local art folder, placed by
centre, width, rotation and mirror). Each layer is clipped to its outline and
the paint area unless it is `opaque`, and only colour is written. Both textures
are painted from the same normalised recipe, each against its own alpha, and
repainted through `fh1_xds.repaint_xds`; they replace the clone's copies
together once both are ready.

A stock car's panel table is authored from local previews of its own textures:

```powershell
python tools\paint-fh1-livery.py panels --state-root .local\preview --game-root .local\game\eur-base `
    --stock-media DOD_ChallengerSRT8392_12 --output .local\livery-panels\DOD_ChallengerSRT8392_12
```

It writes the paint area of both textures, the damage texture (whose scratches
outline every body panel) with a 0.05 grid, and on the Challenger Turn 10's
stripe lanes (each variant diffed against `nodamage`, inside the paint area);
with a table it also draws each outline and frame (the thick line runs front to
rear, the thin one top to bottom) and reports spec criterion 1: each outline's
share inside the paint area of both textures, the share of scratches covered,
and, of the stripe-lane texels that lie on panels, the share on `top`, `front`
and `rear` (Turn 10 paints its stripes past the panels' ends and into colour
swatches, so lanes off every panel are reported but not held against a table).

The six stock cars' tables (`config/livery-cars/panels/`) were traced from those
previews: a rough box per panel, the silhouette its scratches draw inside it
(closed over scratch gaps, window cut-outs kept as holes joined by bridges),
simplified to at most 64 points; the RUF's top, whose scratches are too sparse,
was outlined by hand around its two opaque openings. Each car has `left`,
`right`, `top`, `front` and `rear`, except the Murciélago, whose nose is part of
its top panel (its `front` is the strip along the lower nose).

The frames were checked in game with the probe livery, which paints a stock
car's panels opaque, each in its own colour, with a large patch per quadrant:
white at the front-top, black at the rear-top, magenta at the front-bottom and
cyan at the rear-bottom (on the top panel "top" is the car's left; on the front
and rear, u runs from the car's left to its right):

```powershell
python tools\paint-fh1-livery.py probe --state-root .local\preview --game-root .local\game\eur-base `
    --stock-media SCI_FRS_13 --output <render seed>      # a private asset mod in <seed>\mods\livery-probe
python tools\run-fh1-render-test.py config\render-tests\fh1-livery-probe-frs.fh1test --state-root <render seed> `
    --build-directory out\build\win-amd64-v4 --output <dir> --hidden
```

The routes (`fh1-livery-probe-{challenger,frs,murcielago,lancer,ruf}`) fast
travel to the Autoshow, open the stock car's showroom and orbit the camera
round it. The texture's upper side panel turned out to be the car's **right**,
laid with the car's top towards the texture's bottom; the top panel's upper
edge is the car's right; and every front fascia runs from the car's right to
its left. The tables now give all six cars the same layout, which a unit test
keeps: seen from outside, the left side and the rear are laid out upright and
the right side, the top and the front mirrored. An `image` layer therefore
flips itself on a mirrored panel, and `rotate` is clockwise as seen from
outside, so art reads as drawn on every panel; `mirror` flips it on purpose.

### Evidence

| Date | Check | Result |
|---|---|---|
| 2026-10-11 | `paint` with a six-layer test recipe (base fill, two bands on the top, synthetic disc art on both sides and the hood) into two copies of the scratch 3001 clone, with rough panel rectangles | **80–85 s** for both textures (18 s at 1024², 61–65 s at 2048²; spec: 3 min); the two runs **byte-identical**; alpha **identical at every level** and every block's alpha half kept. Every re-encoded block holds a painted texel; opaque texels sharing such a block with the paint area move by DXT re-encoding only (1.7–2.9% of them, mean 3–7/255, 95th percentile 9–21, at most 148 at a few badge edges) |
| 2026-10-11 | `panels` coverage of the six committed tables (spec criterion 1) | outlines inside the paint area of both textures: **99.03–100%** (worst: the Lancer's left side); scratches covered: **92.4–98.5%**; Challenger stripe lanes on panels: **100% on `top`, `front`, `rear`** (80% of all lane texels lie on panels; the rest are Turn 10's bleed past the panel ends and two colour swatches) |
| 2026-10-11 | Probe in game, Autoshow showroom, from a render seed of `.local/preview` (modded profile), for the Challenger, FR-S, Murciélago, Lancer and RUF; the Autoshow shows the Challenger in a stock stripe variant, so the probe paints every `nodamage*` variant | First pass (each panel's own colour) showed the side tables swapped and the upper side panel upside down; the quadrant patches then showed the top mirrored across the car's centreline and every front fascia mirrored. After the fixes all five read correctly from every side (confirmation pass: on each car the sides, hood, nose and tail show white at the front-top, black at the rear-top, magenta at the front-bottom and cyan at the rear-bottom as seen from outside; on the hood white is on the car's left, and on the nose and tail white is on the car's left). The Fiesta is a Unicorn car (`IsUnicorn = 1`) and is not in the Autoshow; a mod database patch does not reach the v4 database, so its table, laid out like the other five, is first seen in game by `livery-package` |
| 2026-10-11 | Spec open question 1: one Challenger panel painted in the probe colour but with its stock alpha 0 (`--alpha0-panel rear`), on the stock car (`HasRaceLivery = 0`) | in game the panel shows the **stock paint (white)**, not the probe colour, and not a mix: on a car without `HasRaceLivery` the paint colour replaces the paint area's texture colour entirely. Only stock-opaque texels inside the outline showed the probe colour. A livery therefore needs `HasRaceLivery = 1`, which `car-clone` sets; how it shows on such a car is `livery-package`'s first in-game check |

## Packaging a livery car (`tools/package-fh1-livery.py`)

A livery car ships the way Turn 10 shipped its own, the Shelby GT500 Rockstar
Energy (1606) and the Pizza Hut Mustang (1686): as a DLC package whose licence
owns the car's offer. `build_package` clones the stock car, paints the recipe
and adds what a DLC car needs:

- **Rows** in the clone's merge database: the recipe's price (`price: null`
  keeps the stock car's `BaseCost`), `IsUnicorn` 0 (the stock Fiesta is a
  Unicorn car, which keeps it out of the Autoshow), one `Combo_Colors` row in
  the recipe's paint colour (the clone's stripe and colour variants, which would
  replace the livery, are dropped with their `Combo_Colors_Exceptions` and
  `StripeColors` rows), and a hidden `ContentOffers` row (`PubOfferingID` = the
  car ID, `LicenseMask` 1, `OfferId` `0x4D5309C9_5053_0000` + the car ID) with
  its `ContentOffersMapping` (ID 10 × the car ID).
- **Names**: the title uses only the highest-priority copy of each language's
  `Data_Car.str`, so each Turn 10 package ships the whole table. A livery
  package does the same at priority = its car ID (above Turn 10's highest,
  2950): each language's winning installed table plus every enabled livery
  car's two entries (the short name is the stock car's, per language).
- **Thumbnail**: `Thumbnail_<id>.xds` is a ready-made 768×288 uncompressed
  texture (a three-quarter view beside a rotated side view, from Turn 10's
  offline renderer). The stock car's comes from the disc's
  `media/ui/Textures.zip`, unless the recipe names a 768×288 PNG as
  `"thumbnail"`.
- **Files**: `Media/<id>.puboffer` (the title takes the offer from its name),
  `Media/DLCZips/<id>_pri_65.zip` (the car, its audio tuning, the merge
  database and the thumbnail), `StringTables_pri_<id>.zip`, `stringtables.xml`
  and `zipmount.xml`. Archives are written by `patch-fh1-archive.write_archive`:
  stored members in Turn 10's order (files before folders, names compared in
  upper case), with extra field `0x1123` holding each member's data offset,
  which the title reads.
- **Header**: the 332-byte content header the SDK keeps beside an installed
  package, with licence mask `00000001` at byte 328, named
  `<year> <make> <car name>`. The package ID is fixed per car ID.

```powershell
# A package tree and header for inspection (writes nothing in a state root)
python tools\package-fh1-livery.py build --recipe config\livery-cars\tests\challenger-test.json `
    --state-root .local\preview --game-root .local\game\eur-base --output <dir>
```

`tools/manage-fh1-dlc.py install-livery` builds the package and installs it
beside the owned DLC, enabled (the game must be closed). A car that is already
installed is built again and replaced in place, keeping its enabled state; the
old copy is kept under `dlc/replaced/`. Its import record has `kind:
"generated"` and holds the recipe and art hashes, the string keys, the disc it
was built from and the payload digest; it is verified against that record,
since its payload depends on the player's disc and DLC, and its licence stays
`00000001`. `list`, `enable` and `disable` treat it like owned DLC;
`install-folder` never turns a disabled livery car back on.

After every change to the installed set (`import`, `install-folder`,
`enable`, `disable`, `install-livery`), the manager rewrites the Data_Car
tables of every enabled livery package, so whichever of them wins the
priority holds every name; a livery package that fails verification is
skipped, never re-signed.

```powershell
python tools\manage-fh1-dlc.py install-livery --recipe config\livery-cars\<name>.json `
    --state-root <state> --game-root .local\game\eur-base [--art .local\livery-art\<name>]
python tools\manage-fh1-dlc.py refresh-livery-strings --state-root <state>   # also runs after every change
```

`config/livery-cars/tests/` holds two recipes for the in-game checks, fills
and bands only: a Challenger test livery (car 3001) and a Fiesta orientation
livery (car 3006) that draws the probe's quadrant patches in colour. They are
used in private render seeds only.

### Evidence

| Date | Check | Result |
|---|---|---|
| 2026-10-16 | `build` of `tests/challenger-test.json` from the player's files, twice | **58 s and 59 s** (painting 22 s of it; spec: 5 min); the two trees and headers **byte-identical**; a 64.5 MB car archive of 69 members, names in 23 languages (from the Pizza Hut's table at 2950 and the Shelby's at 1450), every base entry kept |
| 2026-10-16 | Built package against the installed Pizza Hut and Shelby packages (spec criterion 2) | the **Shelby's file layout** (the Pizza Hut adds a cameras zip and loose audio folders); headers of the same layout and mask `00000001` (headers built for the Pizza Hut and Shelby equal theirs byte for byte); every member's `0x1123` offset right, zip versions as Turn 10's (1.0, no flags), stored members where theirs are LZX; 48 merge tables like the Shelby's, one `Combo_Colors` row, a hidden offer shaped like the Shelby's, `Data_Car`, `ContentOffers` and `Combo_Colors` columns equal to the Pizza Hut's; the car's flags as both Turn 10 cars (`HasRaceLivery` 1, `ContentId` 99, purchased, installed, selectable) |
| 2026-10-16 | In game, EU v4 build: the built package placed by hand in a private seed of `.local/preview` (no mods), the Autoshow's Dodge list, with the native DLC trace (`# dlc-car-trace`, `# dlc-car-ids 3001,1557`) | the title mounts the package: `dlc.content_entitlement` for car 3001 **installed 1, purchased 1, visible 1** (as the Pizza Hut's and Shelby's), `dlc.car_database` **installed, purchased, selectable, drivable** with the stock Challenger's upgrade counts (5 tyre, 5 suspension, 1 engine). Dodge shows a NEW badge; the list holds **"Challenger SRT8 392 Livery Test"** (2012 Dodge, A 507, **45,000 Cr**) with the stock thumbnail and a NEW tag, after the stock Challenger, which is still listed; other DLC cars keep their names (the full table works) |
| 2026-10-16 | The same seed: car 3001's showroom, orbit and raised captures | the **livery renders as painted**: the dark body, the yellow stripe over the hood, roof, nose and tail, the green band low on each side and the red block at each side's front-top. The bright yellow on a car whose paint colour is near-black shows that with `HasRaceLivery` 1 the paint area shows its texture colour as is, not blended with the paint colour (livery-paint open question 1). The showroom offers the car for 45,000 Cr or 2 Tokens |
| 2026-10-16 | Checkpoint B in the same private seed: `install-livery` of `tests/challenger-test.json` over the hand-placed copy, then after removing it; `disable`, `enable`, a rebuild, `refresh-livery-strings` | refused over content without its record ("did not build"); then built, installed and enabled in **59 s**, byte-identical to the `build` command's package; `list` shows it as `generated`, `gameplay_unverified`; `disable` and `enable` move it; the rebuild keeps it enabled and keeps the old copy under `dlc/replaced/`; the refresh has nothing to rewrite; the seed's other **1,283 files** (saves, Turn 10 packages, title update, config) are unchanged |
