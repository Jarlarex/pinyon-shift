# Third-party notices

Pinyon Shift downloads the following third-party projects during local setup.
Their own licenses apply; they are not relicensed by this repository.

- [ReXGlue SDK](https://github.com/rexglue/rexglue-sdk)
- [LLVM](https://github.com/llvm/llvm-project)
- [extract-xiso](https://github.com/XboxDev/extract-xiso)
- [Git for Windows](https://github.com/git-for-windows/git)
- [Microsoft Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)

Exact versions, source URLs, and archive hashes are recorded in
`config/release-toolchain.json`. ReXGlue's transitive dependencies are fetched
by its pinned source tree and retain their upstream notices.

## Title update

When a supported disc is a verified base of the Forza Horizon v4 title update
(Microsoft's free update for owners of the game), setup and the launcher
download that update package from the sources in
`config/title-update-sources.json` (currently xboxunity.net). It is used only
if its size and SHA-256 match `config/supported-title-updates.json`
(15,728,640 bytes, `CC49029A…9112`). It is stored only in the player's local
state, never in this repository, and remains Microsoft's copyrighted work.
