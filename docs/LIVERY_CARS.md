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
| `car-clone` | `tools/clone-fh1-car.py` | planned |
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
