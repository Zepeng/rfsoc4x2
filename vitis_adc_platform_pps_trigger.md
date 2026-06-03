# External PPS Trigger for Four-Channel RFSoC4x2 ADC Capture

This guide extends the working four-channel RFSoC4x2 Vitis ADC platform so that the
acquisition trigger comes from the board's pulse-per-second (`1PPS`) SMA input instead
of an ADC_C threshold crossing. All four ADCs (ADC_D, ADC_C, ADC_B, ADC_A) remain
readout channels; ADC_C is no longer special.

Base four-channel platform references:

- [Vitis 2023.1 Classic IDE guide](vitis_adc_platform_classicIDE.md)
- [Vitis 2023.2.1 Unified IDE guide](vitis_adc_platform.md)

> **Status of the base design (verified on board):** four real ADC streams capture
> cleanly with RFDC `Decimation=8`, `Data_Width=8` (8 real samples per word),
> `4.9152 GS/s` → `614.4 MS/s` per channel, common stream clock `clk_adc0` at
> `76.8 MHz` (platform clock id `3`). This PPS work only swaps the trigger source; it
> does not change the ADC datapath.

---

## 1. Board PPS Circuit (from the Reference Manual, Figure 6)

The `1PPS` SMA feeds an **AC-coupled** node that fans out to **three parallel taps** —
they are independent, not chained:

| Tap | Output net(s) | FPGA pin(s) | Role |
|---|---|---|---|
| **Schmitt trigger** | `IRIG_TRIG_OUT` | `AH13` | Fast digital edge, fixed thresholds + hysteresis. **Use this as the trigger.** |
| Comparator (LMV7235) | `IRIG_COMP_OUT` | `AJ13` | Threshold-adjustable (R divider), but **75 ns** propagation delay + dispersion. Not used for triggering. |
| SPI ADC (ADS7885S, 8-bit) | `IRIG_TRIG_SDO/SCK/CS_N` | (Appendix A) | Reads the analog PPS *level*. Optional bring-up aid. |

