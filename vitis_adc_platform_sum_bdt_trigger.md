# Four-Channel Sum Threshold and BDT Trigger

This note documents the current trigger implementation for the RFSoC four-stream
ADC kernel. The kernel has a BDT score path based on `csi_bdt_prj_kv260`, with
the BDT score printed by the host but not yet used for event selection.

Default event selection is:

```cpp
external PPS rising edge
```

The host can optionally add a runtime sum veto or sum trigger. The BDT output
remains diagnostic readout for board testing.

## Source Files

Tracked integration files:

- `src/vitis_adc_platform/dummy_kernel.cpp`
- `src/vitis_adc_platform/host.cpp`
- `src/vitis_adc_platform/bdt_sum_trigger_conifer.h`
- `src/vitis_adc_platform/bdt_feature_indices.h`
- `src/vitis_adc_platform/export_bdt_headers.py`
- `vitis_adc_platform_sum_bdt_trigger.md`

Tracked generated BDT firmware used by the HLS build:

- `csi_bdt_prj_kv260/firmware/BDT.h`
- `csi_bdt_prj_kv260/firmware/BDT.cpp`
- `csi_bdt_prj_kv260/firmware/parameters.h`

Do not add `csi_bdt_kv260.cpp` to this kernel build. Its generated top wrapper
has an inconsistent prototype and is not needed. The RFSoC kernel calls
`bdt.decision_function(features, score)` directly.

`bdt_sum_trigger_conifer.h` includes `BDT.cpp` by default so the generated
`tree_scores()` specialization is visible to HLS even when Vitis Classic only
compiles `dummy_kernel.cpp` as the kernel source. If `BDT.cpp` is explicitly
added as a separate HLS source, define `BDT_TREE_SCORES_EXTERNAL=1` to avoid a
duplicate definition.

## Trigger Flow

Each stream word is 32 bits, containing two signed 16-bit samples. The kernel
reads ADC_D, ADC_C, ADC_B, ADC_A, and `PPS_TRIG_AXIS` in lockstep.

For every stream word, the acquisition loop:

1. Packs the four raw ADC words into the 128-bit waveform ring buffer.
2. Sign-extends both lanes from all four channels.
3. Computes `sum_sample = ADC_D + ADC_C + ADC_B + ADC_A` for each lane.
4. Marks the word over threshold if any lane has
   `sum_sample >= sum_threshold`.
5. Maintains `over_threshold_ring[8192]` and `over_threshold_count`.
6. Computes the two-lane average of the sum waveform.
7. Stores that average beside the raw word in
   `word_average_buffer[8192]`.

The max-threshold tracking and average-buffer writes run inside the same
pipelined capture loop as the waveform ring-buffer write.

When the PPS candidate completes, the runtime `sum_gate_mode` selects one of:

```text
disabled: accept the complete PPS candidate
veto:     accept only when over_threshold_count == 0
require:  accept only when over_threshold_count != 0
```

For accepted candidates in the real-BDT build, the kernel uses a generated
capture-word map to read the 250 selected features directly from the
trigger-aligned `word_average_buffer`. The dual-port BRAM supplies two features
per cycle, so the gather takes 125 pipelined iterations. The kernel then
calculates the BDT score before starting the 8192-word waveform write to DDR.
Thus identical accepted capture buffers always produce identical BDT feature
vectors, and the score is available inside the PL without waiting for the
26.7-us waveform transfer. The existing metadata word remains after the
waveform, so the host interface and printed output are unchanged. If a sum
gate rejects a candidate, it is discarded internally and the kernel waits for
the next PPS candidate.

## BDT Modes

The kernel has two score implementations:

- Default build: dummy BDT score. This keeps the previously tested fallback path.
- `USE_CONIFER_BDT` build: real Conifer BDT score from `csi_bdt_prj_kv260`.

The real BDT path:

1. Reads the 250 selected feature indices from `bdt_feature_indices.h`.
2. Uses their generated 8192-word capture addresses to gather two features per
   cycle from the trigger-aligned sum-waveform buffer.
