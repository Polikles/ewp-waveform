# Bounded portable Vulkan qualification — 2026-11-13

This is opt-in backend evidence, not production GPU admission, a performance
result, a native-Windows GPU pass, or NLE/visual acceptance. Existing probe
modules and production defaults are unchanged.

## Interface and independence

`ewp_waveform.ffmpeg.backend_qualification.qualify(ffmpeg, ffprobe, root,
device="RTX 3090", expected=r"RTX\s*3090")` returns independent `transfer`,
`blur`, `prores`, and `ffv1` objects with `status`, `cases`, and explanatory
`evidence`. The supplied evidence root must be empty. Each attempted external
command retains exact argv, process return code, full stderr, diagnostic excerpts,
and output/input byte counts and SHA256. Failed commands never abort unrelated
backends, CPU controls, formats, or geometries.

Statuses distinguish `PASS`, `CAPABILITY_UNAVAILABLE`, `EXECUTION_ERROR`,
`NUMERICAL_MISMATCH`, and `DEVICE_MISMATCH`. Missing components are determined
from exact inventory tokens. Device absence requires both an explicit FFmpeg
name-selection refusal and successful loader enumeration without matching
hardware. Numeric errors, including `-38`, are not absence evidence.

The selected-device parser accepts both `Using device:` and actual
`Device 0 selected:` diagnostics. Device listings alone do not establish
selection; all selected devices must match the expected expression, and software
renderers are rejected. This parser is local to the new qualifier; old adapters
are intentionally not changed in this author slice.

Bounds and oracles:

- Two frames at 60/1 FPS, each of 64x32 and 1400x280.
- Every-byte matching-format upload/download checks for gray, RGBA, BGRA, and
  yuva444p10le, including alpha, transparent hidden RGB, and distinct frames.
- Independent NumPy float64 separable sigma16/size97 Gaussian oracle, normalized
  Simpson-integrated taps, clamp edges, and intermediate/final R8 quantization.
  The predeclared descriptive screen is maximum two 8-bit codes and mean
  absolute error 0.6 codes; it is not production appearance equivalence.
- FFV1 must decode losslessly in BGRA, including transparent hidden RGB, with
  correct codec, geometry, frame count, FPS, and PTS grid.
- ProRes4444 must carry alpha, satisfy the timing grid, and preserve every alpha
  sample within one input 10-bit quantization step. Alpha is not declared a
  lossless RGB oracle for this lossy codec.
- CPU codec controls execute using the selected FFmpeg, not a different system
  build. The actual selected FFmpeg/FFprobe version and configuration are compared.
- Each external command has a 45-second deadline. Temporary codec files stay
  under the owned root and are removed after validation; no binary media is
  written into Git or retained as textual evidence.

## Actual read-only device diagnostic

`ewp_waveform.ffmpeg.vulkan_diagnostic.collect(root)` uses the Vulkan loader C
ABI in a disposable, 30-second subprocess on Linux or Windows. It captures actual
loader/device API versions, driver identity, complete device extension lists,
relevant core features, legacy and 64-bit FormatProperties3 flags, and actual
image format/tiling/usage-combination query results and limits. It also captures
`/etc/os-release` when present and relevant loader-selection environment values.
No SDK, vulkaninfo install, optional binding, or stack repair is required.

The diagnostic records the WSL/dzn explanation as **UNCONFIRMED**, including
whether the actual driver properties identify dzn. Selection of an RTX device,
a dzn warning, or an autoscale `-38` alone cannot identify the failing layer.
Format/usage support, API/extensions, selected device, exact graph, and actual
failure stage must be compared on the operator's host.

Primary FFmpeg 9.0.2 source observations:

- `libavutil/hwcontext_vulkan.c` requests Vulkan 1.3. Its format selection checks
  sampled-image and transfer-source/destination features, plus storage support
  when required by the frames context.
- Both RGBA and BGRA map to `VK_FORMAT_R8G8B8A8_UNORM`; do not mistake the
  spelling BGRA for proof that `VK_FORMAT_B8G8R8A8_UNORM` is used. Planar 10-bit
  alpha formats use R16 images for individual planes.
- `libavfilter/vf_gblur_vulkan.c` constructs normalized Simpson-integrated Gaussian
  taps, executes two passes, and requires a compute queue.
- These source observations do not qualify an arbitrary installed build or
  establish which capability caused an operator failure.

Primary sources are the FFmpeg project source archive/tag, FFmpeg download page,
Khronos Vulkan-Docs format/capability chapters, and Vulkan-Headers definitions.
Exact retrieved responses are retained in the external evidence root below.
The rendered Vulkan documentation endpoints returned HTTP403 here; the primary
Khronos GitHub source was fetched instead. The FFmpeg per-archive `.sha256` URL
returned HTTP404; its source archive hash is a locally observed digest, not a
claim that an official checksum/signature was verified.

