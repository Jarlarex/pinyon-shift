#pragma once

#include <cstddef>
#include <cstdint>

namespace pinyon_shift::dlc {

// The offline token service (pinyon_shift_dlc_tokens, title update v4). Called
// with each secure file the title loads or saves: for the profile, the open
// save's folder becomes the one whose Token balance is used.
void NoteTokenSave(const uint8_t* body, size_t size);

// True when the service answers for the title and `caller` (a return address)
// is the token store's own "Forza server available" check, which then passes.
bool TokenStoreServerCheck(uint32_t caller);

}  // namespace pinyon_shift::dlc
