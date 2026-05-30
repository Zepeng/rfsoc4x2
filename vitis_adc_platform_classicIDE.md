# A Vitis Extensible Platform with ADC Data and Trigger Streams for RFSoC4x2 (Vitis 2023.1 Classic IDE)
This is my second experiment with the RFSoC4x2 board. The goal is to build a simple Vitis extensible platform that supports pulling samples from one ADC stream of the ZU48DR device on board, while exporting a second ADC stream that can be used by PL trigger logic.

The current HLS kernel is a connectivity baseline: it reads the data and trigger streams in lockstep and writes both channels to memory so the Vitis-generated design has both RFDC streams connected. Actual threshold/window trigger logic can be added after this two-stream build is proven.

## Step 0: Install the RFSoC4x2 board files
If not already installed, follow [Steps 0.1 and 0.2 in the previous experiment](./vitis_base_platform.md#step-0-install-the-rfsoc4x2-board-files-and-xilinxs-repos) to install the RFSoC board files. There is no need to install the Xilinx's device tree repo and the ZYNQMP common image here. We will use [Petalinux](https://www.xilinx.com/products/design-tools/embedded-software/petalinux-sdk.html#tools) to generate a new image and a device tree. 

## Step 1: Create a Vivado Hardware Design
1. Download the TCL script [rfsoc_adc_hardware.tcl](src/vitis_adc_platform/rfsoc_adc_hardware.tcl) to `~/workspace`.
2. Open Vivado and source the TCL script in a TCL shell, or simply do
   ```bash
   vivado -source rfsoc_adc_hardware.tcl
   ```
   to generate the following block design:
   ![hardware design](Figures/block_design_adc_platform.png)
   which adds an [RF Data Converter](https://www.xilinx.com/products/intellectual-property/rf-data-converter.html#overview) IP to a slightly modified version of the hardware design in [Vitis Platform Creation Tutorial for
ZCU104-Step 1](https://github.com/Xilinx/Vitis-Tutorials/blob/2023.1/Vitis_Platform_Creation/Design_Tutorials/02-Edge-AI-ZCU104/step1.md).
   - The Vivado project is named `rfsoc_adc_hardware`.
   - The RFDC follows the RFSoC-PYNQ base-design pattern for real ADC streams: ADC tiles 0 and 2 are enabled with sampling rate set to 4.9152 GSps and decimation set to 2, giving 2.4576 GS/s on each exported real AXI4-Stream.
   - `m00_axis` and `m02_axis` are exported for the two-stream dummy kernel. `m20_axis` and `m22_axis` are also exported as platform streams for later tile-2 checks.
   - The Vitis platform stream tags are `RFDC_DATA_AXIS` for `m00_axis`, `RFDC_TRIG_AXIS` for `m02_axis`, `RFDC_ADC_B_AXIS` for `m20_axis`, and `RFDC_ADC_A_AXIS` for `m22_axis`.

3. Before running synthesis, optionally verify the block design and Vitis platform metadata in batch mode. From a checkout of this repository, run:
   ```bash
   vivado -mode batch -source /path/to/rfsoc4x2/src/vitis_adc_platform/check_rfsoc_adc_bd.tcl \
     -tclargs --hardware_tcl ~/workspace/rfsoc_adc_hardware.tcl
   ```
   The checker creates a temporary project, sources `rfsoc_adc_hardware.tcl`, validates the block design, and should end with:
   ```
   PFM m00_axis sptag = RFDC_DATA_AXIS
   PFM m02_axis sptag = RFDC_TRIG_AXIS
   PFM m20_axis sptag = RFDC_ADC_B_AXIS
   PFM m22_axis sptag = RFDC_ADC_A_AXIS
   CHECK PASSED: tile 0/tile 2 real ADC streams and exported RFDC tags are present
   ```
   This check does not require synthesis or implementation.

4. Run synthesis, implementation, and bitstream generation, then export the platform `rfsoc_adc_hardware.xsa` for both hardware and hardware emulation. Vitis will not see the new stream metadata until the `.xsa` is regenerated from the updated Vivado design.

## Step 2: Use Petalinux to create boot files, device tree file, linux image, rootfs, and sysroot
1. Create a Petalinux project: 
   ```shell
   cd ~/workspace
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
   - Add the following line to `~/workspace/rfsoc-linux/project-spec/meta-user/conf/user-rootfsconfig`:
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
   - Add the following lines to `~/workspace/rfsoc-linux/project-spec/meta-user/recipes-bsp/device-tree/files/system-user.dtsi`:
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
   - The boot files, device tree file, kernel image, and the EXT4 rootfs are generated in `~/workspace/rfsoc-linux/images/linux/`. The sysroot is in `~/workspace/rfsoc-linux/images/linux/sysroots/cortexa72-cortexa53-xilinx-linux`.

   If you are only changing the PL RFDC stream export described in Step 1 and already have a working PetaLinux image for this platform, you can usually reuse it. Rebuild PetaLinux only when PS configuration, the address map, device tree requirements, kernel configuration, rootfs contents, or boot files change.
     
## Step 3: Create a Vitis Platform 
1. Create a Vitis Platform project:
 - Start `xsct`:
   ```shell
   cd ~/workspace
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
   The platform project is now created in `~/workspace/rfsoc_adc_vitis_platform`.

   If you previously built the single-stream version of this platform, create a fresh platform project or delete the old `~/workspace/rfsoc_adc_vitis_platform` first. This avoids Vitis using cached metadata that still contains only `RFDC_AXIS`. After exporting a new `.xsa`, the Vitis platform must be regenerated before the application project is configured or rebuilt.

2. Copy `system.dtb` and boot files from the image generated by Petalinux in Step 2 above:
 - Make the following two directories for convenience:
   ```shell
   cd rfsoc_adc_vitis_platform
   mkdir boot fat32
   ```
 - Copy `system.dtb` and other boot files to the directories:
   ```shell
   cp ~/workspace/rfsoc-linux/images/linux/system.dtb boot
   cp ~/workspace/rfsoc-linux/images/linux/system.dtb fat32
   cp ~/workspace/rfsoc-linux/images/linux/boot.scr fat32
   cp ~/workspace/rfsoc-linux/images/linux/bl31.elf boot
   cp ~/workspace/rfsoc-linux/images/linux/u-boot.elf boot
   ```
   
3. Build the Vitis platform:  
 - Open up the Vitis GUI:
   ```shell
   vitis
   ```
   If the platform project doesn't show up in the **<em>Explorer</em>** window,
   either go to **<em>Vitis->XSCT Console</em>** to open up
   an xsct console and type the following command:
   ```tcl
   importprojects rfsoc_adc_vitis_platform
   ```
   or go to **<em>File->Import...</em>** to import the platform project.
   The platform project created above should now show up in the **<em>Explorer</em>** window.
 - Set the platform parameters:
   - Open `platform.spr` from the **<em>Explorer</em>** window (**<em>right-click->Open</em>**)
   - Set the paths to `fsbl.elf` and `pmufw.elf`: 
     - `FSBL`: Click the `Browse` button to select `~/workspace/rfsoc-linux/images/linux/zynqmp_fsbl.elf`
     - `PMU Firmware`: Click the `Browse` button to select `~/workspace/rfsoc-linux/images/linux/pmufw.elf`  
   - Select `xrt` in the opened tab in the main window
   - Under `Domain:xrt` field:
     - `Bif File:` Click downarrow in the `Browse` button to select `Generate Bif`.
     - `Boot Components Directory:` Click the `Browse` button to select `~/workspace/rfsoc_adc_vitis_platform/boot`.
     - `FAT32 Partition Directory:` Click the `Browse` button to select `~/workspace/rfsoc_adc_vitis_platform/fat32`.
     - `Display Name:` Change as wish.
     - `Description:` Change as wish.
     - **Leave `Linux Rootfs:` and `Sysroot Directory:` empty**.
 - Build the platform by click the :hammer: button on the tool bar.
   After the build, the built Vitis platform is in `~/workspace/rfsoc_adc_vitis_platform/export/rfsoc_adc_vitis_platform`.
 - Fix the `linux.bif` file:
   - Select and open the `rfsoc_adc_vitis_platform/export/rfsoc_adc_vitis_platform/sw/rfsoc_adc_vitis_platform/boot/linux.bif` file from the **<em>Explorer</em>**.
   - Change the two lines from:
     ```
     [bootloader] <fsbl.elf>
     [pmufw_image] <pmufw.elf>
     ```
     to
     ```
     [bootloader] <rfsoc_adc_vitis_platform/boot/fsbl.elf>
     [pmufw_image] <rfsoc_adc_vitis_platform/boot/pmufw.elf>
     ```

## Step 4: Test the Vitis Platform
1. Create a new Vitis application project from template. A fresh application project is recommended after changing the platform from one RFDC stream to two RFDC streams:
   - Add Vitis example templates:
     - Go to **<em>Vitis->Examples...</em>** to install example templates
     - Click the `Download` button to install the templates from the **<em>Vitis Accel Examples Repository</em>**
     - Only need to do this once
   - Go to **<em>File->New->Application Project...</em>** to create a new application project:
     - Select the regenerated `rfsoc_adc_vitis_platform` created in Step 3. If the platform doesn't show up as a choice, press the **+** button and select `~/workspace/rfsoc_adc_vitis_platform/export/rfsoc_adc_vitis_platform/rfsoc_adc_vitis_platform.xpfm`. Press the `Next>` button.
     - Name the project `test_adc`. Press the `Next>` button.
     - Under `Application settings` field:
       - `Sysroot path:` Click the `Browse` button to select `~/workspace/rfsoc-linux/images/linux/sysroots/cortexa72-cortexa53-xilinx-linux`.
       - `Root FS:` Click the `Browse` button to select `~/workspace/rfsoc-linux/images/linux/rootfs.ext4`.
       - `Kernel Image:` Click the `Browse` button to select `~/workspace/rfsoc-linux/images/linux/Image`.
       - Press the `Next>` button.
   - Select **<em>Acceleration templates with PL and AIE accelerators->Host Examples->Data Transfer (C)</em>** to finish up the application project creation step.
  
2. Replace the template sources with the two-stream sources:
   If reusing an existing `test_adc` application project, reconfigure it against the regenerated `rfsoc_adc_vitis_platform` first. Then replace the kernel and host sources and update the V++ connectivity below. A project created for the old single-stream platform still references `RFDC_AXIS` and `dummy_kernel_1.s_in`, and will not link against the new two-stream platform.
   - Under the **<em>Explorer</em>** window, replace the file `test_adc_kernels/src/dummy_kernel.cpp` in the template with this [`dummy_kernel.cpp`](src/vitis_adc_platform/dummy_kernel.cpp).
   - Replace the file `test_adc/src/host.cpp` file in the template with this [`host.cpp`](src/vitis_adc_platform/host.cpp).
   - Refresh the projects in the **<em>Explorer</em>** window if Vitis does not immediately show the modified files.
   - The kernel arguments are now:
     - `buffer0`: output buffer in DDR.
     - `data_in`: main ADC stream connected to `RFDC_DATA_AXIS`.
     - `trigger_in`: trigger ADC stream connected to `RFDC_TRIG_AXIS`.
     - `size`: number of 128-bit AXI4-Stream words to capture from each stream.
     - `output_words`: number of packed 256-bit output words available in `buffer0`.
     The host code sets `size` as kernel argument index `3`, because the second AXIS input shifts the scalar argument index.
     The kernel writes one packed 256-bit DDR word per loop so it can run at `II=1`.

3. Configure the hardware link for the two RFDC streams:
   - Open `test_adc_system_hw_link/test_adc_system_hw_link.prj` from the **<em>Explorer</em>**.
   - Under **<em>Hardware Functions</em>**, right-click `dummy_kernel` and select **<em>Edit V++ Options...</em>**.
   - Remove any old connectivity lines that mention `RFDC_AXIS` or `dummy_kernel_1.s_in`.
   - Add the following lines to the `V++ configuration settings` field:
     ```
     [clock]
     id=2:dummy_kernel_1

     [connectivity]
     stream_connect = RFDC_DATA_AXIS:dummy_kernel_1.data_in
     stream_connect = RFDC_TRIG_AXIS:dummy_kernel_1.trigger_in
     ```
   - Click the `Apply and Close` button.
   - If Vitis assigned a different compute-unit name than `dummy_kernel_1`, use the exact instance name shown under **<em>Hardware Functions</em>** in both `stream_connect` lines.
   - If the link step reports that `RFDC_DATA_AXIS` or `RFDC_TRIG_AXIS` cannot be found, rebuild the Vivado design, re-export the `.xsa`, and regenerate the Vitis platform from the new `.xsa`.
   - If the link step reports that `data_in` or `trigger_in` cannot be found, the HLS component is still using the old single-stream `dummy_kernel.cpp`; replace the source again and clean/rebuild the application.
   - If the `cfgen` command line still contains `-sc RFDC_AXIS:dummy_kernel_1.s_in`, the old V++ connectivity is still present. Remove that line from the hardware-link V++ options and clean the hardware-link build directory before rebuilding.

4. Configure packaging and build:
   - Open `test_adc_system.sprj` from the **<em>Explorer</em>**.
   - Select **<em>Hardware</em>** for **<em>Active build configuration</em>** at the upper-right corner.
   - Add `--package.no_image` to the `Packaging options` field to turn off generating a disk image. This still runs the package step and still requires valid boot files for BIF generation.
   - If packaging reports that `export/rfsoc_adc_vitis_platform/sw/fsbl.elf` does not exist, copy the boot files from the PetaLinux image output into the platform export tree:
     ```shell
     mkdir -p ~/workspace/rfsoc_adc_vitis_platform/export/rfsoc_adc_vitis_platform/sw
     cp ~/workspace/rfsoc-linux/images/linux/zynqmp_fsbl.elf \
        ~/workspace/rfsoc_adc_vitis_platform/export/rfsoc_adc_vitis_platform/sw/fsbl.elf
     cp ~/workspace/rfsoc-linux/images/linux/pmufw.elf \
        ~/workspace/rfsoc_adc_vitis_platform/export/rfsoc_adc_vitis_platform/sw/pmufw.elf
     ls -l ~/workspace/rfsoc_adc_vitis_platform/export/rfsoc_adc_vitis_platform/sw/fsbl.elf \
           ~/workspace/rfsoc_adc_vitis_platform/export/rfsoc_adc_vitis_platform/sw/pmufw.elf
     ```
     If Vitis later reports missing `bl31.elf`, `u-boot.elf`, or `system.dtb`, copy those files from `~/workspace/rfsoc-linux/images/linux/` to the path named in the error message.
   - Clean the system project if this workspace previously built the single-stream design.
   - Click the :hammer: button on the tool bar to build the project.
   - The Vitis-generated block design should connect `RFDC_DATA_AXIS` to `dummy_kernel_1/data_in` and `RFDC_TRIG_AXIS` to `dummy_kernel_1/trigger_in`.
   - After the build completes, verify that the generated `xclbin` contains the two-stream kernel:
     ```shell
     xclbinutil --info --input \
       ~/workspace/test_adc_system/Hardware/package/sd_card/dummy_kernel.xclbin | \
       grep -E "data_in|trigger_in|dummy_kernel"
     ```
     The output should show the `dummy_kernel` signature with `data_in` and `trigger_in` arguments, and the command line should include:
     ```
     --connectivity.stream_connect RFDC_DATA_AXIS:dummy_kernel_1.data_in
     --connectivity.stream_connect RFDC_TRIG_AXIS:dummy_kernel_1.trigger_in
     ```
   - The files to deploy after a Vitis build are generated under:
     ```shell
     ~/workspace/test_adc_system/Hardware/package/sd_card/
     ```
     For a host or kernel change, keep the executable and xclbin as a matched pair and update both files on the SD-card boot partition:
     ```shell
     test_adc
     dummy_kernel.xclbin
     ```
     If the platform, boot files, device tree, or PetaLinux image changed, also update the boot files from the same `sd_card` directory:
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
     cd ~/workspace
     mkdir -p /tmp/rootfs_src rootfs-sd
     sudo umount ${SD}1 ${SD}2 mnt /tmp/rootfs_src rootfs-sd 2>/dev/null || true

     sudo mkfs.ext4 -F -L rootfs -O ^64bit,^metadata_csum ${SD}2
     sudo mount -o loop,ro ~/workspace/rfsoc-linux/images/linux/rootfs.ext4 /tmp/rootfs_src
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
     sudo cp ~/workspace/test_adc_system/Hardware/package/sd_card/* mnt/
     sync
     sudo umount mnt
     ```
     If reusing an SD card image that already boots and has XRT working, it is enough to replace the two updated application files on the FAT32 boot partition. Always copy `test_adc` and `dummy_kernel.xclbin` together from the same build:
     ```shell
     sudo cp ~/workspace/test_adc_system/Hardware/package/sd_card/test_adc mnt/
     sudo cp ~/workspace/test_adc_system/Hardware/package/sd_card/dummy_kernel.xclbin mnt/
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
     first check that the SD card has a valid EXT4 rootfs on partition 2. To test or temporarily fix boot arguments without rebuilding the device tree, interrupt U-Boot during its countdown and run:
     ```shell
     setenv bootargs 'earlycon console=ttyPS0,115200 clk_ignore_unused root=/dev/mmcblk0p2 rootwait rw sdhci.debug_quirks2=4'
     printenv bootargs
     run bootcmd
     ```
     This U-Boot change is temporary unless `saveenv` is supported and intentionally used. A persistent no-rebuild option is to place `uEnv.txt` on the FAT32 boot partition with:
     ```text
     bootargs=earlycon console=ttyPS0,115200 clk_ignore_unused root=/dev/mmcblk0p2 rootwait rw sdhci.debug_quirks2=4
     ```
     The generated `boot.scr` imports `uEnv.txt` before loading the kernel. If the same panic remains after setting these boot arguments, recreate the EXT4 rootfs partition using the commands above.
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
   Capturing frame 0
   Writing data to wave.txt
   ```
   The data-channel samples are stored in the file `wave.txt`.
   Check the captured samples with:
   ```shell
   ls -lh wave.txt
   head wave.txt
   tail wave.txt
   grep -v '^0$' wave.txt | head
   ```
   This build validates the two-stream plumbing, but it does not implement triggered capture yet. The kernel reads `data_in` and `trigger_in` in lockstep and writes both to memory. `wave.txt` and the Ethernet stream contain two columns/channels: `RFDC_DATA_AXIS` followed by `RFDC_TRIG_AXIS`.

   If the program stops after `Capturing frame 0`, XRT has programmed the PL and launched the compute unit, but the HLS kernel is probably waiting for ADC stream samples. Because this kernel reads both `data_in` and `trigger_in`, both RFDC streams must be running. Recheck the reference clock setup above and inspect the XRT logs:
   ```shell
   dmesg | grep -i -E 'zocl|xrt|fpga|rfdc|spi|clock'
   dmesg | tail -80
   ```
   If the program completes but `wave.txt` contains only zeros, the Vitis path is working but the data ADC input is likely seeing no signal or an RFDC/clock setup issue. Confirm the reference clocks were programmed and that the analog signal is connected to the data ADC input mapped to `RFDC_DATA_AXIS`.
   The host application can also stream repeated captures over Ethernet. Each frame contains 65536 two-channel sample pairs. At 2.4576 GS/s, each frame spans about 26.67 us; streaming at 60 Hz is about 15.7 MB/s of ADC payload. TCP is the simplest option. On the PC, start the receiver from this repository:
   ```shell
   python3 src/vitis_adc_platform/receive_wave_stream.py --mode tcp --bind 0.0.0.0 --port 5000 --plot
   ```
   Then run the sender on the board, replacing `192.168.2.1` with the PC Ethernet IP address:
   ```shell
   cd /run/media/boot-mmcblk0p1/
   ./test_adc dummy_kernel.xclbin --tcp 192.168.2.1 5000 --rate 60 --frames 0
   ```
   Use `--frames 600` instead of `--frames 0` to send ten seconds of data at 60 Hz. UDP is also supported; start the receiver with `--mode udp` and run the board application with `--udp 192.168.2.1 5000`. UDP frames are split into smaller packets and reassembled by the Python receiver. The PC stream contains both `RFDC_DATA_AXIS` and `RFDC_TRIG_AXIS`.

   Here is an example plot of the captured samples when a 2 MHz sinusoid is fed to the ADC-D SMA connector:
   ![2 MHz sinusoid](Figures/sin2M.png) 
