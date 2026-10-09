#pragma once

#include <cstdint>

namespace pinyon_shift::dlc {

// The offline token service (pinyon_shift_dlc_tokens, title update v4). True
// when the service answers for the title and `caller` (a return address) is
// the token store's own "Forza server available" check, which then passes.
bool TokenStoreServerCheck(uint32_t caller);

}  // namespace pinyon_shift::dlc
