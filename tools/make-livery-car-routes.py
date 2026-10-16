#!/usr/bin/env python3
"""Write the render-test routes that check a livery car in game.

From a livery recipe and the car's place in the Autoshow (presses right to its
make in the manufacturer carousel, then to its card), this writes
config/render-tests/fh1-promo-<recipe>-<kind>.fh1test for each kind:

  list      the make's cards, to find the car's place
  showroom  the car's showroom, the camera orbiting it and then raised
  buy       buy it for credits, return to free roam and drive it
  reload    from the state a buy run left: drive it again
  garage    from that state: fast travel to Dak's Garage, auto-upgrade it, drive it
  paint     from that state: fast travel to the Paint Shop, repaint it, drive it
  paint-clear  from the state a paint run left: Clear Design, drive it

Every route logs the native DLC trace for the car and its stock car. The
routes run from a render seed of the .local/preview save, which spawns at
Dak's Garage with enough credits, with the car installed by
`manage-fh1-dlc.py install-livery`; reload, garage and paint run from the
private state folder (<output>.state) a buy run leaves, paint-clear from the
one a paint run leaves. The Paint Shop's editor shows every car in its paint
colour; a saved repaint replaces a livery, and Clear Design brings it back.
"""
import argparse
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADER = "pinyon-shift-fh1-render-test-v1"
KINDS = ("list", "showroom", "buy", "reload", "garage", "paint", "paint-clear")
# Steps are written relative to free roam (frame 1700) and shifted by this much, since load times vary;
# a wait's limit gets the same allowance.
SETTLE = 600
A, X, Y, START, RIGHT = "1000", "4000", "8000", "0010", "0008"


def _load_tool(name: str):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# -- steps ------------------------------------------------------------------

def to_autoshow(make_presses: int) -> tuple[list, int]:
    """From Dak's Garage: pause, MAP, the cursor nudged onto the Autoshow, Y fast travel, A; X enters
    the Autoshow; right `make_presses` times in the manufacturer carousel. Returns (steps, next frame)."""
    steps = [["press", 1750, START], ["press", 2000, A], ["input", 2420, "0000", 0, 0, 20000, 15000],
             ["input", 2435, "0000", 0, 0, 0, 0], ["press", 2500, Y], ["press", 2650, A],
             ["capture", 4200, "arrived"], ["press", 4250, X], ["capture", 4650, "makes"]]
    frame = 4850
    for _ in range(make_presses):
        steps.append(["press", frame, RIGHT])
        frame += 30
    return steps, frame


def list_steps(make_presses: int, cards: int) -> list:
    steps, frame = to_autoshow(make_presses)
    steps.append(["capture", frame + 40, "make"])
    steps.append(["press", frame + 60, A])
    frame += 500
    steps.append(["capture", frame + 20, "card-00"])
    for n in range(1, cards):
        steps.append(["press", frame + 40, RIGHT])
        frame += 70
        steps.append(["capture", frame + 20, f"card-{n:02d}"])
    steps.append(["stop", frame + 60])
    return steps


def _to_card(steps: list, frame: int, car_presses: int) -> int:
    for _ in range(car_presses):
        steps.append(["press", frame, RIGHT])
        frame += 50
    steps.append(["capture", frame + 20, "card"])
    steps.append(["press", frame + 40, A])
    return frame


def showroom_steps(make_presses: int, car_presses: int) -> list:
    steps, frame = to_autoshow(make_presses)
    steps.append(["capture", frame + 40, "make"])
    steps.append(["press", frame + 60, A])
    frame = _to_card(steps, frame + 500, car_presses) + 600
    steps.append(["capture", frame, "orbit-00"])
    for n in range(1, 41):
        steps += [["input", frame + 10, "0000", 0, 0, 0, 0, 22000, 0], ["input", frame + 16, "0000", 0, 0, 0, 0]]
        frame += 40
        steps.append(["capture", frame, f"orbit-{n:02d}"])
    steps += [["input", frame + 10, "0000", 0, 0, 0, 0, 0, 30000], ["input", frame + 90, "0000", 0, 0, 0, 0]]
    frame += 130
    steps.append(["capture", frame, "high-00"])
    for n in range(1, 13):
        steps += [["input", frame + 10, "0000", 0, 0, 0, 0, 22000, 0], ["input", frame + 18, "0000", 0, 0, 0, 0]]
        frame += 45
        steps.append(["capture", frame, f"high-{n:02d}"])
    steps.append(["stop", frame + 30])
    return steps


