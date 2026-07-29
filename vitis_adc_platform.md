# A Vitis Extensible Platform with Four ADC Streams and External PPS Trigger for RFSoC4x2 (Vitis 2023.2.1 Unified IDE)
This is an attempt to migrate [A Vitis Extensible Platform with Four ADC Streams and an FPGA Trigger for RFSoC4x2](./vitis_adc_platform_classicIDE.md) to the Vitis 2023.2 Unified IDE. Steps 0 to 2 are mostly the same as those before.

The current HLS kernel reads ADC_D, ADC_C, ADC_B, and ADC_A in lockstep, triggers on a rising edge from `PPS_TRIG_AXIS`, and writes all four ADC channels to memory with about 20% pretrigger and 80% post-trigger samples. The static Vivado platform details for the PPS adapter and ILA are described in the [external PPS trigger guide](vitis_adc_platform_pps_trigger.md).


## Step 0: Install the RFSoC4x2 board files
If not already installed, do the following steps to install the RFSoC board files:
1. Get the board files from the [RealDigital repo](https://github.com/RealDigitalOrg/RFSoC4x2-BSP)
   ```shell
   git clone https://github.com/RealDigitalOrg/RFSoC4x2-BSP.git ~/workspace/RFSoC4x2-BSP
   ```
   The board files are in  `~/workspace/RFSoC4x2-BSP/board_files/rfsoc4x2`.
  
2. Add the board files to Vivado:
   Add the following line to Vivado startup script `~/.Xilinx/Vivado/Vivado_init.tcl` (if the file doesn't exist, add it):
   ```tcl
   set_param board.repoPaths [list "<full path to home directory>/workspace/RFSoC4x2-BSP"]
   ```

## Step 1: Create a Vivado Hardware Design
1. Download the TCL script [rfsoc_adc_hardware.tcl](src/vitis_adc_platform/rfsoc_adc_hardware_2023_2_1.tcl) to `~/workspace`.
2. Open Vivado and source the TCL script in a TCL shell, or simply do
   ```bash
   vivado -source rfsoc_adc_hardware_2023_2_1.tcl
   ```
   to generate the following block design:
   ![hardware design](Figures/rfsoc_adc_block_design.png)
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
     -tclargs --hardware_tcl ~/workspace/rfsoc_adc_hardware_2023_2_1.tcl
   ```
   The checker creates a temporary project, validates the block design, and should end with:
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

4. Run synthesis, implementation, and bitstream generation, then export the platform `rfsoc_adc_hardware.xsa` for hardware and platform `rfsoc_adc_hardware_emu.xsa` for hardware emulation. Vitis will not see the new stream metadata until the `.xsa` is regenerated from the updated Vivado design.

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

     &gem1 {
        status = "okay";
        phy-handle = <&phy0>;
        phy-mode = "rgmii-id";
        /* pinctrl-names = "default";
        pinctrl-0 = <&pinctrl_gem1_default>; */
        phy0: phy@f {
                reg = <0xf>;
                ti,rx-internal-delay = <0x8>;
                ti,tx-internal-delay = <0xa>;
                ti,fifo-depth = <0x1>;
                ti,dp83867-rxctrl-strap-quirk;
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
     
## Step 3: Create a Vitis Platform Component
Download the Python script [`create_rfsoc_adc_vitis_platform.py`](src/vitis_adc_platform/create_rfsoc_adc_vitis_platform.py) to `~/workspace` and run
```shell
vitis -s create_rfsoc_adc_vitis_platform.py
```
to create and build the platform component `rfsoc_adc_vitis_platform` in `~/workspace`. You can also run the python script line by line in the Vitis interactive mode (`vitis -i`).

If you previously built the single-stream version or a platform without RFDC clock IDs `3` and `4`, create a fresh platform component or delete the old `~/workspace/rfsoc_adc_vitis_platform` first. This avoids Vitis using cached stream or clock metadata. After exporting a new `.xsa`, the Vitis platform must be regenerated before the application project is configured or rebuilt.
 
## Step 4: Test the Vitis Platform on the RFSoC4x2 board
0. Start Vitis Unified IDE:
   ```shell
   vitis -w ~/workspace
   ```
1. Create a new Vitis system project from template:
   - Add Vitis example templates:
     - Go to **<em>View->Examples</em>** or click the `Examples` button on the left window edge to open the EXAMPLES view
     - Click the `Download` (a downarrow pointing to a bar) button to install the templates from the **<em>Vitis Accel Examples Repository</em>**
     - Only need to do this once
   - Select **<em>Vitis Accel Examples Repository->Host Examples->Data Transfer (C)</em>** in the EXAMPLES view to open up the example.
   - Click the `Create Application from Template` button to create a system project from the example template:
     - Name the project `test_adc`. Press the `Next` button.
     - Select the `rfsoc_adc_vitis_platform` created in Step 3. If the platform doesn't show up as a choice, you can press the **+** button to add it. Press the `Next` button.
     - Enter `Embedded Component Paths`:
       - `Kernel Image`: Click the `Browse` button to select `~/workspace/rfsoc-linux/images/linux/Image`.
       - `Root FS`: Click the `Browse` button to select `~/workspace/rfsoc-linux/images/linux/rootfs.ext4`.
       - `Sysroot`: Click the `Browse` button to select `~/workspace/rfsoc-linux/images/linux/sysroots/cortexa72-cortexa53-xilinx-linux`.
       - Check the `Update Workspace Preference` box so that you do not need to enter the info again.
       - Press the `Next` and the `Finish` buttons to generate the project.
   - You should see the following three components added to the WORKSPACE view:
     - **test_adc [rfsoc_adc_vitis_platform]**: System project
     - **test_adc_dummy_kernel [HLS]**: HLS component
     - **test_adc_host [Application]**: Application component    
  
2. Modify the HLS kernel and host source codes and build the project:
   If reusing an existing `test_adc` system project, reconfigure it against the regenerated `rfsoc_adc_vitis_platform` first. Then replace the HLS kernel and host sources and update the V++ connectivity below. A project created for an older platform does not have the current four-stream kernel interface.
   - Modify sources:
     - Under the WORKSPACE view, replace the template file `dummy_kernel.cpp` in **test_adc_dummy_kernel [HLS]->Sources** with this [`dummy_kernel.cpp`](src/vitis_adc_platform/dummy_kernel.cpp).
     - Replace the template file `host.cpp` in **test_adc_host [Application]->Sources->src** with this [`host.cpp`](src/vitis_adc_platform/host.cpp).
     - Configure **test_adc_dummy_kernel [HLS]** for the RFDC tile 0 AXI4-Stream clock before exporting its `.xo`. If its HLS configuration targets the device part directly, use:
       ```
       [hls]
       clock=13.020833ns
       ```
       If its HLS configuration targets the Vitis platform, use:
       ```
       freqhz=76800000
       ```
       This HLS synthesis target and the separate `[clock] id=3:dummy_kernel_1` linker setting below are both required. Clock ID `3` is the native RFDC tile 0 `clk_adc0` output.
       Do not bind this streaming kernel to the unrelated `400 MHz` PL clock merely because it is faster. Each RFDC producer emits one 128-bit word per `clk_adc0` cycle at `76.8 MHz`. This preserves the proven eight-sample real RFDC word format while decimation 8 reduces the per-channel sample rate to `614.4 MS/s`.
     - The kernel arguments are now `buffer0`, `data_in`, `trigger_in`, `adc_b_in`, `adc_a_in`, `ext_trigger_in`, `size`, and `output_words`. The host code sets `size` as kernel argument index `6`, because the five AXIS inputs precede the scalar arguments.
     - The kernel requires the host's fixed 2048-word frame size. It continuously writes all four ADC streams into one full-frame circular UltraRAM buffer through one uninterrupted `II=1` acquisition loop. After a rising edge on `PPS_TRIG_AXIS` and the 80% post-trigger interval, it freezes the ring and copies the chronological waveform to DDR as packed 512-bit words.
   - Specify `v++` linker connectivity:
     - Under the WORKSPACE view, open the configuration file `dummy_kernel-link.cfg` in **test_adc [rfsoc_adc_vitis_platform]->Sources->hw_link**
     - Click the **</>** button to show the config source text and add the following lines to the file: 
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
     - If the link step reports that clock ID `3`, an `RFDC_*_AXIS`, or `PPS_TRIG_AXIS` tag cannot be found, rebuild the Vivado design, re-export the `.xsa`, and regenerate the Vitis platform from the new `.xsa`. Clock ID `3` is the common RFDC stream clock, tile 0 `clk_adc0`, at `76.8 MHz`.
   - Disable SD card image generation:
     - Under the WORKSPACE view, open the configuration file `package.cfg` in **test_adc [rfsoc_adc_vitis_platform]->Sources->package**
     - Check the box under **Do not create image**
   - Build:
     - Under the FLOW view, select `test_adc` in **Component**   
     - Click **:hammer: HARDWARE->Build All** to build the project
     - After rebuilding, verify that the generated HLS report targets `76.8 MHz`. For example, a roughly 2048-cycle `write_triggered_waveform` pipeline should report approximately `26.67 us`.

3. Boot up the RFSoC board from an SD card:
   - Insert the SD card into a card reader on the host machine running Vitis. Check its device name:
     ```shell
     lsblk -r -O
     ```
     For example, my SD card is `/dev/sdj`. In the commands below, replace `/dev/sdX` with the actual SD card device.
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
     sudo cp ~/workspace/test_adc/build/hw/package/package/sd_card/* mnt/
     sync
     sudo umount mnt
     ```
     This four-channel decimation change modifies the Vivado hardware platform. Update the full generated `sd_card` directory for this rebuild, not only the host executable and `dummy_kernel.xclbin`.
   - Put the SD card into the microSD slot of the RFSoC4x2 board.
     Use a USB cable to connect the Linux host to the JTAG/UART port on the RFSoC4x2 board.
     Also connect the Ethernet port to a DHCP server if available.
     On the host, run to connect to the UART port (install `picocom` if needed):
     ```shell
     sudo picocom -b 115200 /dev/ttyUSB1
     ```
     Boot up the RFSoC4x2 board.
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

4. Configure and turn on the reference clock chips (LMK04828 and LMX2594) via SPI:
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
   - Unpack the pure-Python package and run the script on the board. This does
     not require `python3-pip`:
     ```shell
     cd /home/root
     tar -xzf ./xrfclk-2.0.tar.gz
     PYTHONPATH=/home/root/xrfclk-2.0 python3 ./set_ref_clocks.py
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
     PYTHONPATH=/home/root/xrfclk-2.0 \
       python3 /home/root/set_ref_clocks.py
     ```
5. Run the `test_adc` app to grab samples from the ADC:
   ```shell
   cd /run/media/boot-mmcblk0p1/
   chmod +x test_adc_host
   ./test_adc_host dummy_kernel.xclbin
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
   The FPGA trigger decision uses only `PPS_TRIG_AXIS`. Drive the board `1PPS` SMA with a valid pulse before expecting the app to complete.
   `wave.txt` and the Ethernet stream contain four columns/channels: `RFDC_DATA_AXIS`/ADC_D, `RFDC_TRIG_AXIS`/ADC_C, `RFDC_ADC_B_AXIS`/ADC_B, and `RFDC_ADC_A_AXIS`/ADC_A. Each frame contains about 20% pretrigger and 80% post-trigger samples; for the default frame size, the trigger word is near sample `3272`.
   Check the captured samples with:
   ```shell
   ls -lh wave.txt
   head wave.txt
   ```
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

   If the program stops at `Waiting for trigger for frame 0`, XRT has programmed the PL and launched the compute unit, but the HLS kernel is probably waiting for a rising edge on `PPS_TRIG_AXIS`. Confirm the PPS pulse at the SMA, re-arm the PPS ILA, and check that `pps_trigger_axis_ready` goes high while the kernel is running. Recheck the reference clock setup above and inspect the XRT logs:
   ```shell
   dmesg | grep -i -E 'zocl|xrt|fpga|rfdc|spi|clock'
   dmesg | tail -80
   ```
   The host application can also stream repeated captures over Ethernet. Each frame contains 16384 four-channel sample rows. At 614.4 MS/s, each frame spans about 26.67 us; streaming at 60 Hz is about 7.9 MB/s of ADC payload. TCP is the simplest option. On the PC, start the receiver from this repository:
   ```shell
   python3 src/vitis_adc_platform/receive_wave_stream.py --mode tcp --bind 0.0.0.0 --port 5000 --plot
   ```
   Then run the sender on the board, replacing `192.168.2.1` with the PC Ethernet IP address:
   ```shell
   cd /run/media/boot-mmcblk0p1/
   ./test_adc_host dummy_kernel.xclbin --tcp 192.168.2.1 5000 --rate 1000 --frames 0
   ```
   Use `--frames 600` instead of `--frames 0` to send ten seconds of data at 60 Hz. UDP is also supported; start the receiver with `--mode udp` and run the board application with `--udp 192.168.2.1 5000`. UDP frames are split into smaller packets and reassembled by the Python receiver.

   Here is an example plot of the captured samples when a 2 MHz sinusoid is fed to the ADC-D SMA connector:
   ![2 MHz sinusoid](Figures/sin2M.png)

## Validate the Four-Channel Hardware Build
Complete this test after the PPS-enabled Vitis build. The purpose is to verify sample continuity and measure whether the cross-tile behavior is sufficient before deciding whether RFDC multi-tile synchronization is required.

1. For the first boot of this static hardware build, copy the complete generated SD-card directory to the FAT32 boot partition:

   ```shell
   sudo cp -a \
     ~/workspace/test_adc/build/hw/package/package/sd_card/. \
     /path/to/mounted/boot/
   sync
   ```

2. Boot the board, log in as `root`, and configure the RF reference clocks. Repeat the clock configuration after every power cycle:

   ```shell
   modprobe spidev
   PYTHONPATH=/home/root/xrfclk-2.0 \
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
   chmod +x test_adc_host
   ./test_adc_host dummy_kernel.xclbin
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
     ./test_adc_host dummy_kernel.xclbin \
       --wave /home/root/four_channel_runs/before_power_cycle/wave_${i}.txt || break
   done
   ```

10. Power-cycle the board, configure the RF reference clocks again, and save ten more captures:

    ```shell
    mkdir -p /home/root/four_channel_runs/after_power_cycle
    cd /run/media/boot-mmcblk0p1/

    for i in $(seq -w 1 10); do
      ./test_adc_host dummy_kernel.xclbin \
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

## Step 5: Run Software and Hardware Emulation
1. Software Emulation:
   - Need to first install [Xilinx Runtime Library](https://www.xilinx.com/products/design-tools/vitis/xrt.html#gettingstarted) on the host machine running Vitis.
   - Build:
     - Under the FLOW view, select `test_adc` in **Component**   
     - Click **:hammer: SOFTWARE EMULATION->Build All** to build the project
   - Run:
     - Click **SOFTWARE EMULATION->Run** (**Debug**) to run (debug) the application
     - I haven't figured out how (there is a way in the Vitis manual but haven't gotten to test that) to emulate streaming samples to the dummy kernel. As a result, the run will stall. Hit the **Debug** (a traingle with a bug) button on the left side to show the DEBUG view and you may stop the emulation there.
    
2. Hardware Emulation:
   - It appears that Vitis 2023.2.1 doesn't support hardware emulation for the `xczu48dr` chip on the RFSoC4x2 board.
   - In fact, Vitis doesn't seem to recognize the `xczu48dr` chip:
      - In `vitis-comp.json` created for the Vitis platform, the field `supportedFamily` is set to the generic value `fpga`, rather than the value `zynquplusRFSOC` exported by Vivado.
      - The choice **HARDWARE EMULATION->Start Emulator** doesn't show up under the FLOW view. The hardware emulation build still runs fine (need to uncheck the **Do not create image** box in `package.cfg`), but QEMU hangs after it is started from the script file provided.
   - I tried to manually change all instances of `zynquplusRFSOC` to `zynquplus` in the file `xsa.json` in the hardware archives `rfsoc_adc_hardware.xsa` and `rfsoc_adc_hardware_emu.xsa`, and the value of the field `supportedFamily` in `vitis-comp.json` to `zynquplus` in order to trick Vitis into thinking `xczu48dr` was a `zynquplus`. The choice **HARDWARE EMULATION->Start Emulator** showed up under the FLOW view, but QEMU still hung.
