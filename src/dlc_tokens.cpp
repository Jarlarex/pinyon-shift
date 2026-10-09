#include "dlc_tokens.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <string>
#include <utility>

#include <fmt/format.h>
#include <toml++/toml.hpp>

#include <rex/cvar.h>
#include <rex/memory.h>
#include <rex/ppc/context.h>
#include <rex/system/kernel_state.h>
#include <rex/system/xam/content_manager.h>
#include <rex/system/xam/user_profile.h>
#include <rex/system/xmemory.h>

#include "fh1_guest_address.h"
#include "mod/mod_host.h"
#include "pinyon_shift_diagnostics.h"
#include "save/profile_body.h"

REXCVAR_DEFINE_INT32(pinyon_shift_dlc_tokens, 100, "Pinyon Shift",
                     "Tokens each save starts with in the offline token store (title update "
                     "v4): the in-game marketplace's Treasure Map, Popularity Spikes and other "
                     "token items can be bought with them. What is left is kept in the save's "
                     "folder across restarts; a different amount starts every save again from "
                     "it. -1 leaves the store offline")
    .range(-1, 999999)
    .lifecycle(rex::cvar::Lifecycle::kHotReload);

// Tokens were Forza asset 888, counted and spent by Turn 10's web service
// (Forza.WebServices.User), now gone. v4's Forza::CConsumableAssetManager
// ([0x833F4A88], built by sub_82925E08) does both:
// - EnumerateAssets, sub_82922368(manager, user, &request, 4), enumerates the
//   Live Marketplace assets (event 5, sub_82925F78), sends
//   GetForzaAssetCounts (sub_82B6CD40) with the 16 {asset, count} pairs at
//   manager+12 (count at +140), and on the answer (sub_82924FC8) posts system
//   event 21 with a CSystemEventParamAssetList. Its one listener,
//   ForzaUI::CCarTokenEnumerator (vtable 0x820331D4, sub_82680A80), keeps
//   +4 request pending (u8), +8 the asset 888 count (the balance) and +12
//   counts known (u8; 0 after a failed request). Every token screen owns one
//   and asks for counts through its Refresh, sub_826747D8, which needs a LIVE
//   user with the purchase privilege (user vtable +196).
// - ConsumeAsset, sub_829224F0(manager, user, 888, price, transaction), gets
//   the asset's count (GetForzaAssetCount, task ConsumeAssetTask, success
//   sub_829292A8), sends TwoPhaseConsumeForzaAsset (sub_82B6D040) and, on its
//   answer (sub_82926188), completes the CConsumableAssetManager::ITransaction
//   through vtable +28 with 0 (paid), 0x80514501 (too few Tokens) or another
//   error; the shared completion sub_829156E8 sets the transaction's state
//   (+8) to 0, 1 or 3 from that. It is 2 while pending. Both requests stop at
//   once while sub_824127B8 says the Forza server is unavailable.
// The token store is ForzaUI::CConsumableHelper (the pause map's Treasure Map,
// the Popularity Spike, the Rally All Access Pass and Fast Travel popups).
// Its offer, sub_82681698(helper, item, price, extra), first checks the LIVE
// user (sub_82753C68, which shows "sign in" itself on failure) and the server
// (sub_824127B8), copies the enumerator's balance to helper+376 and offers
// the item ("Current Tokens: {1}") or says there are too few Tokens. On yes it
// builds the item's transaction (helper vtable +224) and calls ConsumeAsset;
// a popup (sub_826777E8) waits until the transaction leaves state 2 or 60 s
// pass, then the helper (sub_826844A0, message 4) takes the price off +376,
// grants the item through the transaction's own completion and saves. The
// Sponsor Challenges screen's RT BUY POPULARITY SPIKE (sub_8283DF18) makes the
// same two checks before its duration popup (30, 60 or 120 minutes for 1, 2
// or 3 Tokens, sub_825537B8) leads to the offer; the Treasure Map costs 5
// (sub_82988028).
//
// With the setting on the host is that service: the enumerator's Refresh
// reports the host balance, those checks pass for the token store's callers
// only, and ConsumeAsset for Tokens is answered on the next frame through the
// transaction's completion, as the service's answer was. What is left is kept
// in pinyon_shift_tokens.toml in the save's own ForzaProfile folder (beside
// the Rally progress), so a new save starts from the setting and a restored
// save brings its balance back; the encrypted profile never held one.
namespace {

namespace diagnostics = pinyon_shift::diagnostics;

constexpr uint32_t kTokenAsset = 888;
constexpr uint32_t kEnumeratorVtable = 0x820331D4u;
constexpr uint32_t kEnumeratorPending = 4;
constexpr uint32_t kEnumeratorBalance = 8;
constexpr uint32_t kEnumeratorKnown = 12;
constexpr uint32_t kHelperPrice = 380;
constexpr uint32_t kHelperItem = 388;
constexpr uint32_t kTransactionState = 8;
constexpr uint32_t kTransactionPending = 2;
constexpr uint32_t kTransactionRelease = 12;   // vtable slot
constexpr uint32_t kTransactionComplete = 28;  // vtable slot, r4 the result
constexpr uint32_t kNotEnoughTokens = 0x80514501u;
constexpr uint32_t kServiceError = 0x80500001u;
// Return addresses of the token store's own checks: the offer
// (sub_82681698); the Sponsor Challenges screen's RT BUY POPULARITY SPIKE
// (CSponsorChallenge input, sub_8283DF18), which shows "FEATURE UNAVAILABLE"
// before reaching the offer; and a car bought for Tokens in the garage flows
// (ForzaUI::CPopupsGarageFlows): the buy prompt (sub_82682E30), the Token
// confirmation that compares the balance with the car's price (sub_82683BF0)
// and the purchase itself (sub_8267B0C0 with r4 = 1, "servers not
// available" on failure). Buying more Tokens (sub_826789B0, sub_82677750)
// stays offline.
constexpr std::array<uint32_t, 3> kSigninCallers = {0x826816D8u, 0x8283DFD0u, 0x82683C14u};
constexpr std::array<uint32_t, 5> kServerCallers = {0x826816ECu, 0x8283DFB4u, 0x82682E78u,
                                                    0x82683C28u, 0x8267B0E8u};

template <size_t N>
bool TokenStoreCaller(const std::array<uint32_t, N>& callers, uint32_t caller) {
  return std::find(callers.begin(), callers.end(), caller) != callers.end();
}

struct Wallet {
  std::filesystem::path path;  // pinyon_shift_tokens.toml in the save's folder
  bool loaded = false;
  int64_t start = -1;  // the setting the balance was started from
  int64_t balance = 0;
};

std::mutex g_wallet_mutex;
Wallet g_wallet;

bool Active() {
  if constexpr (!pinyon_shift::fh1::kTitleUpdateV4) return false;
  return REXCVAR_GET(pinyon_shift_dlc_tokens) >= 0;
}

// The open profile save's folder (user/<xuid>/4D5309C9/00000001/ForzaProfile),
// as the Rally progress finds it; empty while the title has none open.
std::filesystem::path OpenProfileFolder() {
  auto* kernel = rex::system::kernel_state();
  if (!kernel || !kernel->content_manager() || !kernel->user_profile()) return {};
  auto folder = kernel->content_manager()->GetOpenPackagePath(
      fmt::format("{:016X}", kernel->user_profile()->xuid()));
  return folder.filename() == "ForzaProfile" ? folder : std::filesystem::path{};
}

// Switches to the balance of the save in `folder`. Called with g_wallet_mutex
// held.
void UseProfileFolder(const std::filesystem::path& folder) {
  auto path = folder / "pinyon_shift_tokens.toml";
  if (path == g_wallet.path) return;
  g_wallet = Wallet{};
  g_wallet.path = std::move(path);
}

void SaveWallet(const Wallet& wallet) {
  const auto& path = wallet.path;
  const auto temporary = path.string() + ".tmp";
  std::error_code error;
  {
    std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
    output << "# Pinyon Shift's offline Token balance (pinyon_shift_dlc_tokens).\n"
           << "version = 1\n"
           << "start = " << wallet.start << "\n"
           << "balance = " << wallet.balance << "\n";
    if (!output.flush()) error = std::make_error_code(std::errc::io_error);
  }
  if (!error) std::filesystem::rename(temporary, path, error);
  if (error) {
    diagnostics::RecordEvent("dlc.tokens.save_error",
                             {{"path", path.string()}, {"error", error.message()}});
  }
}

// The balance of the open save for the current setting, loading the saved one
// first; -1 while the service is off or no save is open. A save without one,
// or with one started from another setting, starts from the setting. Called
// with g_wallet_mutex held.
int64_t Balance() {
  if (!Active()) return -1;
  if (g_wallet.path.empty()) {
    const auto folder = OpenProfileFolder();
    if (folder.empty()) {
      static bool logged = false;
      if (!std::exchange(logged, true)) diagnostics::RecordEvent("dlc.tokens.no_save");
      return -1;
    }
    UseProfileFolder(folder);
  }
  const int64_t configured = REXCVAR_GET(pinyon_shift_dlc_tokens);
  if (!g_wallet.loaded) {
    g_wallet.loaded = true;
    const auto& path = g_wallet.path;
    std::error_code error;
    if (std::filesystem::exists(path, error)) {
      try {
        const auto table = toml::parse_file(path.string());
        const auto start = table["start"].value<int64_t>();
        const auto balance = table["balance"].value<int64_t>();
        if (table["version"].value<int64_t>() == 1 && start && balance && *balance >= 0) {
          g_wallet.start = *start;
          g_wallet.balance = *balance;
        }
      } catch (const toml::parse_error& parse) {
        diagnostics::RecordEvent("dlc.tokens.load_error",
                                 {{"path", path.string()}, {"error", std::string(parse.description())}});
      }
    }
    diagnostics::RecordEvent("dlc.tokens.wallet",
                             {{"action", "loaded"},
                              {"start", fmt::format("{}", g_wallet.start)},
                              {"balance", fmt::format("{}", g_wallet.balance)},
                              {"path", path.string()}});
  }
  if (g_wallet.start != configured) {
    g_wallet.start = configured;
    g_wallet.balance = configured;
    SaveWallet(g_wallet);
    diagnostics::RecordEvent("dlc.tokens.wallet",
                             {{"action", "started"}, {"balance", fmt::format("{}", configured)}});
  }
  return g_wallet.balance;
}

int64_t CurrentBalance() {
  std::lock_guard lock(g_wallet_mutex);
  return Balance();
}

bool Readable(uint32_t address, uint32_t size) {
  if (address == 0 || size == 0 || address + size - 1u < address) return false;
  auto* memory = rex::system::kernel_state()->memory();
  return rex::memory::IsHostReadable(memory->TranslateVirtual(address)) &&
         rex::memory::IsHostReadable(memory->TranslateVirtual(address + size - 1u));
}

uint32_t Load32(uint32_t address) {
  auto* base = rex::system::kernel_state()->memory()->virtual_membase();
  return static_cast<uint32_t>(*rex::memory::GuestPtr<rex::be_u32*>(base, address));
}

void Store32(uint32_t address, uint32_t value) {
  auto* base = rex::system::kernel_state()->memory()->virtual_membase();
  *rex::memory::GuestPtr<rex::be_u32*>(base, address) = value;
}

void Store8(uint32_t address, uint8_t value) {
  auto* base = rex::system::kernel_state()->memory()->virtual_membase();
  *rex::memory::GuestPtr<uint8_t*>(base, address) = value;
}

// Fills a CCarTokenEnumerator as a successful count request does. False for
// anything else.
bool ReportBalance(uint32_t enumerator, int64_t balance) {
  if (!Readable(enumerator, kEnumeratorKnown + 1) || Load32(enumerator) != kEnumeratorVtable) {
    return false;
  }
  Store8(enumerator + kEnumeratorPending, 0);
  Store32(enumerator + kEnumeratorBalance, static_cast<uint32_t>(balance));
  Store8(enumerator + kEnumeratorKnown, 1);
  return true;
}

// On the title's main thread, a frame after ConsumeAsset: pays for the
// transaction from the balance and completes it as the service's answer did,
// then drops the reference ConsumeAsset was given.
void CompleteConsume(uint32_t transaction, uint32_t price) {
  const uint32_t vtable = Readable(transaction, kTransactionState + 4) ? Load32(transaction) : 0;
  if (!vtable || !Readable(vtable + kTransactionComplete, 4)) {
    diagnostics::RecordEvent("dlc.tokens.consume",
                             {{"action", "lost"}, {"transaction", fmt::format("{:08X}", transaction)}});
    return;
  }
  int64_t before = 0, after = 0;
  uint32_t result = kServiceError;
  {
    std::lock_guard lock(g_wallet_mutex);
    before = Balance();
    if (before >= 0) {
      result = before >= price ? 0u : kNotEnoughTokens;
      if (result == 0) {
        g_wallet.balance -= price;
        SaveWallet(g_wallet);
      }
    }
    after = before >= 0 ? g_wallet.balance : -1;
  }
  pinyon_shift::mod::CallGuest(Load32(vtable + kTransactionComplete), {transaction, result});
  pinyon_shift::mod::CallGuest(Load32(vtable + kTransactionRelease), {transaction});
  diagnostics::RecordEvent(
      "dlc.tokens.consume",
      {{"action", result == 0 ? "paid" : result == kNotEnoughTokens ? "too_few" : "service_off"},
       {"price", fmt::format("{}", price)},
       {"balance_before", fmt::format("{}", before)},
       {"balance_after", fmt::format("{}", after)},
       {"state", fmt::format("{}", Load32(transaction + kTransactionState))}});
}

}  // namespace