def drive_and_look(steps: list, frame: int) -> int:
    """Hold the throttle until the car has moved 15 m (so free roam is back), capture it from behind,
    brake, and turn the camera to each side; returns the next free frame."""
    steps.append(["input", frame, "0000", 0, 255, 0, 0])
    steps.append(["wait", frame + 10, 2400, "vehicle-moved", 15])
    steps.append(["capture", frame + 20, "drive-rear"])
    steps.append(["input", frame + 30, "0000", 255, 0, 0, 0])
    steps.append(["input", frame + 150, "0000", 0, 0, 0, 0])
    frame += 200
    for name, rx, ry in (("look-right", 32767, 0), ("look-left", -32768, 0), ("look-back", 0, 32767)):
        steps.append(["input", frame, "0000", 0, 0, 0, 0, rx, ry])
        steps.append(["capture", frame + 45, name])
        steps.append(["input", frame + 60, "0000", 0, 0, 0, 0])
        frame += 90
    return frame


def buy_steps(make_presses: int, car_presses: int) -> list:
    steps, frame = to_autoshow(make_presses)
    steps.append(["press", frame + 60, A])
    frame = _to_card(steps, frame + 500, car_presses) + 300
    steps.append(["capture", frame, "showroom"])
    steps.append(["press", frame + 20, A])                     # BUY
    steps.append(["capture", frame + 80, "confirm"])
    steps.append(["press", frame + 100, A])                    # buy with credits
    steps.append(["capture", frame + 150, "saving"])
    # The title saves and renders the car's garage thumbnail, a .xdc in the profile.
    steps.append(["wait", frame + 160, 3000, "file", ".xdc"])
    frame += 400
    steps.append(["capture", frame, "return-prompt"])
    for n in range(3):                                         # return to free roam; the later presses are a brake tap
        steps.append(["press", frame + 20 + 120 * n, A])
    frame = drive_and_look(steps, frame + 400)
    steps.append(["stop", frame + 30])
    return steps


def reload_steps() -> list:
    steps = [["capture", 1750, "spawn"]]
    frame = drive_and_look(steps, 1900)
    steps.append(["stop", frame + 30])
    return steps


# From outside the Autoshow, where a buy run leaves the player, the pause map's cursor is nudged onto a
# festival-hub icon: the hub's icons sit close together and the cursor snaps to the nearest one.
DAKS_GARAGE = (-20000, -10000)
PAINT_SHOP = (-20000, -15000)
DOWN = "0002"


def _fast_travel(steps: list, nudge: tuple[int, int], label: str) -> None:
    """Pause, MAP, the cursor nudged onto a hub icon (captured with its label), Y fast travel, A."""
    steps += [["press", 1750, START], ["press", 2000, A],
              ["input", 2420, "0000", 0, 0, *nudge], ["input", 2435, "0000", 0, 0, 0, 0],
              ["capture", 2480, f"map-{label}"], ["press", 2500, Y], ["press", 2650, A],
              ["captures", 2700, 4200, 500, "travel-"]]


def garage_steps() -> list:
    """Dak's Garage: X opens the garage; Auto Upgrade, A on its explanation, A on the first class offered
    (the top of the car's own class), A to buy and install the parts; the title saves; B and A leave the
    garage; then the car is driven."""
    steps = []
    _fast_travel(steps, DAKS_GARAGE, "garage")
    steps += [["press", 4250, X], ["capture", 4600, "garage-menu"], ["press", 4650, A],
              ["capture", 5300, "auto-upgrade"], ["press", 5350, A], ["capture", 5420, "classes"],
              ["press", 5450, A], ["capture", 6300, "install"], ["press", 6350, A],
              ["captures", 6400, 7000, 300, "installed-"], ["press", 7050, "2000"], ["capture", 7300, "leave-prompt"],
              ["press", 7350, A]]
    frame = drive_and_look(steps, 7800)
    steps.append(["stop", frame + 30])
    return steps


def _leave_paint_shop(steps: list, frame: int) -> int:
    """B to the Design Creator menu, B to the Paint Shop menu, B and A leave the Paint Shop."""
    steps += [["press", frame, "2000"], ["press", frame + 300, "2000"], ["press", frame + 600, "2000"],
              ["capture", frame + 850, "leave-prompt"], ["press", frame + 900, A]]
    return frame + 1850


def paint_steps() -> list:
    """The Paint Shop: X, Design Creator, Paint Car, Paint Body; a colour five steps to the right, A;
    Start saves, A to the current car; the Paint Shop is left and the car driven."""
    steps = []
    _fast_travel(steps, PAINT_SHOP, "paint")
    steps += [["press", 4250, X], ["capture", 4600, "paint-menu"], ["press", 4650, A], ["capture", 5500, "creator"],
              ["press", 5550, A], ["capture", 6400, "paint-car"], ["press", 6450, A], ["capture", 7300, "colours"]]
    for n in range(5):
        steps.append(["press", 7400 + 25 * n, RIGHT])
    steps += [["capture", 7600, "colour"], ["press", 7650, A], ["capture", 7900, "applied"],
              ["press", 7950, START], ["capture", 8200, "save"], ["press", 8250, A], ["capture", 8700, "saved"]]
    frame = drive_and_look(steps, _leave_paint_shop(steps, 8950))
    steps.append(["stop", frame + 30])
    return steps