3. Applies optional z-score preprocessing from `bdt_norm_config.h`.
4. Calls `bdt.decision_function(features, score)`.
5. Packs `score[0]` as signed fixed-point raw bits.

The generated BDT uses `ap_fixed<18,8>`, so the host prints:

```cpp
score = raw / 1024.0;
```

because there are 10 fractional bits.

## Feature and Normalization Headers

Generate the selected feature index header from the BDT project:

```shell
python3 src/vitis_adc_platform/export_bdt_headers.py \
  --top-feat-idx csi_bdt_prj_kv260/pynq_data/top_feat_idx.npy \
  --output-dir src/vitis_adc_platform
```

This writes `src/vitis_adc_platform/bdt_feature_indices.h` with 250 indices.

The BDT training script uses z-score normalized waveform samples:

```python
X = (X.astype(np.float32) - mu) / (sig + 1e-8)
```

If `ml_ready/norm_stats.npy` from the matching training run is available,
generate the normalization header:

```shell
python3 src/vitis_adc_platform/export_bdt_headers.py \
  --top-feat-idx csi_bdt_prj_kv260/pynq_data/top_feat_idx.npy \
  --norm-stats /path/to/ml_ready/norm_stats.npy \
  --output-dir src/vitis_adc_platform
```

Then build with `BDT_USE_NORM_CONFIG` defined. `norm_stats.npy` was not found
in the current `csi_bdt_prj_kv260` folder or in the original CsI hls4ml
training area, so the checked-in integration defaults to identity
preprocessing until that file is copied in.

## Output Buffer Layout

The kernel returns `8193` packed 128-bit words:

```text
buffer0[0..8191]  chronological four-channel waveform
buffer0[8192]     trigger/BDT metadata
```

Waveform word layout:

```text
bits [31:0]    ADC_D / RFDC_DATA_AXIS
bits [63:32]   ADC_C / RFDC_TRIG_AXIS
bits [95:64]   ADC_B / RFDC_ADC_B_AXIS
bits [127:96]  ADC_A / RFDC_ADC_A_AXIS
```

Metadata word layout:

```text
bits [31:0]  signed raw BDT score
bit  [32]    score valid flag
bit  [33]    real BDT flag: 1 = Conifer BDT, 0 = dummy fallback
```

The host allocates and migrates `8193` words, unpacks only the first `8192` words
into `wave.txt` or the Ethernet stream, and decodes `buffer0[8192]` separately.

## HLS Build Setup

For the dummy fallback build, no generated BDT firmware is required.

For the real BDT build, add these to the HLS kernel build:

- Include path: `src/vitis_adc_platform`
- Include path: `csi_bdt_prj_kv260/firmware`
- Make `BDT.cpp` available either in the kernel `src` folder or through the
  BDT firmware include path
- Compile define: `USE_CONIFER_BDT`
- Compile define: `BDT_USE_NORM_CONFIG` only when `bdt_norm_config.h` exists

For the Vitis 2025.2 command-line flow, these settings are already captured in
`src/vitis_adc_platform/dummy_kernel_hls_bdt_2025_2.cfg`. It produces
`build/vitis_dummy_kernel_2025_2/dummy_kernel_bdt.xo`, leaving the tested
dummy-score `.xo` untouched.

Example V++ compile options:

```text
-I<repo>/src/vitis_adc_platform
-I<repo>/csi_bdt_prj_kv260/firmware
-DUSE_CONIFER_BDT
```

Add this only after generating `bdt_norm_config.h`:

```text
-DBDT_USE_NORM_CONFIG
```

Keep the existing stream connectivity and clock settings unchanged:

```text
stream_connect = RFDC_DATA_AXIS:dummy_kernel_1.data_in
stream_connect = RFDC_TRIG_AXIS:dummy_kernel_1.trigger_in
stream_connect = RFDC_ADC_B_AXIS:dummy_kernel_1.adc_b_in
stream_connect = RFDC_ADC_A_AXIS:dummy_kernel_1.adc_a_in
stream_connect = PPS_TRIG_AXIS:dummy_kernel_1.ext_trigger_in
clock=307200000:dummy_kernel
```

