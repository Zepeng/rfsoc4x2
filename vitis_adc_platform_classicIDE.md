# A Vitis Extensible Platform with Four ADC Streams and External PPS Trigger for RFSoC4x2 (Vitis 2023.1 Classic IDE)
This is my second experiment with the RFSoC4x2 board. The goal is to build a simple Vitis extensible platform that captures four ADC streams from the ZU48DR device on board while using the board `1PPS` SMA input as the FPGA trigger source.

The current HLS kernel reads ADC_D, ADC_C, ADC_B, and ADC_A in lockstep, triggers on a rising edge from `PPS_TRIG_AXIS`, and writes all four ADC channels to memory with about 20% pretrigger and 80% post-trigger samples. The static Vivado platform details for the PPS adapter and ILA are described in the [external PPS trigger guide](vitis_adc_platform_pps_trigger.md).

## Workspace for This Rebuild
These instructions use a fresh Linux workspace:

```shell
export WORKSPACE=/path/to/workspace_4ch
mkdir -p "$WORKSPACE"
cd "$WORKSPACE"
```

Copy the updated project files from this repository into the workspace before rebuilding Vivado or Vitis. Replace `/path/to/rfsoc4x2` with the checkout path on the Linux build machine:

```shell
export REPO=/path/to/rfsoc4x2
cp "$REPO/src/vitis_adc_platform/rfsoc_adc_hardware.tcl" "$WORKSPACE/"
cp "$REPO/src/vitis_adc_platform/pps_trigger_axis.v" "$WORKSPACE/"
cp "$REPO/src/vitis_adc_platform/pps_trigger.xdc" "$WORKSPACE/"
cp "$REPO/src/vitis_adc_platform/check_rfsoc_adc_bd.tcl" "$WORKSPACE/"
cp "$REPO/src/vitis_adc_platform/dummy_kernel.cpp" "$WORKSPACE/"
cp "$REPO/src/vitis_adc_platform/host.cpp" "$WORKSPACE/"
```

After Vitis creates the `test_adc` projects, copy `dummy_kernel.cpp` into `test_adc_kernels/src/` and `host.cpp` into `test_adc/src/`, or replace those files through the Vitis GUI as described below. All XSCT and Vitis commands in this guide use `/path/to/workspace_4ch`; do not mix it with an older workspace because Vitis can reuse stale platform clock and stream metadata.