def paint_clear_steps() -> list:
    """From the Paint Shop where the paint run leaves the player: X, Design Creator, down five times to
    Clear Design, A, A to erase the paint and decals; the Paint Shop is left and the car driven."""
    steps = [["capture", 1750, "spawn"], ["press", 1800, X], ["capture", 2150, "paint-menu"], ["press", 2200, A],
             ["capture", 2650, "creator"]]
    for n in range(5):
        steps.append(["press", 2700 + 25 * n, DOWN])
    steps += [["capture", 2850, "clear-design"], ["press", 2900, A], ["capture", 3100, "erase-prompt"],
              ["press", 3150, A], ["capture", 3700, "erased"]]
    # From the Design Creator menu one B fewer reaches the Paint Shop menu.
    steps += [["press", 3850, "2000"], ["press", 4150, "2000"], ["capture", 4400, "leave-prompt"], ["press", 4450, A]]
    frame = drive_and_look(steps, 5400)
    steps.append(["stop", frame + 30])
    return steps


# -- routes -----------------------------------------------------------------

def _shifted(step: list) -> list:
    kind = step[0]
    out = [kind]
    for index, value in enumerate(step[1:], 1):
        shift = index == 1 or (index == 2 and kind in ("wait", "captures"))
        out.append(value + SETTLE if shift and isinstance(value, int) else value)
    return out


def render(steps: list, comments: list[str]) -> str:
    """A route: the start (A presses through the menus, also at frames 1000-1300, which a modded
    profile needs and an unmodded one ignores), a wait for free roam, then the steps in frame order."""
    lines = [HEADER, *comments, "input 0 0000 0 0 0 0 0 0"]
    for frame in (360, 480, 600, 720, 1000, 1150, 1300):
        lines += [f"input {frame} 1000 0 0 0 0 0 0", f"input {frame + 6} 0000 0 0 0 0 0 0"]
    lines += ["wait 1400 4000 freeroam", "capture 1700 free-roam"]
    events = []
    for step in map(_shifted, steps):
        kind = step[0]
        if kind == "input":
            _, frame, buttons, lt, rt, lx, ly, *right = step
            rx, ry = (right + [0, 0])[:2]
            events.append((frame, 0, f"input {frame} {buttons} {lt} {rt} {lx} {ly} {rx} {ry}"))
        elif kind == "press":
            _, frame, buttons = step
            events.append((frame, 0, f"input {frame} {buttons} 0 0 0 0 0 0"))
            events.append((frame + 6, 0, f"input {frame + 6} 0000 0 0 0 0 0 0"))
        elif kind == "wait":
            _, frame, most, condition, *argument = step
            events.append((frame, 0, " ".join(["wait", str(frame), str(most), condition, *map(str, argument)])))
        elif kind == "capture":
            events.append((step[1], 1, f"capture {step[1]} {step[2]}"))
        elif kind == "captures":
            _, first, last, every, prefix = step
            for n, frame in enumerate(range(first, last + 1, every)):
                events.append((frame, 1, f"capture {frame} {prefix}{n:02d}"))
        elif kind == "stop":
            events.append((step[1], 2, f"stop {step[1]}"))
        else:
            raise ValueError(f"unknown route step {kind!r}")
    return "\n".join(lines + [text for _, _, text in sorted(events)]) + "\n"


