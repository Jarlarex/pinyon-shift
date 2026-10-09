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
| `xds-codec` | `tools/fh1_xds.py` | layout and block read/write done |
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

```powershell
python tools\fh1_xds.py roundtrip <file.xds> [...]   # layout check, one JSON line per file
```

### Evidence

| Date | Check | Result |
|---|---|---|
| 2026-10-09 | `roundtrip` on every `.xds` of the stock Challenger SRT8 392 (1557, disc), Scion FR-S (1548, disc) and Mustang Boss 302 (1569, October Car Pack) | 60 textures: **54 DXT1/DXT5 byte-exact** (2048², 1024², 512², 128², 64² and non-square 220×100, 150×40, 128×64, 120×40, 128×16, 64×16, 32×16); 6 normal maps (format 49) skipped by design |