## Workstation Vitis Update

These placeholders are used below; substitute the actual locations on the
build machine:

```text
<repo>: checkout of this rfsoc4x2 repository
<workspace>: Vitis workspace
<kernel project>: <workspace>/test_adc_kernels
<host project>: <workspace>/test_adc
<bdt project>: conifer BDT project (csi_bdt_prj_kv260)
```

Generate the feature-index header before copying files:

```shell
python3 <repo>/src/vitis_adc_platform/export_bdt_headers.py \
  --top-feat-idx <bdt project>/pynq_data/top_feat_idx.npy \
  --output-dir <repo>/src/vitis_adc_platform
```

Copy the kernel source and BDT interface files into the Vitis kernel project:

```shell
cp <repo>/src/vitis_adc_platform/dummy_kernel.cpp \
  <kernel project>/src/

cp <repo>/src/vitis_adc_platform/bdt_sum_trigger_conifer.h \
  <kernel project>/src/

cp <repo>/src/vitis_adc_platform/bdt_feature_indices.h \
  <kernel project>/src/

cp <bdt project>/firmware/BDT.cpp \
  <kernel project>/src/
```

`BDT.h` and `parameters.h` can stay in the BDT firmware folder if that folder
is added as an include path. Do not add or copy these generated top-wrapper
files into the RFSoC kernel project:

```text
csi_bdt_kv260.cpp
csi_bdt_kv260.h
```

Do not rely on the file existing on disk as proof that HLS compiles it. The
wrapper includes `BDT.cpp` directly by default, so the required action is to make
the file reachable by `#include "BDT.cpp"`. If you instead add `BDT.cpp` as an
explicit Vitis kernel source, also add this define:

```ini
define=BDT_TREE_SCORES_EXTERNAL=1
```

Copy the updated host source into the Vitis host project:

```shell
cp <repo>/src/vitis_adc_platform/host.cpp \
  <host project>/src/
```

In Vitis Classic IDE, open the hardware build settings for `test_adc_kernels`,
select `dummy_kernel`, and update the kernel `V++ configuration settings` box.
If the current box only contains:

```ini
[hls]
clock=307200000:dummy_kernel
```

change it to:

```ini
include=<kernel project>/src
include=<bdt project>/firmware
define=USE_CONIFER_BDT=1

[hls]
clock=307200000:dummy_kernel
```

Only add this define after generating and copying `bdt_norm_config.h`:

```ini
define=BDT_USE_NORM_CONFIG=1
```

If Vitis rejects `include=` or `define=` in the `V++ configuration settings`
box, leave the config box as:

```ini
[hls]
clock=307200000:dummy_kernel
```

and put this in the kernel `V++ command line options` box instead:

```text
--include <kernel project>/src --include <bdt project>/firmware --define USE_CONIFER_BDT=1
```

After the edits, rebuild in this order:

1. Clean and build `test_adc_kernels`.
2. Clean and build `test_adc_system` or `test_adc_system_hw_link`.
3. Build `test_adc`.
4. Deploy the matched `test_adc` executable and `dummy_kernel.xclbin`.

## Board Test

Run the host with the matching host executable and xclbin:

```shell
./test_adc dummy_kernel.xclbin
```

This default run disables the sum gate, so both low- and high-amplitude PPS
captures should complete. To reproduce the old fixed veto or require a positive
sum crossing:

```shell
./test_adc dummy_kernel.xclbin --sum-veto 200
./test_adc dummy_kernel.xclbin --sum-trigger 200
```

Expected real-BDT host output includes:

```text
Sum gate disabled: every armed PPS candidate is accepted
BDT score is printed but does not select events
Frame 0 BDT score: <score> (raw <raw>)
```

If `USE_CONIFER_BDT` was not defined, the fallback output remains:

```text
Frame 0 dummy BDT score: <score> (raw <raw>)
```

If the host still prints `dummy BDT score` after rebuilding, the host is current
but the xclbin was built without the real-BDT branch. Check the kernel V++
settings and build log:

