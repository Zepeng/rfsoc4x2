"""Minimal Linux GPIO character-device helper for RFSoC4x2 clock control."""

import ctypes
import fcntl
import glob
import os


GPIOHANDLES_MAX = 64
GPIOHANDLE_REQUEST_OUTPUT = 1 << 1

_IOC_NRBITS = 8
_IOC_TYPEBITS = 8
_IOC_SIZEBITS = 14
_IOC_NRSHIFT = 0
_IOC_TYPESHIFT = _IOC_NRSHIFT + _IOC_NRBITS
_IOC_SIZESHIFT = _IOC_TYPESHIFT + _IOC_TYPEBITS
_IOC_DIRSHIFT = _IOC_SIZESHIFT + _IOC_SIZEBITS
_IOC_WRITE = 1
_IOC_READ = 2


def _ioc(direction, ioctl_type, number, size):
    return (
        (direction << _IOC_DIRSHIFT)
        | (ioctl_type << _IOC_TYPESHIFT)
        | (number << _IOC_NRSHIFT)
        | (size << _IOC_SIZESHIFT)
    )


class _GpioChipInfo(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_char * 32),
        ("label", ctypes.c_char * 32),
        ("lines", ctypes.c_uint32),
    ]


class _GpioHandleRequest(ctypes.Structure):
    _fields_ = [
        ("lineoffsets", ctypes.c_uint32 * GPIOHANDLES_MAX),
        ("flags", ctypes.c_uint32),
        ("default_values", ctypes.c_uint8 * GPIOHANDLES_MAX),
        ("consumer_label", ctypes.c_char * 32),
        ("lines", ctypes.c_uint32),
        ("fd", ctypes.c_int),
    ]


class _GpioHandleData(ctypes.Structure):
    _fields_ = [
        ("values", ctypes.c_uint8 * GPIOHANDLES_MAX),
    ]


GPIO_GET_CHIPINFO_IOCTL = _ioc(
    _IOC_READ, 0xB4, 0x01, ctypes.sizeof(_GpioChipInfo)
)
GPIO_GET_LINEHANDLE_IOCTL = _ioc(
    _IOC_READ | _IOC_WRITE, 0xB4, 0x03, ctypes.sizeof(_GpioHandleRequest)
)
GPIOHANDLE_SET_LINE_VALUES_IOCTL = _ioc(
    _IOC_READ | _IOC_WRITE, 0xB4, 0x09, ctypes.sizeof(_GpioHandleData)
)


def _ioctl_struct(fd, command, value):
    data = bytearray(bytes(value))
    fcntl.ioctl(fd, command, data, True)
    ctypes.memmove(ctypes.addressof(value), bytes(data), len(data))


def _decode(value):
    return value.split(b"\0", 1)[0].decode("utf-8", errors="replace")


def find_zynqmp_gpiochip(maximum_line):
    """Return the ZynqMP GPIO chip that exposes maximum_line."""

    candidates = []
    for path in sorted(glob.glob("/dev/gpiochip*")):
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
        try:
            info = _GpioChipInfo()
            _ioctl_struct(fd, GPIO_GET_CHIPINFO_IOCTL, info)
        finally:
            os.close(fd)

        name = _decode(info.name)
        label = _decode(info.label)
        print(f"GPIO: found {path} name={name} label={label} lines={info.lines}")
        if info.lines <= maximum_line:
            continue

        identity = f"{name} {label}".lower()
        priority = 0 if "zynqmp" in identity else 1
        candidates.append((priority, path))

    if not candidates:
        raise RuntimeError(
            f"No GPIO character device exposes line offset {maximum_line}"
        )

    candidates.sort()
    selected = candidates[0][1]
    print(f"GPIO: selected {selected}")
    return selected


class OutputLines:
    """Hold multiple GPIO lines as outputs for the lifetime of this object."""

    def __init__(self, chip_path, line_offsets, initial_values, consumer):
        if len(line_offsets) != len(initial_values):
            raise ValueError("GPIO line and initial-value counts differ")
        if not line_offsets or len(line_offsets) > GPIOHANDLES_MAX:
            raise ValueError("Invalid GPIO line count")

        self._chip_fd = -1
        self._line_fd = -1
        self._line_count = len(line_offsets)

        self._chip_fd = os.open(chip_path, os.O_RDONLY | os.O_CLOEXEC)
        request = _GpioHandleRequest()
        request.flags = GPIOHANDLE_REQUEST_OUTPUT
        request.lines = self._line_count
        request.consumer_label = consumer.encode("ascii")[:31]
        for index, (line, value) in enumerate(
            zip(line_offsets, initial_values)
        ):
            request.lineoffsets[index] = line
            request.default_values[index] = 1 if value else 0

        try:
            _ioctl_struct(
                self._chip_fd, GPIO_GET_LINEHANDLE_IOCTL, request
            )
        except Exception:
            os.close(self._chip_fd)
            self._chip_fd = -1
            raise

        self._line_fd = request.fd

    def set_values(self, values):
        if len(values) != self._line_count:
            raise ValueError("Incorrect GPIO value count")

        data = _GpioHandleData()
        for index, value in enumerate(values):
            data.values[index] = 1 if value else 0
        _ioctl_struct(
            self._line_fd, GPIOHANDLE_SET_LINE_VALUES_IOCTL, data
        )

    def close(self):
        if self._line_fd >= 0:
            os.close(self._line_fd)
            self._line_fd = -1
        if self._chip_fd >= 0:
            os.close(self._chip_fd)
            self._chip_fd = -1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

