#pragma once

namespace pinyon_shift::hostui {

// Whether the host UI swallows a key release. A key pressed before the UI
// opened (the A that chose the guest's Achievements entry, say) went down in
// the guest's keyboard emulation; its release must reach that emulation too,
// or the guest keeps the key held and chooses the same entry again as soon as
// the UI closes. Function keys are keybinds and always pass.
constexpr bool ConsumesKeyRelease(bool open, bool pressed_while_open, bool function_key) {
  return open && pressed_while_open && !function_key;
}

}  // namespace pinyon_shift::hostui