```shell
grep -R "USE_CONIFER_BDT\|bdt_sum_trigger_conifer\|BDT.cpp" \
  "<kernel project>/Hardware/build/dummy_kernel/dummy_kernel/vitis_hls.log"
```

The log should show that `USE_CONIFER_BDT` reached the HLS compile and that
`bdt_sum_trigger_conifer.h` included `BDT.cpp`. If not, force the define in the
kernel `V++ configuration settings` box:

```ini
include=<kernel project>/src
define=USE_CONIFER_BDT=1

[hls]
clock=307200000:dummy_kernel
```

Then clean and rebuild `test_adc_kernels`, rebuild the hardware-link/system
project, and deploy the newly generated `dummy_kernel.xclbin`. Running an older
xclbin will also keep printing `dummy BDT score`.

Board-test checklist:

- HLS acquisition loop remains `II=1`.
- `wave.txt` still has four columns and `16384` per-channel samples.
- A default run completes at both sides of the former 10 mVpp boundary.
- `--sum-veto 200` rejects candidates with `max(sum) >= 200`.
- `--sum-trigger 200` accepts candidates with `max(sum) >= 200`.
- Real-BDT builds print `Frame N BDT score`, not `dummy BDT score`.
- The BDT score does not affect event selection.
- With the correct `norm_stats.npy`, compare the printed score against an
  offline calculation using the same captured waveform and feature indices.

## Later BDT Trigger

Only after score validation passes on board, add BDT event selection:

```cpp
bool bdt_accept = candidate_bdt_score_valid &&
                  candidate_bdt_score_raw >= BDT_SCORE_THRESHOLD_RAW;

if (sum_max_accept && bdt_accept) {
    accepted_bdt_score_raw = candidate_bdt_score_raw;
    accepted_bdt_score_valid = candidate_bdt_score_valid;
    accepted_bdt_score_real = candidate_bdt_score_real;
    event_accepted = true;
}
```

Record the final BDT threshold in the same raw fixed-point scale printed by the
host.

## BDT Latency Optimization (June-July 2026)

### Latency analysis

The original BDT inference took about 3.5 us at the 76.8 MHz kernel clock,
and roughly 95% of it was the feature gather: 250 serial reads from a
BRAM-backed downsample buffer at one read per cycle. The tree forest itself was
never the bottleneck; conifer evaluates all 50 trees as parallel
comparator/mux networks.

### Current implementation

`bdt_sum_score` was split into a three-part API implemented by both BDT modes
(`bdt_feature_offset`, `bdt_gather_feature`, `bdt_finalize_score`, plus
`BDT_FEATURE_COUNT`). `export_bdt_headers.py` converts every selected 1250-bin
feature index into its deterministic source word in the 8192-word accepted
capture. `gather_bdt_feature_pairs` reads two of those source words per cycle
from the dual-port `word_average_buffer`, then `bdt_finalize_score` evaluates
the forest before `write_triggered_waveform` starts. The waveform word comes
from `capture_buffer` (URAM), so scoring and waveform storage remain separate.
The metadata is packed after the waveform write as before. Event acceptance is
unchanged; the score remains diagnostic.

The original gather fusion was introduced in commit `72f733c`. The
trigger-anchored resampling correction replaces its continuously phased
downsample history with the capture-aligned average buffer described above.

### Previous synthesis results (workstation build, 2026-06)

From `csynth.rpt` of the `USE_CONIFER_BDT` build:

- `write_triggered_waveform`: `II=1`, trip count 2048, total 2050 cycles.
  The gather adds zero cycles to the readout.
- `bdt_finalize_score`: latency 1 cycle (12.987 ns). At the 13 ns clock period
  the entire 50-tree forest fits in one cycle as combinational logic
  (each `decision_function_N` reports 0 cycles; only 249 FFs in the block).
- m_axi burst inference intact: one `write 2048 x 512` burst on `gmem0`.
- Resource cost of the forest: about 54k LUTs (12% of the ZU48DR), 0 DSP,
  0 BRAM.

Net effect: dedicated BDT time per event dropped from ~270 cycles (~3.5 us) to
~1 cycle (~13 ns) after the writeout loop.

