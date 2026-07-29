"""Create the RFSoC4x2 Linux/XRT platform with the Vitis 2025.2 Python API.

Set the required paths and run this script with the Vitis Python launcher, not
system Python:

    export RFSOC4X2_VITIS_WORKSPACE=/path/to/workspace
    export RFSOC4X2_XSA=/path/to/rfsoc_adc_hardware_2025_2.xsa
    export RFSOC4X2_LINUX_IMAGE_DIR=/path/to/rfsoc-linux/images/linux
    vitis -s create_rfsoc_adc_vitis_platform_2025_2.py

The hardware-emulation setup from the 2023.2.1 flow is intentionally excluded
from this first port. It was not functional for xczu48dr in that release and
must be re-established separately after the hardware platform builds.
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

PLATFORM_NAME = "rfsoc_adc_vitis_platform_2025_2"
DOMAIN_NAME = "xrt"
DEFAULT_CPU = "psu_cortexa53_0"


def load_vitis_api():
    try:
        import vitis
    except ModuleNotFoundError as error:
        if error.name != "vitis":
            raise
        raise SystemExit(
            "The Vitis Python API is unavailable in this interpreter.\n"
            "Run this script with the Vitis 2025.2 batch launcher:\n"
            "  vitis -s "
            "src/vitis_adc_platform/"
            "create_rfsoc_adc_vitis_platform_2025_2.py\n"
            "Do not run it with python or python3. If the command still fails, "
            "check `command -v vitis` and `vitis -v`."
        ) from None
    return vitis


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        type=Path,
        default=env_path("RFSOC4X2_VITIS_WORKSPACE"),
    )
    parser.add_argument(
        "--xsa",
        type=Path,
        default=env_path("RFSOC4X2_XSA"),
    )
    parser.add_argument(
        "--linux-image-dir",
        type=Path,
        default=env_path("RFSOC4X2_LINUX_IMAGE_DIR"),
    )
    parser.add_argument(
        "--platform-name",
        default=os.environ.get("RFSOC4X2_PLATFORM_NAME", PLATFORM_NAME),
    )
    parser.add_argument(
        "--domain-name",
        default=os.environ.get("RFSOC4X2_DOMAIN_NAME", DOMAIN_NAME),
    )
    parser.add_argument(
        "--cpu",
        default=os.environ.get("RFSOC4X2_CPU", DEFAULT_CPU),
    )
    args = parser.parse_args()
    missing = [
        option
        for option, value in (
            ("--workspace or RFSOC4X2_VITIS_WORKSPACE", args.workspace),
            ("--xsa or RFSOC4X2_XSA", args.xsa),
            (
                "--linux-image-dir or RFSOC4X2_LINUX_IMAGE_DIR",
                args.linux_image_dir,
            ),
        )
        if value is None
    ]
    if missing:
        parser.error("missing required setting(s): " + ", ".join(missing))
    return args


def env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value) if value else None


def require_file(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Required file does not exist: {resolved}")
    return resolved


def copy_boot_files(linux_image_dir: Path, boot_dir: Path) -> None:
    boot_files = (
        "bl31.elf",
        "pmufw.elf",
        "u-boot.elf",
        "system.dtb",
        "zynqmp_fsbl.elf",
        "boot.scr",
    )
    boot_dir.mkdir(parents=True, exist_ok=True)
    for filename in boot_files:
        shutil.copy2(require_file(linux_image_dir / filename), boot_dir / filename)


def write_linux_bif(boot_dir: Path) -> Path:
    bif = boot_dir / "linux.bif"
    lines = (
        "/* linux */",
        "the_ROM_image:",
        "{",
        "  [fsbl_config] a53_x64",
        f"  [bootloader] <{boot_dir / 'zynqmp_fsbl.elf'}>",
        f"  [pmufw_image] <{boot_dir / 'pmufw.elf'}>",
        "  [destination_device=pl] <bitstream>",
        (
            "  [destination_cpu=a53-0, exception_level=el-3, trustzone] "
            f"<{boot_dir / 'bl31.elf'}>"
        ),
        f"  [load=0x00100000] <{boot_dir / 'system.dtb'}>",
        (
            "  [destination_cpu=a53-0, exception_level=el-2] "
            f"<{boot_dir / 'u-boot.elf'}>"
        ),
        "}",
    )
    bif.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return bif


def require_method(obj: object, method_name: str):
    method = getattr(obj, method_name, None)
    if not callable(method):
        raise RuntimeError(
            f"Vitis 2025.2 object {type(obj).__name__} does not provide "
            f"{method_name}(). Inspect "
            "<VITIS_INSTALL>/cli/api_docs/build/html/vitis.html and update "
            "the platform resource attachment step."
        )
    return method


def main() -> None:
    args = parse_args()
    vitis = load_vitis_api()
    workspace = args.workspace.expanduser().resolve()
    xsa = require_file(args.xsa)
    linux_image_dir = args.linux_image_dir.expanduser().resolve()
    if not linux_image_dir.is_dir():
        raise NotADirectoryError(
            f"Linux image directory does not exist: {linux_image_dir}"
        )

    workspace.mkdir(parents=True, exist_ok=True)
    component_dir = workspace / args.platform_name
    if component_dir.exists():
        raise FileExistsError(
            f"Platform component already exists: {component_dir}. "
            "Use a fresh workspace or a new --platform-name."
        )

    client = vitis.create_client()
    try:
        client.set_workspace(path=str(workspace))
        platform = client.create_platform_component(
            name=args.platform_name,
            hw_design=str(xsa),
            cpu=args.cpu,
            os="linux",
            domain_name=args.domain_name,
            generate_dtb=False,
            architecture="64-bit",
            compiler="gcc",
        )

        get_domain = require_method(platform, "get_domain")
        try:
            domain = get_domain(name=args.domain_name)
        except TypeError:
            domain = get_domain(args.domain_name)
        boot_dir = component_dir / "resources" / args.domain_name / "boot"
        copy_boot_files(linux_image_dir, boot_dir)
        bif = write_linux_bif(boot_dir)

        require_method(domain, "add_boot_dir")(boot_dir=str(boot_dir))
        require_method(domain, "add_bif")(path=str(bif))

        status = platform.build()
        print(f"Platform build status: {status}")
        report = getattr(platform, "report", None)
        if callable(report):
            report()
        domain_report = getattr(domain, "report", None)
        if callable(domain_report):
            domain_report()
    finally:
        vitis.dispose()


if __name__ == "__main__":
    main()
