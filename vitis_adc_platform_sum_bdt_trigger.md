# Four-Channel Sum Threshold and BDT Trigger

This note documents the current trigger implementation for the RFSoC four-stream
ADC kernel. The max-threshold trigger has passed board testing. The kernel now
also has a BDT score path based on `csi_bdt_prj_kv260`, with the BDT score printed
by the host but not yet used for event selection.

Event selection is still:

```cpp
external PPS rising edge && max(ADC_D + ADC_C + ADC_B + ADC_A) < 200
```

The BDT output is diagnostic readout for the next board test.

## Source Files

Tracked integration files:

- `src/vitis_adc_platform/dummy_kernel.cpp`
- `src/vitis_adc_platform/host.cpp`
- `src/vitis_adc_platform/bdt_sum_trigger_conifer.h`
- `src/vitis_adc_platform/bdt_feature_indices.h`
- `src/vitis_adc_platform/export_bdt_headers.py`
- `vitis_adc_platform_sum_bdt_trigger.md`

External generated BDT firmware used by the HLS build:

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

Each stream word is 128 bits, containing eight signed 16-bit samples. The kernel
reads ADC_D, ADC_C, ADC_B, ADC_A, and `PPS_TRIG_AXIS` in lockstep.

For every stream word, the acquisition loop:

1. Packs the four raw ADC words into the 512-bit waveform ring buffer.
2. Sign-extends all eight lanes from all four channels.
3. Computes `sum_sample = ADC_D + ADC_C + ADC_B + ADC_A` for each lane.
4. Marks the word over threshold if any lane has `sum_sample >= 200`.
5. Maintains `over_threshold_ring[2048]` and `over_threshold_count`.
6. Computes the eight-lane average of the sum waveform.
7. Downsamples the 2048 capture words into `downsample_history[1250]`.

The max-threshold tracking and downsample writes run inside the same pipelined
capture loop as the waveform ring-buffer write.

When the PPS candidate completes, the FPGA accepts only candidates with:

```cpp
bool sum_max_accept = (over_threshold_count == 0);
```

For accepted candidates, the kernel copies the waveform to DDR and gathers the
BDT features inside the same pipelined writeout loop (the gather rides along in
the first 250 iterations, reading `downsample_history` while the waveform words
come from `capture_buffer`). After the loop, the BDT score is computed in a few
cycles and written as one metadata word. The BDT therefore adds essentially no
latency on top of the waveform readout. Rejected candidates are discarded
internally and the kernel waits for the next PPS candidate.

## BDT Modes

The kernel has two score implementations:

- Default build: dummy BDT score. This keeps the previously tested fallback path.
- `USE_CONIFER_BDT` build: real Conifer BDT score from `csi_bdt_prj_kv260`.

The real BDT path:

1. Reads the 250 selected feature indices from `bdt_feature_indices.h`.
2. Gathers those bins from the 1250-bin sum-waveform history.
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

The kernel returns `2049` packed 512-bit words:

```text
buffer0[0..2047]  chronological four-channel waveform
buffer0[2048]     trigger/BDT metadata
```

Waveform word layout:

```text
bits [127:0]    ADC_D / RFDC_DATA_AXIS
bits [255:128]  ADC_C / RFDC_TRIG_AXIS
bits [383:256]  ADC_B / RFDC_ADC_B_AXIS
bits [511:384]  ADC_A / RFDC_ADC_A_AXIS
```

Metadata word layout:

```text
bits [31:0]  signed raw BDT score
bit  [32]    score valid flag
bit  [33]    real BDT flag: 1 = Conifer BDT, 0 = dummy fallback
```

The host allocates and migrates `2049` words, unpacks only the first `2048` words
into `wave.txt` or the Ethernet stream, and decodes `buffer0[2048]` separately.

## HLS Build Setup

For the dummy fallback build, no generated BDT firmware is required.

For the real BDT build, add these to the HLS kernel build:

- Include path: `src/vitis_adc_platform`
- Include path: `csi_bdt_prj_kv260/firmware`
- Make `BDT.cpp` available either in the kernel `src` folder or through the
  BDT firmware include path