These measurements predate both the fast pre-write gather and the two-sample
word evaluation. Re-run HLS and confirm:

- `gather_bdt_feature_pairs`: trip count 125 and `II=1`, approximately
  127 cycles including BRAM latency.
- `bdt_finalize_score`: use the newly reported latency; the tighter clock may
  require multiple pipeline stages.
- `write_triggered_waveform`: trip count 8192 and `II=1`.

At 307.2 MHz the 125-cycle gather is approximately 0.41 us, while the host
still receives the score after waveform writeout.

Timing watch items for the Vivado implementation stage:

- `bdt_finalize_score` HLS slack is only 0.01 ns (whole forest combinational in
  one 13 ns period).
- The writeout pipeline module reported slack -0.00 at HLS estimate level.

If post-route WNS is negative through the forest, add
`#pragma HLS LATENCY min=2` to `bdt_finalize_score` to insert a register stage
(latency becomes ~3 cycles, still negligible). Do not add it preemptively.

### Where to find latency and resources

HLS report, under the Vitis kernel project on the build machine:

```text
<kernel project>/Hardware/build/dummy_kernel/dummy_kernel/dummy_kernel/solution/syn/report/csynth.rpt
```

Read the "Performance & Resource Estimates" table:
`gather_bdt_feature_pairs` must have trip count 125 and `II=1`,
`bdt_finalize_score` is the forest inference latency, and
`write_triggered_waveform` must remain `II=1`. Post-route truth comes from the
link-stage Vivado reports (`*util_routed.rpt`,
`*timing_summary_routed.rpt`).

In the Vivado implementation netlist the BDT cells are named:

```text
<bd_top>_i/dummy_kernel_1/inst/grp_bdt_finalize_score_fu_<N>
  grp_decision_function_<K>_fu_<N>   (50 trees, may be flattened away)
grp_dummy_kernel_Pipeline_write_triggered_waveform_fu_<N>
```

Useful Tcl on the routed design:

```tcl
report_utilization -cells [get_cells -hier -filter {NAME =~ "*grp_bdt_finalize_score*"}]
report_timing -through [get_cells -hier -filter {NAME =~ "*bdt_finalize_score*"}] -max_paths 5
```

### Deploying a newly trained BDT

Regenerate, never hand-edit:

- `csi_bdt_prj_kv260/firmware/BDT.h`, `BDT.cpp`, `parameters.h`: from
  conifer `model.write()` with `Precision = ap_fixed<18,8>`.
- `src/vitis_adc_platform/bdt_feature_indices.h` and `bdt_norm_config.h`:
  from `export_bdt_headers.py` with the new `top_feat_idx.npy` and
  `norm_stats.npy`.

Unchanged: `dummy_kernel.cpp`, `bdt_sum_trigger_conifer.h`, `host.cpp` — as
long as the score type stays `ap_fixed<18,8>` (otherwise update
`BDT_SCORE_BITS` in `export_bdt_headers.py` and `BDT_SCORE_SCALE` in
`host.cpp`). Training preprocessing must replicate the FPGA exactly: 4-channel
sum, integer two-lane average (`>>1`), the generated deterministic 8192-to-1250
source-word mapping, then the scalar z-score. Validate offline
(`model.decision_function` vs float predictions) before the board test;
on board, metadata bit 33 (`score_real = 1`) confirms the conifer path.

### Caution for the Later BDT Trigger section

The score is now computed before waveform DDR writeout, so a later PL trigger
can compare `bdt_score_raw` immediately and skip the waveform transfer for
rejected candidates. The example names
`candidate_bdt_score_*` / `accepted_bdt_score_*` are illustrative and do not
yet exist in the current kernel. Add the runtime threshold and decision
metadata only after fixed-point score validation is complete.

### Repository tags

- `self-trigger-4ch` -> `374fded`: internal threshold trigger on ADC data,
  4 channels at 612 Msps.
- `ext-trigger-4ch` -> `61535d3`: PPS external trigger streaming 4 channels at
  610 Msps.
