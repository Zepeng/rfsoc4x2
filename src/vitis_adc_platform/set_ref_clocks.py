# Hacked out from the RFSoC-PYNQ distribution
# Tan F. Wong 7/20/2023

import os
import time

from xrfclk import set_ref_clks

from gpio_chardev import OutputLines, find_zynqmp_gpiochip


# The legacy sysfs GPIO IDs 341, 342, and 346 represented these ZynqMP
# controller line offsets. Character-device requests use the offsets directly.
LMK_RESET_LINE = 7
LMK_CLK_SEL0_LINE = 8
LMK_CLK_SEL1_LINE = 12


def main():
    if os.geteuid() != 0:
        raise PermissionError("Root permissions are required")

    line_offsets = [
        LMK_RESET_LINE,
        LMK_CLK_SEL0_LINE,
        LMK_CLK_SEL1_LINE,
    ]
    chip_path = os.environ.get("RFSOC4X2_GPIO_CHIP")
    if not chip_path:
        chip_path = find_zynqmp_gpiochip(max(line_offsets))

    print(
        "GPIO: LMK reset/select lines "
        f"{line_offsets} on {chip_path}"
    )
    with OutputLines(
        chip_path,
        line_offsets,
        [0, 0, 0],
        "rfsoc4x2-clocks",
    ) as clock_gpio:
        clock_gpio.set_values([1, 0, 0])
        time.sleep(0.001)
        clock_gpio.set_values([0, 0, 0])
        time.sleep(0.001)

        print("Clock: LMK04828=245.76 MHz, LMX2594=491.52 MHz")
        set_ref_clks(lmk_freq=245.76, lmx_freq=491.52)

    print("Clock: programming completed")


if __name__ == "__main__":
    main()