namespace pinyon_shift::dlc {

void NoteTokenSave(const uint8_t* body, size_t size) {
  if constexpr (!fh1::kTitleUpdateV4) return;
  // Other secure files pass through here too; only the profile has Main.
  if (!body || !save::FindProfileField(body, size, "Main/Credits")) return;
  const auto folder = OpenProfileFolder();
  if (folder.empty()) return;
  std::lock_guard lock(g_wallet_mutex);
  UseProfileFolder(folder);
}

bool TokenStoreServerCheck(uint32_t caller) {
  if (!TokenStoreCaller(kServerCallers, caller) || !Active()) return false;
  diagnostics::RecordEvent("dlc.tokens.gate",
                           {{"check", "server"}, {"caller", fmt::format("{:08X}", caller)}});
  return true;
}

}  // namespace pinyon_shift::dlc

// Entry of CCarTokenEnumerator::Refresh (sub_826747D8, r3 the enumerator):
// reports the host balance at once instead of requesting the counts.
bool PinyonShiftTokenRefresh(PPCRegister& r3) {
  if (!Active()) return false;
  const int64_t balance = CurrentBalance();
  if (balance < 0 || !ReportBalance(r3.u32, balance)) return false;
  diagnostics::RecordEvent("dlc.tokens.balance", {{"balance", fmt::format("{}", balance)}});
  return true;
}

