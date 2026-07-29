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
  `hw_design`, `generate_bif`, and `set_boot_dir` platform APIs and targets
  `psu_cortexa53_0`.
- Hardware emulation is deferred. It did not work for `xczu48dr` in the
  existing 2023.2.1 flow.

The hardware migration driver has now recreated and validated the block design
and exported a pre-synthesis extensible XSA in Vivado 2025.2. A fresh
PetaLinux 2025.2 project has built successfully with XRT, ZOCL, the installed
SDK sysroot, user-mode SPI, and the corrected RFSoC4x2 SPI, SD, and Ethernet
device-tree nodes. Vitis 2025.2 has also built and exported the
`rfsoc_adc_vitis_platform_2025_2` platform with FSBL, PMU firmware, and Linux
`xrt` domains; the reported platform build status was zero. Independent
`platforminfo` inspection confirmed `clk_adc0` as clock ID 3 at 76.8 MHz,
`clk_adc2` as clock ID 4 at 76.8 MHz, and all five platform stream tags:
`RFDC_DATA_AXIS`, `RFDC_TRIG_AXIS`, `RFDC_ADC_B_AXIS`,
`RFDC_ADC_A_AXIS`, and `PPS_TRIG_AXIS`.

The dummy kernel has now completed Vitis 2025.2 HLS synthesis and XO
packaging. The 13.02 ns target produced a 9.505 ns top-level estimate;
`capture_candidate` achieved `II=1` with a 5.682 ns estimate, and
`write_triggered_waveform` achieved `II=1` with a 9.505 ns estimate and the
expected 2052-cycle latency. The next gate is Vitis hardware linking and
implementation against the exported platform. System packaging and board
validation remain pending.

## Confirmed 2025.2 Migration Findings

- `LIBRARY` is read-only on the generated `system.bd` file in Vivado 2025.2.
  The migration driver omits the legacy exported assignment; the project
  retains Vivado's automatically selected `xil_defaultlib`.
- The 2023.2.1 project export suppresses all status, informational, warning,
  and critical-warning messages. The migration driver omits those session
  filters so IP, DRC, CDC, and implementation diagnostics remain visible.
- Vitis 2025.2 `Domain` objects no longer provide the 2023.2
  `add_boot_dir()` and `add_bif()` methods. The working flow calls
  `generate_bif()` and `set_boot_dir(path=<PetaLinux images/linux>)`.
- The legacy PPS ILA probes the exported `m_axis_tready` signal directly.
  Vitis reconstructs that AXIS connection while extending the platform and
  leaves the native ILA tap unconnected, causing `VPL 16-213` at
  implementation. The 2025.2 migration removes only the ready probe and uses
  four fully connected probes: synchronized PPS, AXIS level, AXIS valid, and
  reset.

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

This Phase 1 XSA is intentionally an extensible, pre-synthesis hardware
platform. It is ready for PetaLinux hardware-description import and Vitis
platform creation without first running synthesis or implementation. Vitis
links the acceleration kernel into this platform and generates the implemented
hardware later.

It is not yet a board-programming artifact: it contains no implemented kernel
design or final bitstream. Complete Vitis linking, implementation, packaging,
and the hardware validation phases before attempting to boot or program it.

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

## Phase 2: Optional Base-Platform Implementation Validation

This phase is recommended for isolating base-design timing, DRC, and placement
problems, but it is not required before PetaLinux import or Vitis platform
creation. The normal extensible-platform flow implements the combined design
after Vitis links the acceleration kernel.

To validate the base design independently after Phase 1:

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

Source PetaLinux 2025.2, then run these commands from the repository root:

```bash
export RFSOC4X2_XSA="$PWD/build/rfsoc_adc_hardware_2025_2.xsa"
export RFSOC4X2_REPOSITORY="$PWD"
export RFSOC4X2_PETALINUX_PROJECT="$PWD/build/rfsoc-linux-2025_2"

petalinux-create project \
  --template zynqMP \
  -n "$RFSOC4X2_PETALINUX_PROJECT"

cd "$RFSOC4X2_PETALINUX_PROJECT"
petalinux-config --get-hw-description "$RFSOC4X2_XSA"
```

In the project configuration, select an EXT4 root filesystem and save. Copy
the versioned board additions over the generated user device tree:

```bash
cp "$RFSOC4X2_REPOSITORY/src/petalinux_2025_2/system-user.dtsi" \
  project-spec/meta-user/recipes-bsp/device-tree/files/system-user.dtsi
```

Run `petalinux-config -c rootfs` and preserve these 2023.2 requirements while
checking their exact 2025.2 package names:

- `rfdc`
- Vitis acceleration/XRT essential runtime and development package groups
- OpenAMP/libmetal runtime and development package groups
- Python modules
- OpenSSH server and SCP support
- Package management and debug tweaks

Ensure `CONFIG_rfdc` is present in
`project-spec/meta-user/conf/user-rootfsconfig`. Run
`petalinux-config -c kernel` and enable the user-mode SPI device driver.

