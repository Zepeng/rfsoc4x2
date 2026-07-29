# Vivado 2025.2 Port

This branch ports the RFSoC4x2 four-channel ADC platform from Vivado/Vitis
2023.2.1 to 2025.2. The port is intentionally staged so that hardware design
changes, tool API changes, and Linux/XRT changes can be diagnosed separately.

## Current Status

- The branch starts from `origin/main` commit `a530765`.
- `rfsoc_adc_hardware_2023_2_1.tcl` remains the known-good functional source.
- `rfsoc_adc_hardware_2025_2.tcl` adapts that source for the 2025.2 run-flow
  names, uses an explicit RealDigital board-file location, validates the block
  design, and can export an extensible XSA.
- `create_rfsoc_adc_vitis_platform_2025_2.py` uses the documented 2025.2
  `hw_design` platform API and targets `psu_cortexa53_0`.
- Hardware emulation is deferred. It did not work for `xczu48dr` in the
  existing 2023.2.1 flow.

The scripts have only received static validation in this repository. They have
not yet run in Vivado or Vitis 2025.2.

## Required Build Host

Use a supported Linux or Windows x86-64 host for Vivado/Vitis. PetaLinux
requires Linux. Install the 2025.2 Zynq UltraScale+ RFSoC device support.

Clone and pin the RealDigital BSP separately:

```bash
git clone https://github.com/RealDigitalOrg/RFSoC4x2-BSP.git
git -C RFSoC4x2-BSP rev-parse HEAD
```

Record the tested BSP commit in this file once the first block-design check
passes.

## Phase 1: Create and Validate the Vivado Project

From the repository root:

```bash
export RFSOC4X2_BOARD_REPO=/absolute/path/to/RFSoC4x2-BSP

vivado -mode batch \
  -source src/vitis_adc_platform/rfsoc_adc_hardware_2025_2.tcl \
  -tclargs \
    --output_dir "$PWD/build/vivado_2025_2" \
    --export_xsa "$PWD/build/rfsoc_adc_hardware_2025_2.xsa"
```

The migration driver must:

1. Confirm the active tool version begins with `2025.2`.
2. Find `rfsoc4x2/1.0/board.xml` in the BSP `board_files` directory.
3. Recreate and validate `system.bd`.
4. Preserve RFDC v2.6 settings:
   - ADC tiles 0 and 2 enabled.
   - 4.9152 GS/s converter sampling.
   - Decimation 8.
   - Four 128-bit real AXI streams.
5. Preserve the common 76.8 MHz `clk_adc0` connection for both RFDC AXI stream
   clock inputs, the PPS adapter, and the PPS ILA.
6. Preserve platform clock IDs 1 through 4 and all five AXI stream tags.

The driver also writes
`rfsoc_adc_hardware_2025_2_migrated.tcl` beside the generated project. Keep
this file with the first Vivado log so any rejected 2023.2.1 property can be
traced to the exact adapted input.

Run the independent design checker against the 2025.2 driver:

```bash
vivado -mode batch \
  -source src/vitis_adc_platform/check_rfsoc_adc_bd.tcl \
  -tclargs \
    --hardware_tcl \
    "$PWD/src/vitis_adc_platform/rfsoc_adc_hardware_2025_2.tcl"
```

The checker needs `RFSOC4X2_BOARD_REPO` in its environment.

Before continuing, inspect:

```text
build/vivado_2025_2/rfsoc_adc_hardware_2025_2_ip_status.rpt
```

Do not automatically accept an RFDC configuration change. Compare every
enabled slice, sampling rate, decimation mode, data width, output clock, and
AXI stream port with the checker expectations.

## Phase 2: Synthesis, Implementation, and Bitstream

After Phase 1 passes:

```bash
vivado -mode batch \
  -source src/vitis_adc_platform/rfsoc_adc_hardware_2025_2.tcl \
  -tclargs \
    --output_dir "$PWD/build/vivado_2025_2_impl" \
    --build \
    --jobs 8 \
    --export_xsa "$PWD/build/rfsoc_adc_hardware_2025_2.xsa"
```

Archive these reports before changing constraints or IP settings:

- Synthesis utilization and timing.
- Post-route timing summary.
- DRC and methodology reports.
- Clock interaction report.
- RFDC and PPS ILA placement.

The first implementation acceptance criteria are zero errors, no new critical
warnings that affect clocks/resets/platform interfaces, and timing closure on
all generated clocks, including the 76.8 MHz RFDC-connected kernel clock.

## Phase 3: PetaLinux 2025.2

Create a fresh PetaLinux 2025.2 project from the new XSA. Do not upgrade the
2023.2 project in place. Reapply the existing SPI, Ethernet, rootfs, XRT, and
device-tree configuration deliberately, then record the actual 2025.2 sysroot
path instead of assuming the old `cortexa72-cortexa53-xilinx-linux` name.

## Phase 4: Vitis Platform

Run the new platform script from the Vitis 2025.2 environment:

```bash
export RFSOC4X2_VITIS_WORKSPACE=/absolute/path/to/workspace_2025_2
export RFSOC4X2_XSA="$PWD/build/rfsoc_adc_hardware_2025_2.xsa"
export RFSOC4X2_LINUX_IMAGE_DIR=/absolute/path/to/rfsoc-linux/images/linux

vitis -s src/vitis_adc_platform/create_rfsoc_adc_vitis_platform_2025_2.py
```

The script intentionally stops with an API-specific error if the installed
2025.2 domain object no longer supports `add_boot_dir()` or `add_bif()`.
Resolve such an error against the installed API reference:

```text
<VITIS_INSTALL>/cli/api_docs/build/html/vitis.html
```

After the platform builds, use `platforminfo` to verify clock ID 3 and the five
stream tags before creating an application.

## Phase 5: HLS and Hardware Validation

Build the dummy-BDT kernel first. Preserve:

- Kernel clock: 76.8 MHz.
- `II=1` acquisition and writeout loops.
- Four RFDC stream connections plus `PPS_TRIG_AXIS`.
- One 512-bit `gmem0` output buffer.
- 2048 capture words plus one metadata word.

Only enable `USE_CONIFER_BDT` after the dummy build works. The real BDT depends
on ignored, externally generated files in `csi_bdt_prj_kv260/firmware`; pin or
archive `BDT.h`, `BDT.cpp`, and `parameters.h` before calling the port
reproducible.

Board acceptance tests are the existing reference-clock, PPS/ILA, four-channel
continuity, cross-tile phase, power-cycle, XRT, and BDT timing checks in
`vitis_adc_platform.md`.