// sub_82681698 at 0x826818DC, where the offer tests the enumerator (r11) for
// known counts and then copies its balance: the balance is the host's at that
// moment, however long the screen has been open. r24 is the helper.
void PinyonShiftTokenOffer(PPCRegister& r11, PPCRegister& r24) {
  if (!Active()) return;
  const int64_t balance = CurrentBalance();
  if (balance < 0 || !ReportBalance(r11.u32, balance)) return;
  const bool helper = Readable(r24.u32 + kHelperPrice, kHelperItem - kHelperPrice + 4);
  diagnostics::RecordEvent("dlc.tokens.offer",
                           {{"item", helper ? fmt::format("{}", Load32(r24.u32 + kHelperItem)) : ""},
                            {"price", helper ? fmt::format("{}", Load32(r24.u32 + kHelperPrice)) : ""},
                            {"balance", fmt::format("{}", balance)}});
}

// Entry of sub_82753C68(screen, item), the LIVE sign-in and privilege check
// that shows its own failure popup: passes for the token store's calls only.
bool PinyonShiftTokenStoreSignin(PPCRegister& r3, uint64_t& lr) {
  if (!TokenStoreCaller(kSigninCallers, uint32_t(lr)) || !Active()) return false;
  diagnostics::RecordEvent("dlc.tokens.gate",
                           {{"check", "signin"}, {"caller", fmt::format("{:08X}", uint32_t(lr))}});
  r3.u64 = 1;
  return true;
}

// Entry of CConsumableAssetManager::ConsumeAsset (sub_829224F0; r5 the asset,
// r6 the price, r7 the transaction's smart pointer, passed by value). For
// Tokens the transaction is marked pending, as the consume task marks it, and
// answered from the balance on the next frame. Skipping the body leaves the
// argument's reference for that answer to release.
bool PinyonShiftTokenConsume(PPCRegister& r5, PPCRegister& r6, PPCRegister& r7) {
  if (r5.u32 != kTokenAsset || !Active() || !Readable(r7.u32, 4)) return false;
  const uint32_t transaction = Load32(r7.u32);
  if (!Readable(transaction, kTransactionState + 4)) return false;
  const uint32_t price = r6.u32;
  Store32(transaction + kTransactionState, kTransactionPending);
  diagnostics::RecordEvent("dlc.tokens.consume",
                           {{"action", "requested"}, {"price", fmt::format("{}", price)}});
  pinyon_shift::mod::EnqueueHostGuestTask([transaction, price] { CompleteConsume(transaction, price); });
  return true;
}