def routes(recipe, make_presses: int, car_presses: int, kinds=KINDS[:4], cards: int = 8) -> dict[str, str]:
    """The route files (name -> text) for a livery recipe at its place in the Autoshow."""
    car = recipe.car
    trace = ["# The native DLC trace logs the title's entitlement and rows for the car and its stock car:",
             "# dlc-car-trace", f"# dlc-car-ids {car['new_id']},{car['stock_id']}"]
    seed = ("# Seed: a render seed of the .local/preview save (it spawns at Dak's Garage with enough credits) "
            "with the car installed by `tools/manage-fh1-dlc.py install-livery --recipe "
            f"config\\livery-cars\\{recipe.name}.json --state-root <seed> --game-root .local\\game\\eur-base`.")
    after_buy = (f"# Seed: the private state folder a run of fh1-promo-{recipe.name}-buy left (<output>.state); "
                 "the runner copies it again, so it is not written.")
    place = (f"# The Autoshow: pause, MAP, the cursor nudged onto it, Y fast travel, A; X enters; right {make_presses} "
             "times to the car's make, A")
    title = f"# livery car {car['new_id']} ({car['display_name']}, recipe {recipe.name}):"
    builders = {
        "list": (lambda: list_steps(make_presses, cards),
                 [f"{title} its make's cards in the Autoshow, to find its place.", seed, *trace,
                  f"{place}; then right along the list, a capture per card (card-00 to card-{cards - 1:02d})."]),
        "showroom": (lambda: showroom_steps(make_presses, car_presses),
                     [f"{title} its showroom in the Autoshow, from every side.", seed, *trace,
                      f"{place}; right {car_presses} times to the car, A: the showroom. The right stick orbits the "
                      "camera (41 captures) and a raised camera adds the rear (13 captures)."]),
        "buy": (lambda: buy_steps(make_presses, car_presses),
                [f"{title} buy it for credits and drive it in free roam.", seed, *trace,
                 f"{place}; right {car_presses} times to the car, A: the showroom; A: BUY; A: buy with credits; the "
                 "title saves (the wait is for the garage thumbnail it renders, a .xdc in the profile); A at the "
                 "\"return to free roam\" prompt. In free roam the throttle is held until the car has moved 15 m, "
                 "then the camera turns to each side. The run's .state folder seeds the reload and garage routes."]),
        "reload": (reload_steps,
                   [f"{title} reload the save the buy route left and drive the car again.", after_buy, *trace,
                    "# The player spawns outside the Autoshow in the car; the throttle is held until it has moved "
                    "15 m, then the camera turns to each side."]),
    }
    paint_note = ("# The Paint Shop's editor makes the renderer log draw failures (PM4_DRAW_INDX_2 ... Failed in "
                  "backend), which fail the runner's renderer-log check; the captures are complete.")
    builders |= {
        "garage": (garage_steps,
                   [f"{title} auto-upgrade it at Dak's Garage and drive it.", after_buy, *trace,
                    "# Pause, MAP, the cursor nudged onto Dak's Garage (map-garage shows its label), Y fast travel, "
                    "A; X opens the garage; Auto Upgrade, A on its explanation, A on the first class offered, A to "
                    "buy and install the parts (the title saves); B and A leave the garage. The HUD then shows the "
                    "new PI; the throttle is held until the car has moved 15 m and the camera turns to each side."]),
        "paint": (paint_steps,
                  [f"{title} repaint it at the Paint Shop and drive it.", after_buy, *trace,
                   "# Pause, MAP, the cursor nudged onto the Paint Shop (map-paint), Y fast travel, A; X; Design "
                   "Creator, Paint Car, Paint Body; a colour five steps right, A; Start saves, A to the current car; "
                   "B three times and A leave the Paint Shop; then the car is driven. A saved repaint replaces the "
                   "livery. The run's .state folder seeds paint-clear.", paint_note]),
        "paint-clear": (paint_clear_steps,
                        [f"{title} clear the repaint at the Paint Shop, which brings the livery back.",
                         f"# Seed: the private state folder a run of fh1-promo-{recipe.name}-paint left (<output>.state).",
                         *trace,
                         "# X at the Paint Shop; Design Creator, down five times to Clear Design, A, A to erase the "
                         "paint and decals (the title saves); B twice and A leave the Paint Shop; then the car is "
                         "driven.", paint_note]),
    }
    unknown = sorted(set(kinds) - set(builders))
    if unknown:
        raise ValueError(f"no route kind {unknown[0]!r} (known: {', '.join(builders)})")
    return {f"fh1-promo-{recipe.name}-{kind}.fh1test": render(builders[kind][0](), builders[kind][1]) for kind in kinds}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--recipe", type=Path, required=True, help="the livery recipe (config/livery-cars/)")
    parser.add_argument("--make-presses", type=int, required=True, help="presses right to the car's make")
    parser.add_argument("--car-presses", type=int, required=True, help="presses right along the make's list to the car")
    parser.add_argument("--kinds", default=",".join(KINDS[:4]), help=f"comma-separated, of {', '.join(KINDS)}")
    parser.add_argument("--cards", type=int, default=8, help="list: how many cards to capture")
    parser.add_argument("--output", type=Path, default=ROOT / "config/render-tests")
    parser.add_argument("--panels", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--ids", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.make_presses < 0 or args.car_presses < 0 or args.cards < 1:
            raise ValueError("presses must be 0 or more and cards at least 1")
        paint = _load_tool("paint-fh1-livery")
        recipe = paint.load_recipe(args.recipe, panel_tables=args.panels or paint.PANEL_TABLES,
                                   id_table=args.ids or paint.ID_TABLE, require_art=False)
        written = routes(recipe, args.make_presses, args.car_presses, [k for k in args.kinds.split(",") if k], args.cards)
        args.output.mkdir(parents=True, exist_ok=True)
        for name, text in written.items():
            (args.output / name).write_bytes(text.encode())
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    for name in written:
        print(args.output / name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
