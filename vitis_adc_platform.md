# A Vitis Extensible Platform with ADC Data and Trigger Streams for RFSoC4x2 (Vitis 2023.2.1 Unified IDE)
This is an attempt to migrate [A Vitis Extensible Platform with ADC Data and Trigger Streams for RFSoC4x2](./vitis_adc_platform_classicIDE.md) to the Vitis 2023.2 Unified IDE. Steps 0 to 2 are mostly the same as those before.

The current HLS kernel is a two-stream connectivity baseline: it writes the data stream to memory and consumes the trigger stream in lockstep. Actual threshold/window trigger logic can be added after this Vitis build is proven.


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
   - ADC-D (ADC0 on tile 224) on the RFSoC4x2 board is enabled with sampling rate set to 4.9152 GSps and decimation set to 8, giving 614.4 MS/s on each exported ADC stream.
   - A second ADC slice is enabled and exported through the RFDC `m02_axis` port for use as a trigger stream.
   - The Vitis platform stream tags are `RFDC_DATA_AXIS` for `m00_axis` and `RFDC_TRIG_AXIS` for `m02_axis`.

3. Before running synthesis, optionally verify the block design and Vitis platform metadata in batch mode. From a checkout of this repository, run:
   ```bash
   vivado -mode batch -source /path/to/rfsoc4x2/src/vitis_adc_platform/check_rfsoc_adc_bd.tcl \
     -tclargs --hardware_tcl ~/workspace/rfsoc_adc_hardware_2023_2_1.tcl
   ```
   The checker creates a temporary project, validates the block design, and should end with:
   ```
   PFM m00_axis sptag = RFDC_DATA_AXIS
   PFM m02_axis sptag = RFDC_TRIG_AXIS
   CHECK PASSED: ADC slice 02, vin0_23, and exported RFDC streams are present
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

If you previously built the single-stream version of this platform, create a fresh platform component or delete the old `~/workspace/rfsoc_adc_vitis_platform` first. This avoids Vitis using cached metadata that still contains only `RFDC_AXIS`. After exporting a new `.xsa`, the Vitis platform must be regenerated before the application project is configured or rebuilt.
 
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
   If reusing an existing `test_adc` system project, reconfigure it against the regenerated `rfsoc_adc_vitis_platform` first. Then replace the HLS kernel and host sources and update the V++ connectivity below. A project created for the old single-stream platform still references `RFDC_AXIS` and `dummy_kernel_1.s_in`, and will not link against the new two-stream platform.
   - Modify sources:
     - Under the WORKSPACE view, replace the template file `dummy_kernel.cpp` in **test_adc_dummy_kernel [HLS]->Sources** with this [`dummy_kernel.cpp`](src/vitis_adc_platform/dummy_kernel.cpp).
     - Replace the template file `host.cpp` in **test_adc_host [Application]->Sources->src** with this [`host.cpp`](src/vitis_adc_platform/host.cpp).
     - The kernel arguments are now `buffer0`, `data_in`, `trigger_in`, and `size`. The host code sets `size` as kernel argument index `3`, because the second AXIS input shifts the scalar argument index.
   - Specify `v++` linker connectivity:
     - Under the WORKSPACE view, open the configuration file `dummy_kernel-link.cfg` in **test_adc [rfsoc_adc_vitis_platform]->Sources->hw_link**
     - Click the **</>** button to show the config source text and add the following lines to the file: 
       ```
       [clock]
       id=2:dummy_kernel_1

       [connectivity]
       stream_connect = RFDC_DATA_AXIS:dummy_kernel_1.data_in
       stream_connect = RFDC_TRIG_AXIS:dummy_kernel_1.trigger_in
       ```
     - If the link step reports that `RFDC_DATA_AXIS` or `RFDC_TRIG_AXIS` cannot be found, rebuild the Vivado design, re-export the `.xsa`, and regenerate the Vitis platform from the new `.xsa`.
   - Disable SD card image generation:
     - Under the WORKSPACE view, open the configuration file `package.cfg` in **test_adc [rfsoc_adc_vitis_platform]->Sources->package**
     - Check the box under **Do not create image**
   - Build:
     - Under the FLOW view, select `test_adc` in **Component**   
     - Click **:hammer: HARDWARE->Build All** to build the project

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
   - Put the SD card into the microSD slot of the RFSoC4x2 board.
     Use a USB cable to connect the Linux host to the JTAG/UART port on the RFSoC4x2 board.
     Also connect the Ethernet port to a DHCP server if available.
     On the host, run to connect to the UART port (install `picocom` if needed):
     ```shell
     sudo picocom -b 115200 /dev/ttyUSB1
     ```
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
   Reading data from device
   Writing data to wave.txt
   ```
   The samples are stored in the file `wave.txt`.
   Check the captured samples with:
   ```shell
   ls -lh wave.txt
   head wave.txt
   ```
   If the program stops at `Reading data from device`, XRT has programmed the PL and launched the compute unit, but the HLS kernel is probably waiting for ADC stream samples. Recheck the reference clock setup above and inspect the XRT logs:
   ```shell
   dmesg | grep -i -E 'zocl|xrt|fpga|rfdc|spi|clock'
   dmesg | tail -80
   ```
   The host application can also stream repeated captures over Ethernet. Each frame contains 65536 signed 16-bit samples, so streaming at 60 Hz is about 7.9 MB/s of ADC payload. TCP is the simplest option. On the PC, start the receiver from this repository:
   ```shell
   python3 src/vitis_adc_platform/receive_wave_stream.py --mode tcp --bind 0.0.0.0 --port 5000 --plot
   ```
   Then run the sender on the board, replacing `192.168.2.1` with the PC Ethernet IP address:
   ```shell
   cd /run/media/boot-mmcblk0p1/
   ./test_adc_host dummy_kernel.xclbin --tcp 192.168.2.1 5000 --rate 60 --frames 0
   ```
   Use `--frames 600` instead of `--frames 0` to send ten seconds of data at 60 Hz. UDP is also supported; start the receiver with `--mode udp` and run the board application with `--udp 192.168.2.1 5000`. UDP frames are split into smaller packets and reassembled by the Python receiver.

   Here is an example plot of the captured samples when a 2 MHz sinusoid is fed to the ADC-D SMA connector:
   ![2 MHz sinusoid](Figures/sin2M.png)

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