The RFSoC4x2 DP83867 PHY must be a child of the GEM1 `mdio` node. The
versioned `system-user.dtsi` supplies `#address-cells = <1>` and
`#size-cells = <0>` on that node so the PHY address `reg = <0xf>` has the
correct format. Do not move the PHY directly under `&gem1`; doing so makes it
inherit the GEM register format and produces `dtc` `reg_format` warnings.

Build the image and install its SDK sysroot:

```bash
petalinux-build
petalinux-build --sdk
petalinux-package --sysroot
```

Before Phase 4, confirm that `images/linux` contains:

```text
bl31.elf
boot.scr
pmufw.elf
system.dtb
u-boot.elf
zynqmp_fsbl.elf
```

Also retain `Image`, `rootfs.ext4`, `sdk.sh`, and the installed SDK directory
for application compilation and packaging.

Decompile the final DTB and check the board-level nodes before creating the
Vitis platform:

```bash
dtc -I dtb -O dts images/linux/system.dtb -o /tmp/rfsoc4x2-final.dts
grep -nE \
  'bootargs|spi@ff040000|lmk@0|lmxdac@1|lmxadc@2|ethernet@ff0c0000|mdio|ethernet-phy@f' \
  /tmp/rfsoc4x2-final.dts
```

The decompile must not report a `reg_format` warning for the Ethernet PHY.

## Phase 4: Vitis Platform

Run the new platform script from the Vitis 2025.2 environment:

```bash
export RFSOC4X2_VITIS_WORKSPACE=/absolute/path/to/workspace_2025_2
export RFSOC4X2_XSA="$PWD/build/rfsoc_adc_hardware_2025_2.xsa"
export RFSOC4X2_LINUX_IMAGE_DIR=/absolute/path/to/rfsoc-linux/images/linux

vitis -s src/vitis_adc_platform/create_rfsoc_adc_vitis_platform_2025_2.py
```

Do not invoke this file with `python` or `python3`. Sourcing the Vitis settings
script places the Vitis launcher on `PATH`, but the `vitis` Python API is
provided by the launcher's embedded interpreter. Verify the selected launcher
before running the script:

```bash
command -v vitis
vitis -v
```

Both commands must resolve to the intended 2025.2 installation. If
`vitis -s ...` itself reports `No module named 'vitis'`, the selected launcher
is incomplete or belongs to a different installation; inspect all candidates
with `type -a vitis` and source the settings script from the matching full
Vitis 2025.2 installation.

The script uses the Vitis 2025.2 Linux-domain resource API:
`domain.generate_bif()` followed by
`domain.set_boot_dir(path=<PetaLinux images/linux>)`. The older
`add_boot_dir()` and `add_bif()` methods are not available in Vitis 2025.2.
Resolve any further API-specific error against the installed API reference:

```text
<VITIS_INSTALL>/cli/api_docs/build/html/vitis.html
```

After the platform builds, use `platforminfo` to verify clock IDs 3 and 4 and
the five stream tags before creating an application.

## Phase 5: HLS and Hardware Validation

Build the dummy-BDT kernel first. Preserve:

- Kernel clock: 76.8 MHz.
- `II=1` acquisition and writeout loops.
- Four RFDC stream connections plus `PPS_TRIG_AXIS`.
- One 512-bit `gmem0` output buffer.
- 2048 capture words plus one metadata word.

The repository provides separate Vitis 2025.2 HLS and link configurations:

- `src/vitis_adc_platform/dummy_kernel_hls_2025_2.cfg`
- `src/vitis_adc_platform/dummy_kernel_link_2025_2.cfg`

Run the flow from the repository root after sourcing the Vitis 2025.2
environment. Set `RFSOC4X2_XPFM` to the exported platform file, not its project
directory:

```bash
export RFSOC4X2_XPFM=\
/absolute/path/to/rfsoc_adc_vitis_platform_2025_2.xpfm

mkdir -p build/vitis_dummy_kernel_2025_2

v++ -c --mode hls \
  --platform "$RFSOC4X2_XPFM" \
  --freqhz=76800000 \
  --config src/vitis_adc_platform/dummy_kernel_hls_2025_2.cfg \
  --work_dir build/vitis_dummy_kernel_2025_2/hls

test -s build/vitis_dummy_kernel_2025_2/dummy_kernel.xo
```

Vitis 2025.2 HLS mode uses `freqhz` when an HLS component targets a platform.
Do not copy the legacy `[hls] clock=76800000:dummy_kernel` setting into this
configuration. The HLS configuration packages the `.xo` as part of C
synthesis. Vitis 2025.2 resolves `syn.file` from the parent of `--work_dir`,
but resolves `package.output.file` from the HLS configuration file's
directory. The checked-in relative paths account for these two bases and place
the `.xo` in `build/vitis_dummy_kernel_2025_2`.

Review the generated HLS synthesis report before linking. In particular,
confirm a 76.8 MHz target and `II=1` for the acquisition and waveform-write
pipelines. Then run the hardware link:

The first Vitis 2025.2 HLS run passed these checks: target 13.02 ns,
top-level estimate 9.505 ns, `capture_candidate` estimate 5.682 ns with
achieved `II=1`, and `write_triggered_waveform` estimate 9.505 ns with
achieved `II=1`. Its 2052-cycle, 26.719 us writeout latency is consistent with
the 76.8 MHz target. The unknown latency of the outer
`capture_external_trigger` loop is intentional because it waits for an
external PPS edge and may retry a rejected candidate.

```bash
v++ -l -t hw \
  --platform "$RFSOC4X2_XPFM" \
  --config src/vitis_adc_platform/dummy_kernel_link_2025_2.cfg \
  --temp_dir build/vitis_dummy_kernel_2025_2/link \
  --log_dir build/vitis_dummy_kernel_2025_2/logs \
  --save-temps \
  -o build/vitis_dummy_kernel_2025_2/dummy_kernel.xclbin \
  build/vitis_dummy_kernel_2025_2/dummy_kernel.xo

test -s build/vitis_dummy_kernel_2025_2/dummy_kernel.xclbin
```

The link configuration explicitly names the single compute unit
`dummy_kernel_1`, binds it to platform clock ID 3, and connects all five
platform streams. It intentionally omits an `sp` mapping for `buffer0`; Vitis
automatically selects an available platform memory resource when no explicit
mapping is supplied. Record that generated mapping from the link report before
deciding whether to pin it.

If implementation reports `VPL 16-213` for
`system_i/ila_pps_trigger/probe3`, the XPFM was generated from the legacy
five-probe ILA. Pull the four-probe migration fix, regenerate the extensible
XSA in a fresh Vivado output directory, and rebuild the Vitis platform in a
fresh workspace. The PetaLinux image does not need to be rebuilt because this
change only removes an internal debug tap; reuse the verified
`images/linux` directory. The existing dummy-kernel `.xo` is also reusable.

Archive the Vitis and Vivado link reports. The first link is accepted only if
it finishes without errors, meets timing on the 76.8 MHz kernel clock, and
contains exactly the expected stream connections. Inspect the resulting
container with:

```bash
xclbinutil --info \
  --input build/vitis_dummy_kernel_2025_2/dummy_kernel.xclbin
```

Cross-compile the Linux host with the SDK generated by the matching PetaLinux
2025.2 project. The host uses the native XRT C++ API, following the 67DR
project, so it does not depend on the legacy `xcl2.hpp`, OpenCL host wrappers,
or HLS `ap_int.h`.

```bash
cd /home/neutrino/work/rfsoc4x2

conda deactivate 2>/dev/null || true
unset LD_LIBRARY_PATH PYTHONPATH PYTHONHOME
source build/rfsoc-linux-2025_2/images/linux/sdk/\
environment-setup-cortexa72-cortexa53-amd-linux

$CXX $CXXFLAGS -std=c++17 -O2 -Wall -Wextra \
  -o build/vitis_dummy_kernel_2025_2/test_adc \
  src/vitis_adc_platform/host.cpp \
  $LDFLAGS -lxrt_coreutil -pthread

file build/vitis_dummy_kernel_2025_2/test_adc
test -x build/vitis_dummy_kernel_2025_2/test_adc
```

`file` must report an ARM AArch64 executable. Copy it beside the matching
linked xclbin on the FAT32 boot partition; this userspace-only addition does
not require rebuilding PetaLinux, the platform, or the xclbin.

```bash
sudo mkdir -p /mnt/rfsoc4x2-boot
sudo mount /dev/sda1 /mnt/rfsoc4x2-boot
sudo install -m 0755 \
  build/vitis_dummy_kernel_2025_2/test_adc \
  /mnt/rfsoc4x2-boot/test_adc
sync
sudo umount /mnt/rfsoc4x2-boot
```

The verified rootfs contains `python3-core` and `python3-setuptools`, but not
`python3-pip`. The checked-in `xrfclk` archive is pure Python and can be used
directly without installing it. After the first board boot:

```bash
BOOT_DIR=$(findmnt -rn -S /dev/mmcblk0p1 -o TARGET)
test -n "$BOOT_DIR"
cd /home/root
tar -xzf "$BOOT_DIR/xrfclk-2.0.tar.gz"
cp "$BOOT_DIR/set_ref_clocks.py" .
modprobe spidev
PYTHONPATH=/home/root/xrfclk-2.0 python3 ./set_ref_clocks.py
ls /dev/spidev*
```

Only enable `USE_CONIFER_BDT` after the dummy build works. The real BDT depends
on ignored, externally generated files in `csi_bdt_prj_kv260/firmware`; pin or
archive `BDT.h`, `BDT.cpp`, and `parameters.h` before calling the port
reproducible.

Board acceptance tests are the existing reference-clock, PPS/ILA, four-channel
continuity, cross-tile phase, power-cycle, XRT, and BDT timing checks in
`vitis_adc_platform.md`.