- Compile define: `USE_CONIFER_BDT`
- Compile define: `BDT_USE_NORM_CONFIG` only when `bdt_norm_config.h` exists

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
clock=76800000:dummy_kernel
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
clock=76800000:dummy_kernel
```

change it to:

```ini
include=<kernel project>/src
include=<bdt project>/firmware
define=USE_CONIFER_BDT=1

[hls]
clock=76800000:dummy_kernel
```

Only add this define after generating and copying `bdt_norm_config.h`:

```ini
define=BDT_USE_NORM_CONFIG=1
```

If Vitis rejects `include=` or `define=` in the `V++ configuration settings`
box, leave the config box as:

```ini
[hls]
clock=76800000:dummy_kernel
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

Expected real-BDT host output includes:

```text
BDT score is printed for accepted threshold events but does not select events
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
clock=76800000:dummy_kernel
```

Then clean and rebuild `test_adc_kernels`, rebuild the hardware-link/system
project, and deploy the newly generated `dummy_kernel.xclbin`. Running an older
xclbin will also keep printing `dummy BDT score`.

Board-test checklist:

- HLS acquisition loop remains `II=1`.
- `wave.txt` still has four columns and `16384` per-channel samples.
- Candidates with `max(sum) >= 200` are rejected internally.
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

## BDT Latency Optimization (June 2026)

### Latency analysis

The original BDT inference took about 3.5 us at the 76.8 MHz kernel clock,
and roughly 95% of it was the feature gather: 250 serial reads from the
BRAM-backed `downsample_history[1250]` at one read per cycle. The tree forest
itself was never the bottleneck; conifer evaluates all 50 trees as parallel
comparator/mux networks.

### Implementation (commit 72f733c)

`bdt_sum_score` was split into a three-part API implemented by both BDT modes
(`bdt_feature_offset`, `bdt_gather_feature`, `bdt_finalize_score`, plus
`BDT_FEATURE_COUNT`). The feature gather now rides inside the first 250
iterations of the `write_triggered_waveform` loop: the waveform word comes from
`capture_buffer` (URAM) while the gather reads `downsample_history` (BRAM), so
there is no port conflict and the loop keeps `II=1`. The score is computed
after the loop and packed into the metadata word as before. Event acceptance
(`sum_max_accept`) is unchanged; the score remains diagnostic. The math in both
modes is bit-identical to the previous version, so dummy-mode scores from older
boards are a regression reference.

### Synthesis results (workstation build, 2026-06)

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

Read the "Performance & Resource Estimates" table: the `bdt_finalize_score`
row is the BDT inference latency; the `write_triggered_waveform` row must stay
`II=1`; the absence of a ~250-cycle gather loop confirms the fusion took
effect (if `dummy_bdt_features` or `bdt_prepare_features` reappears, a stale
`dummy_kernel.cpp` copy is in the Vitis `src` folder). Post-route truth comes
from the link-stage Vivado reports (`*util_routed.rpt`,
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
sum, integer 8-lane average (`>>3`), the kernel's 2048-to-1250 accumulator
downsampling, then the scalar z-score. Validate offline
(`model.decision_function` vs float predictions) before the board test;
on board, metadata bit 33 (`score_real = 1`) confirms the conifer path.

### Caution for the Later BDT Trigger section

The code snippet above predates the gather fusion: the
`candidate_bdt_score_*` / `accepted_bdt_score_*` variables no longer exist,
and the score is now computed during/after the DDR writeout. Gating event
acceptance on the score will require either moving the gather back before the
accept decision (restoring ~250 cycles, ideally with the dual-port unroll to
halve it) or writing out every sum-max candidate and discarding rejected
frames on the host.

### Repository tags

- `self-trigger-4ch` -> `374fded`: internal threshold trigger on ADC data,
  4 channels at 612 Msps.
- `ext-trigger-4ch` -> `61535d3`: PPS external trigger streaming 4 channels at
  610 Msps.