## Frozen native-Windows acquisition

The official FFmpeg download page, retrieved directly on 2026-11-13, names
9.0.2 (released 2026-09-18) as its latest stable release and links BtbN as a
third-party Windows binary provider. The retained provider monthly build is
frozen in `src/ewp_waveform/ffmpeg/portable_ffmpeg_lock.json`:

- Release: `autobuild-2026-10-31-12-59`.
- Exact build: `n9.0.2-39-g7adfbe40dc-20261031`, shared Win64 GPL.
- Source commit observed through the FFmpeg project API:
  `7adfbe40dcde598f93a6963d2f7b22cd75202ccc`.
- Asset: `ffmpeg-n9.0.2-39-g7adfbe40dc-win64-gpl-shared-9.0.zip`.
- Download size: 85,920,857 bytes.
- SHA256 verified against the provider release asset digest:
  `1d9823c35c7a7e2f54d1438cf61030d6efabe3278de01c191309d1e828bb74df`.
- All ten executable/DLL payload hashes are frozen. All are actual PE x86-64.
  The avutil DLL embeds the exact build version, avcodec contains all requested
  CPU/Vulkan codec identifiers, avfilter contains all requested filter
  identifiers, and the embedded build configuration enables Vulkan.

The initially investigated November 13 daily build is preserved as supplemental
research, **not** the selected lock. The provider's README says only 14 daily
builds are retained, versus two years for monthly builds; therefore the retained
October monthly asset was selected. Missing/changed assets fail closed, never
upgrade to `latest`. A dated provider URL is not a promise of permanent hosting.

`acquire_windows(root, allow_download=True)` performs isolated, explicit-opt-in
HTTPS acquisition, SHA/size verification, bounded safe ZIP extraction, and exact
read-back verification of the installed EXE/DLL set. It rejects traversal,
absolute/drive paths, symlinks, Windows reserved names, case collisions, oversized
archives, changed binaries, and injected DLLs. It neither changes PATH nor
installs system components. It returns absolute same-directory `ffmpeg` and
`ffprobe` paths for the driver, which can expose this as `--prepare-ffmpeg`.

Standalone acquisition:

```text
python -m ewp_waveform.ffmpeg.portable_tools --root <isolated-tools-root> --acquire
```

**Binary identity and embedded names are not executable inventory or runtime
qualification.** Native-Windows `-encoders`/`-filters`, same-build CPU controls,
actual selected-device evidence, and each bounded runtime oracle remain required.
Acquisition receipts explicitly say `PENDING_NATIVE_WINDOWS_EXECUTION`.

## Author execution evidence

External root:
`/home/linuch/waveform-browser-work/analysis/ewp-portable-20261113T175616Z-24bef4b7/probes-author-r01`.

- `author-gates.json`: lint and strict full-project typecheck passed; unit and
  regression tests **1598 passed, 13 skipped**; integration **186 passed, 2
  skipped**. Existing skips identify absent optional jsonschema and separately
  opted-in media suites; no dependency was installed to conceal them.
- `vm-run-02-final/qualification.json`: actual `/usr/bin/ffmpeg` and FFprobe
  8.0.1-3ubuntu2. Same-build control and all four CPU codec cases passed.
  Both ProRes alpha oracles were exact (maximum error 0); both FFV1 every-byte
  oracles were exact. The VM has no RTX hardware.
- Actual VM OS: Ubuntu 26.04.1 LTS. Loader API 1.4.341; device
  `llvmpipe (LLVM 21.1.8, 256 bits)`, API 1.4.335, Mesa 26.0.8-1ubuntu0.3.
  This is VM evidence, not confirmation of the operator's reported OS version.
- Transfer, blur, and FFV1 cases report device capability unavailable with actual
  name-refusal plus loader evidence. ProRes Vulkan reports encoder unavailable
  in the selected VM build. All-backends-passed is false. No software fallback.
- `windows-monthly-acquisition.json` and `windows-monthly-reuse.json`: the actual
  frozen archive was downloaded, extracted, hash-verified, then independently
  re-read/reused without downloading. This transport test ran on Linux; Windows
  binary execution and native RTX runtime qualification remain pending.
- `windows-monthly-identity.json`: actual PE machines, embedded version, and source
  commit evidence. `windows-monthly-binary-evidence.json`: downloaded payload and
  embedded encoder/filter/build-configuration observations.
- `vm-run-01` is preserved as an earlier iteration, superseded by the final run;
  no historical evidence was rewritten to change its statuses.

The actual operator WSL dzn device capabilities have not been collected here.
No dzn root cause or native-Windows complete codec matrix is claimed.