Signals are `LVCMOS18` unless otherwise noted
([RFSoC4x2 Reference Manual](https://www.realdigital.org/downloads/4b98c421901794107cd1e25e208fe002.pdf),
Appendix A).

### Why the Schmitt path (`IRIG_TRIG_OUT`)
- A dedicated logic Schmitt trigger has single-digit-ns propagation delay versus the
  LMV7235's **75 ns**, and it is a **separate, parallel path** — it does *not* inherit
  the comparator's delay or dispersion.
- Its built-in hysteresis prevents chatter / double-triggering on a slow or noisy edge.
- The 75 ns / dispersion caveat therefore applies only to `IRIG_COMP_OUT`, which this
  design does not use. Keep the comparator path in mind only if your PPS is marginal /
  low-level and needs the adjustable threshold.

### Datapath

```text
1PPS SMA  (AC-coupled)
  -> on-board Schmitt trigger
  -> IRIG_TRIG_OUT / AH13  (LVCMOS18)
  -> pps_trigger_axis  (static RTL: 2-FF sync into clk_adc0, level as AXIS word)
  -> PPS_TRIG_AXIS
  -> dummy_kernel_1.ext_trigger_in

ADC_D / ADC_C / ADC_B / ADC_A
  -> RFDC AXI4-Stream outputs (8 real samples per 128-bit word)
  -> dummy_kernel_1 ADC readout inputs
```

### Platform settings this design keeps

| Setting | Value |
|---|---:|
| RFDC converter sample rate | `4.9152 GS/s` |
| ADC decimation | `8` |
| Per-channel output rate | `614.4 MS/s` |
| Samples per RFDC AXIS word (`Data_Width`) | `8` |
| Per-channel stream width | `128 bit` |
| Common RFDC AXIS clock | `clk_adc0`, **`76.8 MHz`**, platform clock id `3` |
| Capture depth (`CAPTURE_WORDS`/`DATA_SIZE`) | `2048` words = `16384` samples/ch ≈ `26.67 µs` |

---

## 2. Trigger Timing, Accuracy, and Test Signal

### Resolution and accuracy
The PPS level is sampled once per fabric cycle (one 128-bit word = 8 ADC samples), so
the trigger is localized to:

- **On-chip quantization: ±1 `clk_adc0` cycle = 8 samples = `13.0 ns`** at `76.8 MHz`.
  This is the dominant on-chip term (coarser than a faster fabric would give, because
  the stream clock is only 76.8 MHz).
- **Schmitt path:** a few ns fixed propagation delay (calibratable) + small slew-rate
  time-walk. Negligible next to the 13 ns quantization if the PPS edge is reasonably
  fast.
- **Absolute (vs UTC):** dominated by your PPS source — tens of ns for a typical GPS
  module, sub-ns for a GPSDO — plus a fixed, calibratable path delay.

There is no sub-word resolution without a faster sampling clock; 13 ns / 8 samples is
the floor here and is fine for "start capture on PPS." (A faster PL clock oversampling
`IRIG_TRIG_OUT` could improve this later, at the cost of an extra clock-domain crossing.)

### AC-coupling consequences
The SMA path is AC-coupled, so:
- Drive a **pulse train with a distinct low interval**, not a constant high level.
- The pulse must have enough amplitude to swing the biased node across the Schmitt's
  fixed `VT+` (≈ half-supply). Narrow pulses through the coupling cap are attenuated, so
  amplitude and width matter.
- Verify the waveform at the cable end with a scope before connecting to the board. The
  manual does not state a max PPS amplitude, so do **not** assume a 5 V TTL pulse is
  safe — increase amplitude gradually.
- **Optional check:** read the analog level over SPI from the ADS7885S
  (`IRIG_TRIG_SDO/SCK/CS_N`) to confirm the pulse actually reaches the Schmitt
  threshold before trusting the digital edge.

### Initial function-generator settings

| Setting | Initial value |
|---|---:|
| Waveform | Pulse or square wave |
| Frequency | `1 Hz`, then `60 Hz` |
| Pulse width | `1 µs` to `1 ms` |
| Amplitude | start `1 Vpp`, raise gradually if PL does not toggle |
| Offset | `0 V` |
| Generator load | `50 Ω` |

### Capture rate and missed triggers
The capture rate is set by the trigger source, not the host. The current ADC_C
threshold trigger streams at the host `--rate` (default `60 Hz`) because threshold
crossings are abundant — each launched kernel finds a trigger almost immediately, so the
loop is paced by the host's per-frame work (read DDR + format + send/save + re-enqueue).
A PPS edge is sparse instead, so the kernel blocks until the next edge and the loop is
paced by the PPS itself.

Every PPS edge is still captured as long as that per-frame work finishes within one PPS
period: after a capture the kernel re-arms and waits, armed, for the next edge. The
ADC_C design already sustains `60 Hz`, which proves the per-frame work fits well inside
`16.7 ms`, so a **`60 Hz` PPS is captured at full rate with the existing single buffer —
no buffer change is needed**. A missed edge only occurs if per-frame work exceeds the
PPS period, in which case the next edge is taken (a one-period gap); with abundant ADC_C
crossings such a miss is invisible, with sparse PPS edges it costs a full period.

> **`--rate` gotcha:** the kernel blocks on the PPS edge, so the edges should pace the
> loop. If `--rate` is left at the PPS rate, the host's pacing sleep stacks on top of the
> kernel's ~one-period blocking wait and can push re-arm past the next edge, catching
> only every other edge (e.g. 30 Hz for a 60 Hz PPS). Set `--rate` well above the PPS
> rate and let the PPS set the cadence.

Ping-pong / queued buffers are only needed if per-frame work approaches or exceeds the
trigger period (much higher rates or heavy per-frame transport) — not at `60 Hz`.

---

## 3. Static RTL Trigger Adapter (`pps_trigger_axis.v`)

The repository now provides this source as
`src/vitis_adc_platform/pps_trigger_axis.v`. The hardware Tcl imports it automatically
when the file is copied next to `rfsoc_adc_hardware.tcl` in the workspace. It
2-FF-synchronizes the asynchronous `IRIG_TRIG_OUT` into the `clk_adc0` domain and
presents the current level as one continuously valid AXI4-Stream word per cycle. The
kernel reads it in lockstep with the four RFDC streams and does the rising-edge
detection.

```verilog
`timescale 1 ns / 1 ps

module pps_trigger_axis (
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME aclk, ASSOCIATED_BUSIF m_axis, ASSOCIATED_RESET aresetn" *)
    input  wire        aclk,

    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 aresetn RST" *)
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME aresetn, POLARITY ACTIVE_LOW" *)
    input  wire        aresetn,

    input  wire        pps_in,

    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 m_axis TDATA" *)
    output wire [31:0] m_axis_tdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 m_axis TVALID" *)
    output wire        m_axis_tvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 m_axis TREADY" *)
    input  wire        m_axis_tready,

    output wire        dbg_pps_sync_level,
    output wire        dbg_axis_level,
    output wire        dbg_axis_valid
);

(* ASYNC_REG = "TRUE" *) reg [1:0] pps_sync;
reg [31:0] axis_data;

always @(posedge aclk) begin
    if (!aresetn) begin
        pps_sync  <= 2'b00;
        axis_data <= 32'b0;
    end else begin
        pps_sync <= {pps_sync[0], pps_in};
        if (m_axis_tready)
            axis_data <= {31'b0, pps_sync[1]};
    end
end

assign m_axis_tdata  = axis_data;
assign m_axis_tvalid = aresetn;

assign dbg_pps_sync_level = pps_sync[1];
assign dbg_axis_level     = axis_data[0];
assign dbg_axis_valid     = m_axis_tvalid;

endmodule
```

Notes:
- The stream is **32-bit** carrying one valid bit (bit 0). It stays 32-bit even though
  the ADC streams are 128-bit — the kernel port for it is `ap_uint<32>`, which generates
  an AXIS interface with only TDATA/TVALID/TREADY (no TLAST/TKEEP), matching this module.
- `m_axis_tdata` holds when `m_axis_tready` is low, as AXI4-Stream requires.
- The `dbg_*` outputs feed the bring-up ILA and are not consumed by Vitis.
- Do not feed `IRIG_TRIG_OUT` to the kernel without this synchronizer.

---

## 4. PPS Pin Constraint (`pps_trigger.xdc`)

The repository now provides this constraint as `src/vitis_adc_platform/pps_trigger.xdc`.

```tcl
set_property PACKAGE_PIN AH13      [get_ports IRIG_TRIG_OUT]
set_property IOSTANDARD  LVCMOS18  [get_ports IRIG_TRIG_OUT]
```

The top-level block-design port name must be `IRIG_TRIG_OUT`. Confirm the pin and bank
voltage against the official RealDigital master XDC before building.

---

## 5. Vivado Block Design Updates

The repository hardware Tcl scripts now implement these static-platform changes:

- `src/vitis_adc_platform/rfsoc_adc_hardware.tcl`
- `src/vitis_adc_platform/rfsoc_adc_hardware_2023_2_1.tcl`

Copy `pps_trigger_axis.v` and `pps_trigger.xdc` next to the hardware Tcl before
sourcing it:

```shell
export WORKSPACE=/home/neutrino/workspace_4ch
export REPO=/path/to/rfsoc4x2
cp "$REPO/src/vitis_adc_platform/rfsoc_adc_hardware.tcl" "$WORKSPACE/"
cp "$REPO/src/vitis_adc_platform/pps_trigger_axis.v" "$WORKSPACE/"
cp "$REPO/src/vitis_adc_platform/pps_trigger.xdc" "$WORKSPACE/"
cp "$REPO/src/vitis_adc_platform/check_rfsoc_adc_bd.tcl" "$WORKSPACE/"
```

If Vivado reports:

```text
Failed to resolve reference ... pps_trigger_axis
Unable to resolve module-source based on inputs: pps_trigger_axis
```

then the workspace is using an older hardware Tcl/source set, or Vivado is reopening a
partially generated failed project. Re-copy the files above, then delete or rename the
generated `/home/neutrino/workspace_4ch/rfsoc_adc_hardware` project directory before
rerunning `vivado -source rfsoc_adc_hardware.tcl`. The updated Tcl adds
`pps_trigger_axis.v` to `sources_1`, marks it as Verilog, and updates the compile order
before creating `pps_trigger_axis_0`.

If synthesis reports:

```text
Unable to run synthesis. No HDL sources found in project
```

then the block design was created but the top HDL wrapper was not added to `sources_1`.
In the Vivado Tcl console, recover the current project with:

```tcl
set system_bd_file [get_files -norecurse system.bd]
generate_target all $system_bd_file
set wrapper_path [make_wrapper -fileset sources_1 -files $system_bd_file -top]
foreach wrapper_file $wrapper_path {
  add_files -norecurse -fileset sources_1 $wrapper_file
}
set_property top system_wrapper [get_filesets sources_1]
update_compile_order -fileset sources_1
report_compile_order -fileset sources_1
```

After `system_wrapper.v` appears in `sources_1`, rerun synthesis/implementation. The
updated hardware Tcl now performs these wrapper-generation steps automatically.

The scripted Vivado design does the following:

1. Add an external input port named `IRIG_TRIG_OUT`.
2. Add `pps_trigger_axis` as a module reference `pps_trigger_axis_0`.
3. Connect the input: `IRIG_TRIG_OUT -> pps_trigger_axis_0/pps_in`.
4. Connect to the common RFDC stream clock (the same `clk_adc0` the four ADC streams
   use):
   ```text
   usp_rf_data_converter_0/clk_adc0 -> pps_trigger_axis_0/aclk
   ```
5. Connect the matching active-low reset:
   ```text
   proc_sys_reset_clk_adc0/peripheral_aresetn -> pps_trigger_axis_0/aresetn
   ```
6. Export the adapter AXIS interface to Vitis:
   ```tcl
   set_property PFM.AXIS_PORT {
     m_axis { type "M_AXIS" sptag "PPS_TRIG_AXIS" is_range "false" }
   } [get_bd_cells /pps_trigger_axis_0]
   ```
7. Add `ila_pps_trigger` clocked by `clk_adc0` with five one-bit probes:
   ```text
   probe0 = pps_trigger_axis_0/dbg_pps_sync_level
   probe1 = pps_trigger_axis_0/dbg_axis_level
   probe2 = pps_trigger_axis_0/dbg_axis_valid
   probe3 = pps_trigger_axis_0/m_axis_tready
   probe4 = pps_trigger_axis_0/aresetn
   ```
8. `validate_bd_design` then `save_bd_design`.
9. Generate the bitstream and export a new `.xsa` (bitstream included).

The static platform changed, so regenerate the Vitis platform from the new `.xsa`
before rebuilding the application.

---

## 6. Verify the Exported Platform

Before implementation, run the block-design checker from the workspace:

```shell
cd /home/neutrino/workspace_4ch
vivado -mode batch -source check_rfsoc_adc_bd.tcl \
  -tclargs --hardware_tcl /home/neutrino/workspace_4ch/rfsoc_adc_hardware.tcl
```

The check should end with:

```text
CHECK PASSED: four 614.4 MS/s ADC streams plus PPS_TRIG_AXIS and PPS ILA use common clk_adc0
```

Confirm common RFDC clock id `3` is fixed at **76.8 MHz**:

```shell
platforminfo -v -p \
  /home/neutrino/workspace_4ch/rfsoc_adc_vitis_platform/export/rfsoc_adc_vitis_platform/rfsoc_adc_vitis_platform.xpfm |
  sed -n '/Clock Information/,/Memory Information/p'
```

Confirm the new stream tag exists:

```shell
grep -Rni "PPS_TRIG_AXIS" \
  /home/neutrino/workspace_4ch/rfsoc_adc_vitis_platform/export/rfsoc_adc_vitis_platform
```

Do not continue if clock id `3` is missing/scaled or `PPS_TRIG_AXIS` is absent.

---

## 7. HLS Kernel Changes (`dummy_kernel.cpp`)

Keep the four 128-bit ADC streams. Add a fifth, 32-bit stream for the synchronized
trigger, drop the ADC_C threshold logic, and trigger on the PPS rising edge.

Add the trigger packet type (32-bit, no side channels):

```cpp
typedef ap_uint<32> trigger_pkt;
```

Update the kernel signature — add `ext_trigger_in`, remove `trigger_threshold`:

```cpp
void dummy_kernel(ap_uint<PACKED_WIDTH>* buffer0,
                  hls::stream<pkt>& data_in,
                  hls::stream<pkt>& trigger_in,
                  hls::stream<pkt>& adc_b_in,
                  hls::stream<pkt>& adc_a_in,
                  hls::stream<trigger_pkt>& ext_trigger_in,
                  unsigned int size,
                  unsigned int output_words) {
#pragma HLS INTERFACE m_axi port = buffer0 bundle = gmem0
#pragma HLS INTERFACE axis port = data_in
#pragma HLS INTERFACE axis port = trigger_in
#pragma HLS INTERFACE axis port = adc_b_in
#pragma HLS INTERFACE axis port = adc_a_in
#pragma HLS INTERFACE axis port = ext_trigger_in
```

Remove `get_trigger_sample()`, the `int trigger_threshold` argument, and the
`threshold` / `previous_trigger_sample` state. Replace them with PPS edge-state
variables before the loop:

```cpp
bool previous_ext_trigger_level = false;
bool ext_trigger_armed = false;
```

Inside the existing `II=1` capture loop, read the trigger once per ADC word. Require a
low level before accepting the next rising edge; otherwise a relaunch while the PPS pulse
is still high can false-trigger immediately:

```cpp
ap_uint<PACKED_WIDTH> packed =
    read_packed_word(data_in, trigger_in, adc_b_in, adc_a_in);
trigger_pkt ext_trigger_word = ext_trigger_in.read();

capture_buffer[write_idx] = packed;
advance_index(write_idx, CAPTURE_WORDS);

bool ext_trigger_level = ext_trigger_word[0];
if (!ext_trigger_level) {
    ext_trigger_armed = true;
}
bool crossing = ext_trigger_armed && !previous_ext_trigger_level && ext_trigger_level;
if (crossing) {
    ext_trigger_armed = false;
}
previous_ext_trigger_level = ext_trigger_level;
```

The rest of the arm/trigger/post-trigger state machine is unchanged. Keep:

```cpp
#pragma HLS PIPELINE II = 1
```

After rebuilding HLS, confirm the capture loop still reports `II=1` (trivial at
`76.8 MHz` with five always-valid stream reads). The trigger marks a word boundary, so
trigger position is word-granular (8-sample / 13 ns resolution).

ADC_C / `trigger_in` is now just readout column 2 — its data path is unchanged.

---

## 8. Host Application Changes (`host.cpp`)

The kernel now has five AXIS inputs and two scalar args. Update `setArg` (the four AXIS
streams are connected by the linker, not set here):

```cpp
unsigned int size = DATA_SIZE;
unsigned int output_words = PACKED_WORDS_PER_FRAME;
OCL_CHECK(err, err = krnl.setArg(0, buffer));
OCL_CHECK(err, err = krnl.setArg(6, size));          // was 5
OCL_CHECK(err, err = krnl.setArg(7, output_words));  // was 6; threshold arg removed
```

Also:
- Remove the `--threshold` option, `DEFAULT_TRIGGER_THRESHOLD`, the `trigger_threshold`
  field, its parsing/validation, and the "FPGA threshold trigger on … ADC_C" messages.
- Update usage/help text: the trigger is now the external `1PPS` rising edge on
  `IRIG_TRIG_OUT`; ADC_C is a readout channel.
- `wave.txt` remains four columns: `ADC_D ADC_C ADC_B ADC_A`.

Always deploy the host executable and `dummy_kernel.xclbin` from the same Vitis build.

---

## 9. V++ Linker Configuration

```ini
[clock]
id=3:dummy_kernel_1

[connectivity]
stream_connect = RFDC_DATA_AXIS:dummy_kernel_1.data_in
stream_connect = RFDC_TRIG_AXIS:dummy_kernel_1.trigger_in
stream_connect = RFDC_ADC_B_AXIS:dummy_kernel_1.adc_b_in
stream_connect = RFDC_ADC_A_AXIS:dummy_kernel_1.adc_a_in
stream_connect = PPS_TRIG_AXIS:dummy_kernel_1.ext_trigger_in

[hls]
clock=76800000:dummy_kernel
```

Clock id `3` is the common RFDC stream clock `clk_adc0` at `76.8 MHz`. If the link step
cannot find clock id `3`, an `RFDC_*_AXIS`, or `PPS_TRIG_AXIS`, rebuild the Vivado
design, re-export the `.xsa`, and regenerate the platform.

---

## 10. Rebuild and Deploy

Because the static platform changed:

1. Recreate the Vivado project from the updated hardware Tcl:

   ```shell
   cd /home/neutrino/workspace_4ch
   if [ -d rfsoc_adc_hardware ]; then mv rfsoc_adc_hardware rfsoc_adc_hardware.failed.$(date +%s); fi
   vivado -source rfsoc_adc_hardware.tcl
   ```

2. In the Vivado Tcl console, run implementation and export the hardware platform:

   ```tcl
   launch_runs impl_1 -to_step write_bitstream -jobs 8
   wait_on_run impl_1
   open_run impl_1
   write_hw_platform -fixed -include_bit -force \
     /home/neutrino/workspace_4ch/rfsoc_adc_hardware/rfsoc_adc_hardware.xsa
   ```

3. Regenerate and rebuild the Vitis platform from the new `.xsa`. Then verify the
   exported `.xpfm` with the `platforminfo` command in Section 6.

4. Update the HLS kernel and host as described in Sections 7 and 8, then set the V++
   options from Section 9. Rebuild HLS, hardware link, and package.

5. Verify the generated `xclbin` has all five stream connections:

   ```shell
   xclbinutil --info --input \
     /home/neutrino/workspace_4ch/test_adc_system/Hardware/package/sd_card/dummy_kernel.xclbin | \
     grep -E "data_in|trigger_in|adc_b_in|adc_a_in|ext_trigger_in|PPS_TRIG_AXIS|dummy_kernel"
   ```

6. Copy the complete generated `sd_card` directory to the SD-card FAT32 boot partition.
   Replacing only `test_adc` and `dummy_kernel.xclbin` is insufficient because the PPS
   adapter and ILA are part of the static hardware image:

   ```shell
   sudo cp /home/neutrino/workspace_4ch/test_adc_system/Hardware/package/sd_card/* /path/to/mounted/boot/
   sync
   ```

---

## 11. Verify the Trigger on the Board with the ILA

The updated hardware Tcl includes one native-probe ILA named `ila_pps_trigger` next to
`pps_trigger_axis_0`, clocked from the same free-running stream clock:

```text
usp_rf_data_converter_0/clk_adc0   (76.8 MHz)
```

Configure the RF reference clocks before opening Hardware Manager, or debug cores may
not be detected. The ILA probes are:

```text
probe0 = pps_trigger_axis_0/dbg_pps_sync_level
probe1 = pps_trigger_axis_0/dbg_axis_level
probe2 = pps_trigger_axis_0/dbg_axis_valid
probe3 = pps_trigger_axis_0/m_axis_tready
probe4 = pps_trigger_axis_0/aresetn
```

Do **not** probe `pps_sync[0]` (the metastability-catch flip-flop). Probe the raw
`IRIG_TRIG_OUT` only as a coarse diagnostic if needed; it is asynchronous to `clk_adc0`.

Initial ILA settings:

| Setting | Value |
|---|---:|
| Probe type | Native |
| Clock | `clk_adc0`, `76.8 MHz` |
| Capture depth | `1024` (≈ `1024 / 76.8 MHz = 13.3 µs`) |
| Trigger position | `512` |
| Trigger condition | Rising edge of `probe0` / `dbg_pps_sync_level` |

Expected: `probe0` rises a few `clk_adc0` cycles after the external edge; `probe1`
follows when the AXIS word updates; `probe2` remains high after reset. `probe3`
(`TREADY`) is meaningful after the Vitis linked design connects `PPS_TRIG_AXIS` to the
kernel; it should be high while the kernel is waiting/capturing.

Bring-up order:

1. Configure RF reference clocks.
2. Program the PPS-enabled bitstream.
3. Open Hardware Manager, arm the ILA on `probe0` rising.
4. Send a `1 Hz` PPS; confirm sync + AXIS handshaking.
5. Increase to `60 Hz`.
6. Run the host capture and correlate completion with the ILA waveform.

ILA references:
[UG908 Debug Core Clocks](https://docs.amd.com/r/2023.1-English/ug908-vivado-programming-debugging/Debug-Core-Clocks),
[Netlist Insertion Debug Flow](https://docs.amd.com/r/2023.1-English/ug908-vivado-programming-debugging/Using-the-Netlist-Insertion-Debug-Probing-Flow).

Run the application:

```shell
cd /run/media/boot-mmcblk0p1/
chmod +x test_adc
./test_adc dummy_kernel.xclbin
```

Capture should complete on a rising edge at the `1PPS` SMA input. ADC_C remains
available as a readout channel.

---

## 12. Plot the Four ADC Channels

```shell
python3 src/vitis_adc_platform/plot_wave.py wave.txt --channel all --start 0 --count 2000
```

To view one sample per RFDC word (8 samples/word in this design), pass
`--word-lane 0`. The current plotting default is `--lanes-per-word 8`, matching this
decimation-8 / Data_Width-8 RFDC format.

---

## Appendix: Open Items to Confirm Before Building

- **Schematic check:** confirm `IRIG_TRIG_OUT` (AH13) bank voltage = `LVCMOS18`, the
  AC-coupling cap value vs your pulse width, and the Schmitt `VT+` vs your PPS amplitude.
- **Capture rate:** `60 Hz` PPS works with the existing single buffer (the ADC_C design
  already sustains `60 Hz`). Set `--rate` above the PPS rate so host pacing does not
  delay re-arm. Ping-pong is only needed at much higher rates / heavy per-frame work.
- **Tile-2 alignment:** the four channels capture cleanly with `clk_adc0` shared across
  tiles (`Multi_Tile_Sync=false`), verified on board. Cross-tile channels (C/D on tile 0
  vs B/A on tile 2) are not guaranteed sample-aligned to each other; enable MTS only if
  you later need coherent cross-tile timing relative to the PPS.
