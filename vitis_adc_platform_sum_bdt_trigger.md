# Four-Channel Sum Trigger Bring-Up Plan

This note documents the staged trigger implementation. The commit-ready version
is **Step 1 only**: external PPS creates candidate events, and the FPGA accepts
only candidates whose four-channel sum waveform satisfies `max(sum) < 200`.

The BDT interface is intentionally left for Step 2 after the threshold trigger
has passed board testing.

## Current Commit: Threshold Trigger

The threshold-trigger build changes only:

- `src/vitis_adc_platform/dummy_kernel.cpp`
- `src/vitis_adc_platform/host.cpp`
- `vitis_adc_platform_sum_bdt_trigger.md`

No BDT headers, conifer firmware sources, BDT metadata word, or 2049-word host
transfer are part of this commit.

## Threshold Trigger Implementation

Each ADC stream word is 128 bits, containing eight signed 16-bit samples. The
kernel reads ADC_D, ADC_C, ADC_B, and ADC_A in lockstep.

For every stream word, the kernel:

1. Packs the four raw ADC words into the normal 512-bit event buffer.
2. Sign-extends all eight 16-bit lanes in each stream word.
3. Computes `sum_sample = ADC_D + ADC_C + ADC_B + ADC_A` for each lane.
4. Marks the word over threshold if any lane has `sum_sample >= 200`.
5. Maintains `over_threshold_ring[2048]` in parallel with the waveform ring.
6. Maintains `over_threshold_count`, so the completed candidate can be tested
   with `over_threshold_count == 0`.

The external PPS rising edge still defines a candidate event. After the
post-trigger interval completes, the FPGA applies:

```cpp
bool sum_max_accept = (over_threshold_count == 0);

if (sum_max_accept) {
    event_accepted = true;
} else {
    triggered = false;
    posttrigger_count = 0;
}
```

If a candidate fails the threshold check, the kernel discards it internally and
keeps streaming until a later PPS candidate passes.

## Output Buffer Layout

The threshold-trigger commit keeps the original transfer size:

```text
buffer0[0..2047]  chronological four-channel waveform
```

The waveform word layout is unchanged:

```text
bits [127:0]    ADC_D / RFDC_DATA_AXIS
bits [255:128]  ADC_C / RFDC_TRIG_AXIS
bits [383:256]  ADC_B / RFDC_ADC_B_AXIS
bits [511:384]  ADC_A / RFDC_ADC_A_AXIS
```

The host still allocates and migrates `2048` packed 512-bit words:

```cpp
static const size_t PACKED_WORDS_PER_FRAME = DATA_SIZE;
```

`wave.txt` and the Ethernet stream remain four-channel waveform payloads only.

## Step 1 Board Test Checklist

The tested threshold-trigger board build should satisfy:

- The HLS acquisition loop remains `II=1`.
- The host prints:

  ```text
  Accepted events also require max(ADC_D + ADC_C + ADC_B + ADC_A) < 200
  ```

- With a valid PPS input and a passing sum waveform, the host reaches
  `Writing data to wave.txt`.
- `wave.txt` has four columns and `16384` per-channel samples.
- The trigger sample remains near the expected pretrigger point.
- Candidates with `max(sum) >= 200` are rejected internally.
- No extra metadata word is written to the waveform file or network stream.

Record for the commit/test log:

- HLS loop II and latency summary.
- XRT run log.
- `wave.txt` from at least one accepted event.
- Any ILA capture proving PPS candidate creation and threshold
  rejection/acceptance.

## Step 2 Plan: BDT Interface

After the threshold trigger has passed on the board, add the BDT path in a
separate commit and hardware build.

### BDT Score Readout First

First add BDT score readout without using the BDT result for event selection.

1. Keep the threshold trigger logic unchanged.
2. Add a 1250-bin sum-waveform history in the same `II=1` acquisition loop:
   - Maintain `downsample_history[1250]`.
   - Use the average four-channel sum over each 8-lane stream word as the
     source sample.
   - Use an accumulator mapping from 2048 capture words to 1250 BDT bins.
   - Update this history in parallel with waveform-buffer writing.
3. Generate the 250 selected feature indices from the BDT project:

   ```shell
   python3 src/vitis_adc_platform/export_bdt_headers.py \
     --top-feat-idx csi_bdt_prj_kv260/pynq_data/top_feat_idx.npy \
     --output-dir src/vitis_adc_platform
   ```

4. If available, generate normalization constants from the training
   `norm_stats.npy`:

   ```shell
   python3 src/vitis_adc_platform/export_bdt_headers.py \
     --norm-stats path/to/norm_stats.npy \
     --output-dir src/vitis_adc_platform
   ```

5. Add the BDT wrapper and conifer firmware to the HLS build:
   - Include path: `src/vitis_adc_platform`.
   - Include path: `csi_bdt_prj_kv260/firmware`.
   - Source file: `csi_bdt_prj_kv260/firmware/BDT.cpp`.
   - Compile define: `USE_HLS4ML_BDT`.
   - Compile define `BDT_USE_NORM_CONFIG` only if `bdt_norm_config.h` exists.
6. Change the host/kernel transfer size for the score-readout build:
   - Kernel writes `buffer0[2048]` as metadata.
   - Host allocates `PACKED_WORDS_PER_TRANSFER = 2049`.
   - Host still unpacks only the first 2048 words as waveform data.
7. Keep event selection threshold-only during the first BDT board test:

   ```cpp
   if (sum_max_accept) {
       accepted_bdt_score_raw = candidate_bdt_score_raw;
       accepted_bdt_score_valid = candidate_bdt_score_valid;
       event_accepted = true;
   }
   ```

8. Run the host and confirm BDT score readout:

   ```text
   Frame 0 BDT score: <score> (raw <raw>)
   ```

9. Validate the score before using it as a trigger:
   - Confirm `bdt_score_valid` is true.
   - Compare the printed score against an offline software calculation for the
     same captured waveform.
   - Confirm the normalization constants match the training used by
     `csi_bdt.py`.
   - Inspect score separation for signal-like and background-like events.

### BDT Event Selection Second

Only after score validation passes, enable BDT selection:

```cpp
bool bdt_accept = candidate_bdt_score_valid &&
                  candidate_bdt_score_raw >= BDT_SCORE_THRESHOLD_RAW;

if (sum_max_accept && bdt_accept) {
    accepted_bdt_score_raw = candidate_bdt_score_raw;
    accepted_bdt_score_valid = candidate_bdt_score_valid;
    event_accepted = true;
} else {
    triggered = false;
    posttrigger_count = 0;
}
```

For the BDT-trigger board test, confirm:

- Candidates that pass the sum threshold but fail BDT are rejected.
- Candidates that pass both triggers are returned.
- The host still prints the BDT score for accepted events.
- The waveform output remains aligned and chronologically ordered.
- The final BDT threshold is recorded in the same fixed-point scale used by the
  firmware.