## Step 0: Install the RFSoC4x2 board files
If not already installed, follow [Steps 0.1 and 0.2 in the previous experiment](./vitis_base_platform.md#step-0-install-the-rfsoc4x2-board-files-and-xilinxs-repos) to install the RFSoC board files. There is no need to install the Xilinx's device tree repo and the ZYNQMP common image here. We will use [Petalinux](https://www.xilinx.com/products/design-tools/embedded-software/petalinux-sdk.html#tools) to generate a new image and a device tree. 

## Step 1: Create a Vivado Hardware Design
1. Download the TCL script [rfsoc_adc_hardware.tcl](src/vitis_adc_platform/rfsoc_adc_hardware.tcl) to `/path/to/workspace_4ch`.
2. Open Vivado and source the TCL script in a TCL shell, or simply do
   ```bash
   cd /path/to/workspace_4ch
   vivado -source rfsoc_adc_hardware.tcl
   ```
   to generate the following block design:
   ![hardware design](Figures/block_design_adc_platform.png)
   which adds an [RF Data Converter](https://www.xilinx.com/products/intellectual-property/rf-data-converter.html#overview) IP to a slightly modified version of the hardware design in [Vitis Platform Creation Tutorial for
ZCU104-Step 1](https://github.com/Xilinx/Vitis-Tutorials/blob/2023.1/Vitis_Platform_Creation/Design_Tutorials/02-Edge-AI-ZCU104/step1.md).
   - The Vivado project is named `rfsoc_adc_hardware`.
   - ADC tiles 0 and 2 are enabled with converter sampling rate set to 4.9152 GSps and decimation set to 8, giving 614.4 MS/s on each exported real ADC stream.
   - `m00_axis`, `m02_axis`, `m20_axis`, and `m22_axis` are exported for the four-stream dummy kernel. Each AXI4-Stream beat contains eight consecutive signed 16-bit real samples.
   - The Vitis platform stream tags are `RFDC_DATA_AXIS` for `m00_axis`, `RFDC_TRIG_AXIS` for `m02_axis`, `RFDC_ADC_B_AXIS` for `m20_axis`, `RFDC_ADC_A_AXIS` for `m22_axis`, and `PPS_TRIG_AXIS` for the PPS trigger adapter.
   - Tile 0 `clk_adc0` is the common RFDC AXI4-Stream clock and is exported as fixed platform clock ID `3`. Both `m0_axis_aclk` and `m2_axis_aclk` use this `76.8 MHz` clock, so all four streams can feed one `II=1` HLS capture loop without an inserted clock-domain crossing. Tile 2 `clk_adc2` remains exported as fixed clock ID `4` for later use.

3. Before running synthesis, optionally verify the block design and Vitis platform metadata in batch mode. From a checkout of this repository, run:
   ```bash
   vivado -mode batch -source /path/to/rfsoc4x2/src/vitis_adc_platform/check_rfsoc_adc_bd.tcl \
     -tclargs --hardware_tcl /path/to/workspace_4ch/rfsoc_adc_hardware.tcl
   ```
   The checker creates a temporary project, sources `rfsoc_adc_hardware.tcl`, validates the block design, and should end with:
   ```
   PFM m00_axis sptag = RFDC_DATA_AXIS
   PFM m02_axis sptag = RFDC_TRIG_AXIS
   PFM m20_axis sptag = RFDC_ADC_B_AXIS
   PFM m22_axis sptag = RFDC_ADC_A_AXIS
   m0_axis_aclk net = usp_rf_data_converter_0_clk_adc0
   m2_axis_aclk net = usp_rf_data_converter_0_clk_adc0
   PFM clk_adc0 = id 3, status fixed, freq_hz 76800000
   PFM clk_adc2 = id 4, status fixed, freq_hz 76800000
   CHECK PASSED: four 614.4 MS/s ADC streams plus PPS_TRIG_AXIS and PPS ILA use common clk_adc0
   ```
   This check does not require synthesis or implementation.

4. Run synthesis, implementation, and bitstream generation. From the Vivado Tcl console:
   ```tcl
   launch_runs impl_1 -to_step write_bitstream -jobs 8
   wait_on_run impl_1
   open_run impl_1
   write_hw_platform -fixed -include_bit -force \
     /path/to/workspace_4ch/rfsoc_adc_hardware/rfsoc_adc_hardware.xsa
   ```
   Vitis will not see the new RFDC `Data_Width=8`, `clk_adc0=76.8 MHz`, or stream metadata until the `.xsa` is regenerated from the updated Vivado design.

## Step 2: Use Petalinux to create boot files, device tree file, linux image, rootfs, and sysroot
1. Create a Petalinux project: 
   ```shell
   cd /path/to/workspace_4ch
   petalinux-create -t project --template zynqMP -n rfsoc-linux
   cd rfsoc-linux
   ```
2. Enter the hardware platform `rfsoc_adc_hardware.xsa` and select EXT4 for rootfs:
   ```shell
   petalinux-config --get-hw-description=../rfsoc_adc_hardware/rfsoc_adc_hardware.xsa
   ```
   - Select **<em>Image Packaging Configuration->Root filesystem type->EXT4</em>**
   - Exit and save configuration
3. Add relevant libraries to rootfs:
   - Add the following line to `/path/to/workspace_4ch/rfsoc-linux/project-spec/meta-user/conf/user-rootfsconfig`:
     ```
     CONFIG_rfdc
     ```
     to allow including the `rfdc` library (we don't use it in this experiment though)
   - Run
     ```shell
     petalinux-config -c rootfs
     ```
   - Select **<em>user packages->rfdc</em>**  
   - Select `xrt`:
     - **<em>Petalinux Package Groups->packagegroup-petalinux-vitis-acceleration-essential->packagegroup-petalinux-vitis-acceleration-essential</em>**
     - **<em>Petalinux Package Groups->packagegroup-petalinux-vitis-acceleration-essential->packagegroup-petalinux-vitis-acceleration-essential-dev</em>**
   - Select `libmetal` (mostly for `rfdc`):
     - **<em>Petalinux Package Groups->packagegroup-petalinux-openamp->packagegroup-petalinux-openamp</em>**
     - **<em>Petalinux Package Groups->packagegroup-petalinux-openamp->packagegroup-petalinux-openamp-dev</em>**
   - Select Python (to run some PYNQ scripts later):
     - **<em>Petalinux Package Groups->packagegroup-petalinux-python-modules->packagegroup-petalinux-python-modules</em>**
     - **<em>Petalinux Package Groups->packagegroup-petalinux-python-modules->packagegroup-petalinux-python-modules-dev</em>**
   - Select `openssh` for convenience:
     - **<em>Filesystem Packages->console->network->openssh->openssh, openssh-ssh, openssh-sshd, openssh-scp</em>**
   - Select **<em>Image Features->package-management</em>** and **<em>Image Features->debug-tweaks</em>**
   - Select any other packages as wish
   - Exit and save
4. Configure the Linux kernel:
   ```shell
   petalinux-config -c kernel
   ```
   - Allow user-mode SPI device driver support:
     - Select **<em>Device Drivers->SPI support->User mode SPI device driver support</em>** (select the * mark)
   - Exit and save
5. Add device tree descriptions to enable access to the reference clock chips (LMK04828 and LMX2594) via SPI:
   - Add the following lines to `/path/to/workspace_4ch/rfsoc-linux/project-spec/meta-user/recipes-bsp/device-tree/files/system-user.dtsi`:
     ```
     /include/ "system-conf.dtsi"
     / {
        chosen {
                bootargs = " earlycon console=ttyPS0,115200 clk_ignore_unused root=/dev/mmcblk0p2 rootwait rw sdhci.debug_quirks2=4";
                stdout-path = "serial0:115200n8";
        };
     };

     &sdhci0 {
                no-1-8-v;
     };

     &spi0 {
        status = "okay";

        lmk@0 {
                compatible = "ti,lmk04828";
                reg = <0x0>;
                spi-max-frequency = <500000>;
                num_bytes = <3>;
        };
        lmxdac@1 {
                compatible = "ti,lmx2594";
                reg = <0x1>;
                spi-max-frequency = <500000>;
                num_bytes = <3>;
        };
        lmxadc@2 {
                compatible = "ti,lmx2594";
                reg = <0x2>;
                spi-max-frequency = <500000>;
                num_bytes = <3>;
        };
     };
     ```
6. Build the image and sysroot:
   ```bash
   petalinux-build
   petalinux-build --sdk
   cd images/linux
   ./sdk.sh -d .
   ```
   - The boot files, device tree file, kernel image, and the EXT4 rootfs are generated in `/path/to/workspace_4ch/rfsoc-linux/images/linux/`. The sysroot is in `/path/to/workspace_4ch/rfsoc-linux/images/linux/sysroots/cortexa72-cortexa53-xilinx-linux`.

   If you are only changing the PL RFDC stream export described in Step 1 and already have a working PetaLinux image for this platform, you can usually reuse it. Rebuild PetaLinux only when PS configuration, the address map, device tree requirements, kernel configuration, rootfs contents, or boot files change.
     
## Step 3: Create a Vitis Platform 
1. Create a Vitis Platform project:
 - Start `xsct`:
   ```shell
   cd /path/to/workspace_4ch
   xsct
   ```
 - Once in the `xsct` terminal, execute the following commands to create a Vitis platform project:
   ```tcl
   setws .
   platform create -name rfsoc_adc_vitis_platform \
       -desc "RFSoC4x2 ADC platform with data and trigger ADC streams" \
       -hw rfsoc_adc_hardware/rfsoc_adc_hardware.xsa \
       -hw_emu rfsoc_adc_hardware/rfsoc_adc_hardware.xsa \
       -no-boot-bsp -out .
   domain create -name xrt -proc psu_cortexa53 -os linux \
       -arch {64-bit} -runtime {ocl}  -bootmode {sd}
   platform write
   platform generate
   exit
   ```
   The platform project is now created in `/path/to/workspace_4ch/rfsoc_adc_vitis_platform`.

   If you previously built the single-stream version or a platform without RFDC clock IDs `3` and `4`, create a fresh platform project or delete the old `/path/to/workspace_4ch/rfsoc_adc_vitis_platform` first. This avoids Vitis using cached stream or clock metadata. After exporting a new `.xsa`, the Vitis platform must be regenerated before the application project is configured or rebuilt.

2. Copy `system.dtb` and boot files from the image generated by Petalinux in Step 2 above:
 - Make the following two directories for convenience:
   ```shell
   cd rfsoc_adc_vitis_platform
   mkdir boot fat32
   ```
 - Copy `system.dtb` and other boot files to the directories:
   ```shell
   cp /path/to/workspace_4ch/rfsoc-linux/images/linux/system.dtb boot
   cp /path/to/workspace_4ch/rfsoc-linux/images/linux/system.dtb fat32
   cp /path/to/workspace_4ch/rfsoc-linux/images/linux/boot.scr fat32
   cp /path/to/workspace_4ch/rfsoc-linux/images/linux/bl31.elf boot
   cp /path/to/workspace_4ch/rfsoc-linux/images/linux/u-boot.elf boot
   ```
   
3. Import the generated platform project into the XSCT workspace and build the Vitis platform:
 - Make sure the Vitis GUI is closed. A workspace can be used by either standalone `xsct` or the Vitis GUI, but not both at the same time.
 - Start a standalone `xsct` process and import the generated platform project into the workspace metadata:
   ```shell
   cd /path/to/workspace_4ch
   xsct
   ```
   Then run:
   ```tcl
   setws /path/to/workspace_4ch
   importprojects /path/to/workspace_4ch/rfsoc_adc_vitis_platform
   exit
   ```
   If `importprojects` reports that `rfsoc_adc_vitis_platform` already exists in the workspace, continue. The platform is already registered.
 - Open the Vitis GUI with the same workspace used by `xsct`:
   ```shell
   vitis -workspace /path/to/workspace_4ch
   ```
 - If `rfsoc_adc_vitis_platform` does not appear in the **<em>Explorer</em>** window after the XSCT import, import it from the GUI:
   - Select **<em>File->Import...</em>**.
   - Select **<em>General->Existing Projects into Workspace</em>** and click **<em>Next</em>**.
   - Set **<em>Select root directory</em>** to `/path/to/workspace_4ch`.
   - Enable **<em>Search for nested projects</em>** if that option is shown.
   - Select `rfsoc_adc_vitis_platform`.
   - Leave **<em>Copy projects into workspace</em>** unchecked because the project is already under `/path/to/workspace_4ch`.
   - Click **<em>Finish</em>**.
 - Set the platform parameters:
   - Open `platform.spr` from the **<em>Explorer</em>** window (**<em>right-click->Open</em>**)
   - Set the paths to `fsbl.elf` and `pmufw.elf`: 
     - `FSBL`: Click the `Browse` button to select `/path/to/workspace_4ch/rfsoc-linux/images/linux/zynqmp_fsbl.elf`
     - `PMU Firmware`: Click the `Browse` button to select `/path/to/workspace_4ch/rfsoc-linux/images/linux/pmufw.elf`
   - Select `xrt` in the opened tab in the main window
   - Under `Domain:xrt` field:
     - `Bif File:` Click downarrow in the `Browse` button to select `Generate Bif`.
     - `Boot Components Directory:` Click the `Browse` button to select `/path/to/workspace_4ch/rfsoc_adc_vitis_platform/boot`.
     - `FAT32 Partition Directory:` Click the `Browse` button to select `/path/to/workspace_4ch/rfsoc_adc_vitis_platform/fat32`.
     - `Display Name:` Change as wish.
     - `Description:` Change as wish.
     - **Leave `Linux Rootfs:` and `Sysroot Directory:` empty**.
 - Build the platform by click the :hammer: button on the tool bar.
   After the build, the built Vitis platform is in `/path/to/workspace_4ch/rfsoc_adc_vitis_platform/export/rfsoc_adc_vitis_platform`.
 - Verify that the exported platform exposes RFDC tile 0 clock ID `3` as a fixed `76.8 MHz` clock before creating the application:
   ```shell
   platforminfo -v -p \
     /path/to/workspace_4ch/rfsoc_adc_vitis_platform/export/rfsoc_adc_vitis_platform/rfsoc_adc_vitis_platform.xpfm | \
     sed -n '/Clock Information/,/Memory Information/p'
   ```
   The clock list must include clock ID `3` with status `fixed` and frequency `76800000`. Do not continue to the application build if clock ID `3` is missing or reported as a scaled clock.
 - Fix the `linux.bif` file:
   - Select and open the `rfsoc_adc_vitis_platform/export/rfsoc_adc_vitis_platform/sw/rfsoc_adc_vitis_platform/boot/linux.bif` file from the **<em>Explorer</em>**.
   - Change the bootloader and PMU firmware lines to concrete file paths. Do not keep the angle brackets; Bootgen treats them as BIF syntax, not placeholders. The lines should be:
     ```
     [bootloader] /path/to/workspace_4ch/rfsoc_adc_vitis_platform/boot/fsbl.elf
     [pmufw_image] /path/to/workspace_4ch/rfsoc_adc_vitis_platform/boot/pmufw.elf
     ```
   - If this `linux.bif` file is regenerated later, repeat this edit before rebuilding the platform or packaging the system project.

## Step 4: Test the Vitis Platform
1. Create a new Vitis application project from template. A fresh application project is recommended after changing the platform interface:
   - Add Vitis example templates:
     - Go to **<em>Vitis->Examples...</em>** to install example templates
     - Click the `Download` button to install the templates from the **<em>Vitis Accel Examples Repository</em>**
     - Only need to do this once
   - Go to **<em>File->New->Application Project...</em>** to create a new application project:
     - Select the regenerated `rfsoc_adc_vitis_platform` created in Step 3. If the platform doesn't show up as a choice, press the **+** button and select `/path/to/workspace_4ch/rfsoc_adc_vitis_platform/export/rfsoc_adc_vitis_platform/rfsoc_adc_vitis_platform.xpfm`. Press the `Next>` button.
     - Name the project `test_adc`. Press the `Next>` button.
     - Under `Application settings` field:
       - `Sysroot path:` Click the `Browse` button to select `/path/to/workspace_4ch/rfsoc-linux/images/linux/sysroots/cortexa72-cortexa53-xilinx-linux`.
       - `Root FS:` Click the `Browse` button to select `/path/to/workspace_4ch/rfsoc-linux/images/linux/rootfs.ext4`.
       - `Kernel Image:` Click the `Browse` button to select `/path/to/workspace_4ch/rfsoc-linux/images/linux/Image`.
       - Press the `Next>` button.
   - Select **<em>Acceleration templates with PL and AIE accelerators->Host Examples->Data Transfer (C)</em>** to finish up the application project creation step.
  
2. Replace the template sources with the four-stream sources:
   If reusing an existing `test_adc` application project, reconfigure it against the regenerated `rfsoc_adc_vitis_platform` first. Then replace the kernel and host sources and update the V++ connectivity below. A project created for an older platform does not have the current four-stream kernel interface.
   - Under the **<em>Explorer</em>** window, replace the file `test_adc_kernels/src/dummy_kernel.cpp` in the template with this [`dummy_kernel.cpp`](src/vitis_adc_platform/dummy_kernel.cpp).
   - Replace the file `test_adc/src/host.cpp` file in the template with this [`host.cpp`](src/vitis_adc_platform/host.cpp).
   - Refresh the projects in the **<em>Explorer</em>** window if Vitis does not immediately show the modified files.
   - Compile the HLS kernel for the RFDC tile 0 AXI4-Stream clock. Open the Hardware build settings for `test_adc_kernels`, select `dummy_kernel`, and add the following lines to its **<em>V++ configuration settings</em>** field:
     ```
     [hls]
     clock=76800000:dummy_kernel
     ```
     Leave **<em>V++ command line options</em>** empty.
     This option affects the HLS-generated `.xo`. The separate `[clock] id=3:dummy_kernel_1` setting below must also remain present so the linker connects the kernel instance directly to the native `clk_adc0` stream clock exported by the platform.
     Do not bind this streaming kernel to the unrelated `400 MHz` PL clock merely because it is faster. Each RFDC producer emits one 128-bit word per `clk_adc0` cycle at `76.8 MHz`. This preserves the proven eight-sample real RFDC word format while decimation 8 reduces the per-channel sample rate to `614.4 MS/s`.
   - The kernel arguments are now:
     - `buffer0`: output buffer in DDR.
     - `data_in`: ADC_D stream connected to `RFDC_DATA_AXIS`.
     - `trigger_in`: ADC_C stream connected to `RFDC_TRIG_AXIS`.
     - `adc_b_in`: ADC_B stream connected to `RFDC_ADC_B_AXIS`.
     - `adc_a_in`: ADC_A stream connected to `RFDC_ADC_A_AXIS`.
     - `ext_trigger_in`: external PPS trigger stream connected to `PPS_TRIG_AXIS`.
     - `size`: number of 128-bit AXI4-Stream words to capture from each stream. The current kernel requires `2048`.
     - `output_words`: number of packed 512-bit output words available in `buffer0`.
     The host code sets `size` as kernel argument index `6`, because the five AXIS inputs precede the scalar arguments.
     The kernel continuously writes all four ADC streams into one full-frame circular UltraRAM buffer through one uninterrupted `II=1` acquisition loop. After a rising edge on `PPS_TRIG_AXIS` and the 80% post-trigger interval, it freezes the ring and copies the chronological 2048-word waveform to DDR as packed 512-bit words.

3. Configure the hardware link for the four RFDC streams plus PPS trigger stream:
   - Open `test_adc_system_hw_link/test_adc_system_hw_link.prj` from the **<em>Explorer</em>**.
   - Under **<em>Hardware Functions</em>**, right-click `dummy_kernel` and select **<em>Edit V++ Options...</em>**.
   - Remove any old connectivity lines that mention `RFDC_AXIS` or `dummy_kernel_1.s_in`.
   - Add the following lines to the `V++ configuration settings` field:
     ```
     [clock]
     id=3:dummy_kernel_1

     [connectivity]
     stream_connect = RFDC_DATA_AXIS:dummy_kernel_1.data_in
     stream_connect = RFDC_TRIG_AXIS:dummy_kernel_1.trigger_in
     stream_connect = RFDC_ADC_B_AXIS:dummy_kernel_1.adc_b_in
     stream_connect = RFDC_ADC_A_AXIS:dummy_kernel_1.adc_a_in
     stream_connect = PPS_TRIG_AXIS:dummy_kernel_1.ext_trigger_in
     ```
   - Click the `Apply and Close` button.
   - If Vitis assigned a different compute-unit name than `dummy_kernel_1`, use the exact instance name shown under **<em>Hardware Functions</em>** in all five `stream_connect` lines.
   - If the link step reports that clock ID `3`, an `RFDC_*_AXIS`, or `PPS_TRIG_AXIS` tag cannot be found, rebuild the Vivado design, re-export the `.xsa`, and regenerate the Vitis platform from the new `.xsa`. Clock ID `3` is the common RFDC stream clock, tile 0 `clk_adc0`, at `76.8 MHz`.
   - If the link step reports that an input such as `adc_b_in` or `ext_trigger_in` cannot be found, the HLS component is still using an older `dummy_kernel.cpp`; replace the source again and clean/rebuild the application.
   - If the `cfgen` command line still contains `-sc RFDC_AXIS:dummy_kernel_1.s_in`, the old V++ connectivity is still present. Remove that line from the hardware-link V++ options and clean the hardware-link build directory before rebuilding.

4. Configure packaging and build:
   - Open `test_adc_system.sprj` from the **<em>Explorer</em>**.
   - Select **<em>Hardware</em>** for **<em>Active build configuration</em>** at the upper-right corner.
   - Add `--package.no_image` to the `Packaging options` field to turn off generating a disk image. This still runs the package step and still requires valid boot files for BIF generation.
   - If Bootgen reports a syntax error in `/path/to/workspace_4ch/test_adc_system/Hardware/package/rfsoc_adc_vitis_platform.bif`, open that generated file and check the bootloader line. It must contain one bracketed attribute list followed by the actual FSBL file, not a directory and not a doubled bracket. For example:
     ```
     [bootloader] /path/to/workspace_4ch/rfsoc_adc_vitis_platform/boot/fsbl.elf
     [pmufw_image] /path/to/workspace_4ch/rfsoc_adc_vitis_platform/boot/pmufw.elf
     ```
     A line like `[[bootloader] /path/to/workspace_4ch/rfsoc_adc_vitis_platform/` is malformed. Fix the source `linux.bif` in the exported platform as described in Step 3, then clean and rebuild packaging so Vitis regenerates the package BIF from the corrected template.
   - If packaging reports that `export/rfsoc_adc_vitis_platform/sw/fsbl.elf` does not exist, copy the boot files from the PetaLinux image output into the platform export tree:
     ```shell
     mkdir -p /path/to/workspace_4ch/rfsoc_adc_vitis_platform/export/rfsoc_adc_vitis_platform/sw
     cp /path/to/workspace_4ch/rfsoc-linux/images/linux/zynqmp_fsbl.elf \
        /path/to/workspace_4ch/rfsoc_adc_vitis_platform/export/rfsoc_adc_vitis_platform/sw/fsbl.elf
     cp /path/to/workspace_4ch/rfsoc-linux/images/linux/pmufw.elf \
        /path/to/workspace_4ch/rfsoc_adc_vitis_platform/export/rfsoc_adc_vitis_platform/sw/pmufw.elf
     ls -l /path/to/workspace_4ch/rfsoc_adc_vitis_platform/export/rfsoc_adc_vitis_platform/sw/fsbl.elf \
           /path/to/workspace_4ch/rfsoc_adc_vitis_platform/export/rfsoc_adc_vitis_platform/sw/pmufw.elf
     ```
     If Vitis later reports missing `bl31.elf`, `u-boot.elf`, or `system.dtb`, copy those files from `/path/to/workspace_4ch/rfsoc-linux/images/linux/` to the path named in the error message.
   - Clean the system project if this workspace previously built the single-stream design.
   - Click the :hammer: button on the tool bar to build the project.
   - After rebuilding, verify that the generated HLS report targets `76.8 MHz`. For example, a roughly 2048-cycle `write_triggered_waveform` pipeline should report approximately `26.67 us`.
   - The Vitis-generated block design should connect all four exported RFDC streams and `PPS_TRIG_AXIS` directly to the corresponding `dummy_kernel_1` inputs.
   - After the build completes, verify that the generated `xclbin` contains the five-stream kernel:
     ```shell
     xclbinutil --info --input \
       /path/to/workspace_4ch/test_adc_system/Hardware/package/sd_card/dummy_kernel.xclbin | \
       grep -E "data_in|trigger_in|adc_b_in|adc_a_in|ext_trigger_in|PPS_TRIG_AXIS|dummy_kernel"
     ```
     The output should show the `dummy_kernel` signature with all five AXI4-Stream arguments, and the command line should include:
     ```
     --connectivity.stream_connect RFDC_DATA_AXIS:dummy_kernel_1.data_in
     --connectivity.stream_connect RFDC_TRIG_AXIS:dummy_kernel_1.trigger_in
     --connectivity.stream_connect RFDC_ADC_B_AXIS:dummy_kernel_1.adc_b_in
     --connectivity.stream_connect RFDC_ADC_A_AXIS:dummy_kernel_1.adc_a_in
     --connectivity.stream_connect PPS_TRIG_AXIS:dummy_kernel_1.ext_trigger_in
     ```
   - The files to deploy after a Vitis build are generated under:
     ```shell
     /path/to/workspace_4ch/test_adc_system/Hardware/package/sd_card/
     ```
     For a host or kernel change, keep the executable and xclbin as a matched pair and update both files on the SD-card boot partition:
     ```shell
     test_adc
     dummy_kernel.xclbin
     ```
     This four-channel decimation change modifies the Vivado hardware platform. For this rebuild, update the full generated SD-card boot directory, including:
     ```shell
     BOOT.BIN
     Image
     system.dtb
     boot.scr
     ```
     Do not replace the EXT4 rootfs partition for a normal Vitis-only host/kernel rebuild.
   - The following block design is generated by Vitis:
     ![vitis_generated_hardware design](Figures/vitis_generated_block_design.png)

5. Boot up the RFSoC board from an SD card:
   - Insert the SD card into a card reader on a Linux machine. Check its device name:
     ```shell
     lsblk -r -O
     ```
     For example, my SD card is `/dev/sda`. In the commands below, replace `/dev/sdX` with the actual SD card device.
   - Follow [these steps](https://xilinx-wiki.atlassian.net/wiki/spaces/A/pages/18842385/How+to+format+SD+card+for+SD+boot) to create a boot partition (FAT32) and a root partition (EXT4) on the SD card.
   - Check that both SD-card partitions exist as block devices before writing anything:
     ```shell
     SD=/dev/sdX
     lsblk -p -o NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS,MODEL ${SD}
     ls -l ${SD} ${SD}1 ${SD}2
     test -b ${SD}1 && test -b ${SD}2
     ```
     The two partition device nodes must start with `b`, for example `brw-rw----`. If a partition node is missing or is a regular file, unplug and replug the SD-card reader, then check again.
   - Create a target-friendly EXT4 root partition and copy the PetaLinux rootfs into it. This avoids EXT4 feature mismatches, such as `64bit` and `metadata_csum`, that can prevent the target kernel from mounting the rootfs:
     ```shell
     cd /path/to/workspace_4ch
     mkdir -p /tmp/rootfs_src rootfs-sd
     sudo umount ${SD}1 ${SD}2 mnt /tmp/rootfs_src rootfs-sd 2>/dev/null || true

     sudo mkfs.ext4 -F -L rootfs -O ^64bit,^metadata_csum ${SD}2
     sudo mount -o loop,ro /path/to/workspace_4ch/rfsoc-linux/images/linux/rootfs.ext4 /tmp/rootfs_src
     sudo mount -t ext4 ${SD}2 rootfs-sd
     findmnt rootfs-sd

     sudo rsync -aH --numeric-ids /tmp/rootfs_src/ rootfs-sd/
     sync
     sudo umount rootfs-sd
     sudo umount /tmp/rootfs_src
     sudo e2fsck -f -y ${SD}2
     sudo file -s ${SD}2
     ```
     `findmnt rootfs-sd` should show `${SD}2` as the source. The last command should report an `ext4 filesystem` and should not list the `64bit` feature.
   - Mount the boot (FAT32) partition:
     ```shell
     mkdir -p mnt
     sudo mount -t vfat ${SD}1 mnt
     ```
   - Copy boot files, bit file, and executable to the SD card:
     ```shell
     sudo cp /path/to/workspace_4ch/test_adc_system/Hardware/package/sd_card/* mnt/
     sync
     sudo umount mnt
     ```
     If reusing an SD card image that already boots and has XRT working, it is enough to replace the two updated application files on the FAT32 boot partition. Always copy `test_adc` and `dummy_kernel.xclbin` together from the same build:
     ```shell
     sudo cp /path/to/workspace_4ch/test_adc_system/Hardware/package/sd_card/test_adc mnt/
     sudo cp /path/to/workspace_4ch/test_adc_system/Hardware/package/sd_card/dummy_kernel.xclbin mnt/
     sync
     ```
     If the platform, device tree, kernel image, or boot files changed, copy the full `sd_card` directory instead of only the two application files.
   - Put the SD card into the microSD slot of the RFSoC4x2 board.
     Use a USB cable to connect the Linux host to the JTAG/UART port on the RFSoC4x2 board.
     Also connect the Ethernet port to a DHCP server if available.
     On the host, run to connect to the UART port (install `picocom` if needed):
     ```shell
     sudo picocom -b 115200 /dev/ttyUSB1
     ```
   - If boot stops with:
     ```text
     Kernel panic - not syncing: VFS: Unable to mount root fs on unknown-block(0,0)
     ```
     first check that the SD card has a valid EXT4 rootfs on partition 2.

     To make the SD card boot without manually typing `bootargs` at the U-Boot prompt, create `uEnv.txt` on the FAT32 boot partition. If the boot partition is still mounted at `mnt` on the host:
     ```shell
     sudo tee mnt/uEnv.txt >/dev/null <<'EOF'
     bootargs=earlycon console=ttyPS0,115200 clk_ignore_unused root=/dev/mmcblk0p2 rootwait rw sdhci.debug_quirks2=4
     EOF
     sync
     sudo umount mnt
     ```

     If the board has already booted once using a temporary U-Boot command, create the same file from Linux on the board:
     ```shell
     cat > /run/media/boot-mmcblk0p1/uEnv.txt <<'EOF'
     bootargs=earlycon console=ttyPS0,115200 clk_ignore_unused root=/dev/mmcblk0p2 rootwait rw sdhci.debug_quirks2=4
     EOF
     sync
     cat /run/media/boot-mmcblk0p1/uEnv.txt
     reboot
     ```

     The generated `boot.scr` imports `uEnv.txt` before loading the kernel, so the next boot should not require manual `setenv bootargs`.

     To test the same setting temporarily without modifying the SD card, interrupt U-Boot during its countdown and run:
     ```shell
     setenv bootargs 'earlycon console=ttyPS0,115200 clk_ignore_unused root=/dev/mmcblk0p2 rootwait rw sdhci.debug_quirks2=4'
     printenv bootargs
     run bootcmd
     ```
     This U-Boot change is temporary unless `saveenv` is supported and intentionally used. If the same panic remains after setting these boot arguments, recreate the EXT4 rootfs partition using the commands above.
     Boot up the RFSoC4x2 board.
   - Log in as `root` (default password is `root`, remember to change it after logging in).
     Do `ifconfig` to check the IP address. With the IP address, can also `ssh` in as `root`.
     Petalinux also creates a sudoer with login `petalinux`, whose passwd is set by the user when logging in the first time.
   - If the board is connected directly to a PC instead of a DHCP network, assign static IP addresses. On the RFSoC board:
     ```shell
     ifconfig eth0 192.168.2.2 netmask 255.255.255.0 up
     ifconfig eth0
     cat /sys/class/net/eth0/carrier
     ```
     The `carrier` value should be `1`. On the PC Ethernet adapter, use a static IPv4 address such as `192.168.2.1` with netmask `255.255.255.0`, leaving gateway and DNS blank. Then connect from the PC:
     ```shell
     ping 192.168.2.2
     ssh root@192.168.2.2
     ```

6. Configure and turn on the reference clock chips (LMK04828 and LMX2594) via SPI:
   - From the host, copy this python package file [`xrfclk-2.0.tar.gz`](src/vitis_adc_platform/xrfclk-2.0.tar.gz) (I hacked out from the [RFSoC-PYNQ distribution](https://github.com/Xilinx/RFSoC-PYNQ/tree/master/boards/RFSoC4x2)) and the clock setup script [`set_ref_clocks.py`](src/vitis_adc_platform/set_ref_clocks.py) to the RFSoC board. Replace `192.168.2.2` with the board IP address:
     ```shell
     scp src/vitis_adc_platform/xrfclk-2.0.tar.gz root@192.168.2.2:/home/root/
     scp src/vitis_adc_platform/set_ref_clocks.py root@192.168.2.2:/home/root/
     ```
   - On the board, check that the three SPI nodes from the device tree are present:
     ```shell
     ls /sys/bus/spi/devices
     modprobe spidev
     ```
     The expected SPI devices are `spi0.0`, `spi0.1`, and `spi0.2`. The `/dev/spidev*` nodes may not exist yet; the `xrfclk` package binds these SPI devices to `spidev` when it runs.
   - Install the Python package and run the script on the board:
     ```shell
     cd /home/root
     python3 -m pip install ./xrfclk-2.0.tar.gz
     python3 ./set_ref_clocks.py
     ls /dev/spidev*
     ```
     The script should create `/dev/spidev0.0`, `/dev/spidev0.1`, and `/dev/spidev0.2` and program the LMK04828 and LMX2594 chips for the ADC reference clocks.
   - If `/sys/bus/spi/devices` has `spi0.0`, `spi0.1`, and `spi0.2`, but `/dev/spidev*` is still missing, bind the devices manually and rerun the script:
     ```shell
     for d in spi0.0 spi0.1 spi0.2; do
       echo spidev > /sys/bus/spi/devices/$d/driver_override
       if [ -L /sys/bus/spi/devices/$d/driver ]; then
         echo $d > /sys/bus/spi/devices/$d/driver/unbind
       fi
       echo $d > /sys/bus/spi/drivers/spidev/bind
     done

     ls /dev/spidev*
     python3 /home/root/set_ref_clocks.py
     ```
7. Run the `test_adc` app to grab samples from the ADC:
   ```shell
   cd /run/media/boot-mmcblk0p1/
   chmod +x test_adc
   ./test_adc dummy_kernel.xclbin
   ```
   If the app runs properly, should see the following printout:
   ```
   Found Platform
   Platform Name: Xilinx
   INFO: Reading dummy_kernel.xclbin
   Loading: 'dummy_kernel.xclbin'
   Trying to program device[0]: edge
   Device[0]: program successful!
   External PPS trigger on PPS_TRIG_AXIS rising edge
   Output columns are RFDC_DATA_AXIS/ADC_D, RFDC_TRIG_AXIS/ADC_C, RFDC_ADC_B_AXIS/ADC_B, and RFDC_ADC_A_AXIS/ADC_A
   Trigger word is near sample 3272 of 16384 per-channel samples
   Waiting for trigger for frame 0
   Writing data to wave.txt
   ```
   The samples are stored in the file `wave.txt`.
   Check the captured samples with:
   ```shell
   ls -lh wave.txt
   head wave.txt
   tail wave.txt
   grep -v '^0 0 0 0$' wave.txt | head
   ```
   `wave.txt` and the Ethernet stream contain four columns/channels: `RFDC_DATA_AXIS`/ADC_D, `RFDC_TRIG_AXIS`/ADC_C, `RFDC_ADC_B_AXIS`/ADC_B, and `RFDC_ADC_A_AXIS`/ADC_A. Each frame contains about 20% pretrigger and 80% post-trigger samples; for the default frame size, the trigger word is near sample `3272`.

   The FPGA trigger decision uses only `PPS_TRIG_AXIS`. Drive the board `1PPS` SMA with a valid pulse before expecting the app to complete. The Vivado-only ILA test above used a `3.3 Vpp` square wave and confirmed `pps_trigger_sync_level` toggles.

   If the program stops after `Waiting for trigger for frame 0`, XRT has programmed the PL and launched the compute unit, but the HLS kernel is probably waiting for a rising edge on `PPS_TRIG_AXIS`. Confirm the PPS pulse at the SMA, re-arm the PPS ILA, and check that `pps_trigger_axis_ready` goes high while the kernel is running. Recheck the reference clock setup above and inspect the XRT logs:
   ```shell
   dmesg | grep -i -E 'zocl|xrt|fpga|rfdc|spi|clock'
   dmesg | tail -80
   ```
   If the program completes but `wave.txt` contains only zeros, the Vitis path is working but the data ADC input is likely seeing no signal or an RFDC/clock setup issue. Confirm the reference clocks were programmed and that the analog signal is connected to the data ADC input mapped to `RFDC_DATA_AXIS`.

   Copy `wave.txt` to a PC with Python, NumPy, and Matplotlib installed. To plot all four channels and inspect continuity, select one sample lane from each 128-bit RFDC AXI4-Stream word:
   ```shell
   python3 src/vitis_adc_platform/plot_wave.py wave.txt \
     --channel all \
     --word-lane 0 \
     --start 300 \
     --count 600
   ```
   Each RFDC word contains eight signed 16-bit samples. With `--word-lane 0`, the effective plotted sample rate is `614.4 MS/s / 8 = 76.8 MS/s`. A `1 MHz` input should have approximately `76.8` plotted points per cycle and `1 us` between peaks. This mode is useful for checking that the captured AXI4-Stream words are continuous.

   To inspect the full-rate waveform, omit `--word-lane`. Multiply a word-lane start index by eight when selecting the equivalent region:
   ```shell
   python3 src/vitis_adc_platform/plot_wave.py wave.txt \
     --channel all \
     --start 2400 \
     --count 4800
   ```
   At the full `614.4 MS/s` sample rate, a `40 MHz` input has about `15.36` points per cycle. The same waveform plotted with `--word-lane 0` has only `1.92` points per cycle, so use the full-rate plot for high-frequency waveform shape checks. If a full-rate plot instead shows discontinuities every eight samples, retry with `--lane-order msb-first` to check the RFDC word-lane ordering.

   The rebuilt common-clock design should produce a continuous waveform with no periodic jumps. Verify this on the board before analyzing the measured period.

   The host application can also stream repeated captures over Ethernet. Each frame contains 16384 four-channel sample rows. At 614.4 MS/s, each frame spans about 26.67 us; streaming at 60 Hz is about 7.9 MB/s of ADC payload. TCP is the simplest option. On the PC, start the receiver from this repository:
   ```shell
   python3 src/vitis_adc_platform/receive_wave_stream.py --mode tcp --bind 0.0.0.0 --port 5000 --plot
   ```
   Then run the sender on the board, replacing `192.168.2.1` with the PC Ethernet IP address:
   ```shell
   cd /run/media/boot-mmcblk0p1/
   ./test_adc dummy_kernel.xclbin --tcp 192.168.2.1 5000 --rate 1000 --frames 0
   ```
   Use `--frames 600` instead of `--frames 0` to send ten seconds of data at 60 Hz. UDP is also supported; start the receiver with `--mode udp` and run the board application with `--udp 192.168.2.1 5000`. UDP frames are split into smaller packets and reassembled by the Python receiver. The PC stream contains all four ADC channels.

   Here is an example plot of the captured samples when a 2 MHz sinusoid is fed to the ADC-D SMA connector:
   ![2 MHz sinusoid](Figures/sin2M.png) 

## Validate the Four-Channel Hardware Build
Complete this test after the PPS-enabled Vitis build. The purpose is to verify sample continuity and measure whether the cross-tile behavior is sufficient before deciding whether RFDC multi-tile synchronization is required.

1. For the first boot of this static hardware build, copy the complete generated SD-card directory to the FAT32 boot partition:

   ```shell
   sudo cp -a \
     /path/to/workspace_4ch/test_adc_system/Hardware/package/sd_card/. \
     /path/to/mounted/boot/
   sync
   ```

2. Boot the board, log in as `root`, and configure the RF reference clocks. Repeat the clock configuration after every power cycle:

   ```shell
   modprobe spidev
   python3 /home/root/set_ref_clocks.py
   ls /dev/spidev*
   ```

   The expected device nodes are:

   ```text
   /dev/spidev0.0
   /dev/spidev0.1
   /dev/spidev0.2
   ```

3. Apply the same `1 MHz` sine wave to all four ADC inputs using a suitable splitter or distribution amplifier and matched cables. Verify every splitter output with an oscilloscope. Also drive the board `1PPS` SMA with a valid pulse so the external trigger can fire.

   | ADC input | Captured column | RFDC tile |
   |---|---|---|
   | ADC_D | `RFDC_DATA_AXIS/ADC_D` | Tile 0 |
   | ADC_C | `RFDC_TRIG_AXIS/ADC_C` | Tile 0 |
   | ADC_B | `RFDC_ADC_B_AXIS/ADC_B` | Tile 2 |
   | ADC_A | `RFDC_ADC_A_AXIS/ADC_A` | Tile 2 |

4. Run one capture. The capture will complete on the next rising edge of `PPS_TRIG_AXIS`:

   ```shell
   cd /run/media/boot-mmcblk0p1/
   chmod +x test_adc
   ./test_adc dummy_kernel.xclbin
   ```

5. Confirm that `wave.txt` has `16384` rows and four columns:

   ```shell
   wc -l wave.txt
   head wave.txt
   tail wave.txt
   awk 'NF != 4 {bad++} END {print "rows with wrong column count:", bad+0}' wave.txt
   grep -v '^0 0 0 0$' wave.txt | head
   ```

6. Copy the waveform to the PC:

   ```shell
   scp root@192.168.2.2:/run/media/boot-mmcblk0p1/wave.txt .
   ```

7. Plot one lane from each eight-sample RFDC word. This is useful for checking AXI4-Stream-word continuity:

   ```shell
   python3 src/vitis_adc_platform/plot_wave.py wave.txt \
     --channel all \
     --word-lane 0 \
     --start 300 \
     --count 600
   ```

   Plot the full-rate waveform:

   ```shell
     python3 src/vitis_adc_platform/plot_wave.py wave.txt \
     --channel all \
     --start 2400 \
     --count 4800
   ```

   For a `1 MHz` input, adjacent peaks should be separated by approximately `1 us`. All four channels should be continuous with no periodic jumps. If the full-rate waveform instead alternates incorrectly every eight samples, retry with `--lane-order msb-first`.

8. Plot the FFT using the complete waveform:

   ```shell
   python3 src/vitis_adc_platform/plot_wave.py wave.txt \
     --channel all \
     --count 0 \
     --fft
   ```

   The dominant peak should be near `1 MHz`.

9. Save ten captures on the board before the power cycle:

   ```shell
   mkdir -p /home/root/four_channel_runs/before_power_cycle
   cd /run/media/boot-mmcblk0p1/

   for i in $(seq -w 1 10); do
     ./test_adc dummy_kernel.xclbin \
       --wave /home/root/four_channel_runs/before_power_cycle/wave_${i}.txt || break
   done
   ```

10. Power-cycle the board, configure the RF reference clocks again, and save ten more captures:

    ```shell
    mkdir -p /home/root/four_channel_runs/after_power_cycle
    cd /run/media/boot-mmcblk0p1/

    for i in $(seq -w 1 10); do
      ./test_adc dummy_kernel.xclbin \
        --wave /home/root/four_channel_runs/after_power_cycle/wave_${i}.txt || break
    done
    ```

    Copy both sets of results to the PC:

    ```shell
    scp -r root@192.168.2.2:/home/root/four_channel_runs .
    ```

11. Compare the captures:

    - Confirm sample continuity on every channel.
    - Compare ADC_D with ADC_C to check the Tile 0 phase relationship.
    - Compare ADC_B with ADC_A to check the Tile 2 phase relationship.
    - Compare Tile 0 with Tile 2 across captures and power cycles.

    A fixed cable-related offset is acceptable. Random phase changes after restart, Tile 2 corruption, or sample discontinuities mean that RFDC multi-tile synchronization or an explicit clock-domain-crossing design is required before relying on four-channel timing measurements.
