#!/usr/bin/env python3
"""Plot ADC samples captured by the RFSoC Vitis ADC example."""

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

CHANNEL_LABELS = (
    "RFDC_DATA_AXIS/ADC_D",
    "RFDC_TRIG_AXIS/ADC_C",
    "RFDC_ADC_B_AXIS/ADC_B",
    "RFDC_ADC_A_AXIS/ADC_A",
)
CHANNEL_INDEX = {
    "data": 0,
    "trigger": 1,
    "adc-b": 2,
    "adc-a": 3,
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Plot ADC samples captured by test_adc."
    )
    parser.add_argument(
        "wave_file",
        nargs="?",
        default="wave.txt",
        help="Input text file produced by test_adc. Default: wave.txt",
    )
    parser.add_argument(
        "--sample-rate",
        type=float,
        default=614.4e6,
        help="Sample rate in samples/second. Default: 614.4e6",
    )
    parser.add_argument(
        "--channel",
        choices=("data", "trigger", "adc-b", "adc-a", "both", "all"),
        default="all",
        help="Channel selection for multi-column files. Default: all",
    )
    parser.add_argument(
        "--lane-order",
        choices=("lsb-first", "msb-first"),
        default="lsb-first",
        help=(
            "Order of the 16-bit samples inside each RFDC "
            "AXIS word. Default: lsb-first"
        ),
    )
    parser.add_argument(
        "--lanes-per-word",
        type=int,
        default=8,
        help="Number of 16-bit samples in each RFDC AXIS word. Default: 8",
    )
    parser.add_argument(
        "--word-lane",
        type=int,
        metavar="N",
        help=(
            "Plot only one 16-bit sample lane from each RFDC word. "
            "This divides the effective sample rate by --lanes-per-word."
        ),
    )
    parser.add_argument(
        "--start",
        type=int,
        default=0,
        help="First sample index to plot. Default: 0",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=4096,
        help="Number of samples to plot. Use 0 for all samples. Default: 4096",
    )
    parser.add_argument(
        "--duration-us",
        type=float,
        help=(
            "Time span to plot in microseconds. Overrides --count when "
            "--sample-rate is positive."
        ),
    )
    parser.add_argument(
        "--fft",
        action="store_true",
        help="Also plot a single-sided FFT magnitude.",
    )
    parser.add_argument(
        "--save",
        type=Path,
        help="Save the plot to this file instead of only showing it.",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Do not open an interactive plot window.",
    )
    args = parser.parse_args()
    if args.lanes_per_word <= 0:
        parser.error("--lanes-per-word must be positive")
    if args.word_lane is not None and not 0 <= args.word_lane < args.lanes_per_word:
        parser.error("--word-lane must be between 0 and --lanes-per-word - 1")
    return args


def load_wave(path):
    return np.loadtxt(path, dtype=np.int16, ndmin=2)


def sample_count(samples):
    return samples.shape[0] if samples.ndim == 2 else samples.size


def apply_lane_order(samples, lane_order, lanes_per_word):
    if lane_order == "lsb-first":
        return samples

    total = sample_count(samples)
    aligned = total - (total % lanes_per_word)
    if aligned == 0:
        return samples

    head = samples[:aligned]
    tail = samples[aligned:]
    if samples.ndim == 1:
        reordered = head.reshape((-1, lanes_per_word))[:, ::-1].reshape((-1,))
    else:
        reordered = (
            head.reshape((-1, lanes_per_word, samples.shape[1]))
            [:, ::-1, :]
            .reshape((-1, samples.shape[1]))
        )

    if tail.size == 0:
        return reordered
    return np.concatenate((reordered, tail), axis=0)


def select_word_lane(samples, lane, lanes_per_word):
    if lane is None:
        return samples

    total = sample_count(samples)
    aligned = total - (total % lanes_per_word)
    if aligned == 0:
        raise ValueError("Not enough samples to select a RFDC word lane")

    return samples[lane:aligned:lanes_per_word]


def select_window(samples, start, count):
    if start < 0:
        raise ValueError("--start must be non-negative")
    if count < 0:
        raise ValueError("--count must be non-negative")
    total = sample_count(samples)
    if start >= total:
        raise ValueError(f"--start {start} is past the end of {total} samples")
    stop = total if count == 0 else min(total, start + count)
    return samples[start:stop], start, stop


def count_from_duration(duration_us, sample_rate):
    if duration_us is None:
        return None
    if duration_us <= 0.0:
        raise ValueError("--duration-us must be positive")
    if sample_rate <= 0.0:
        raise ValueError("--duration-us requires a positive --sample-rate")
    return max(1, int(round(duration_us * 1e-6 * sample_rate)))


def make_time_axis(start, stop, sample_rate):
    sample_numbers = np.arange(start, stop)
    if sample_rate > 0:
        return sample_numbers / sample_rate * 1e6, "Time (us)"
    return sample_numbers, "Sample index"


def selected_series(samples, channel):
    if samples.ndim == 1 or samples.shape[1] == 1:
        return [("ADC", samples.reshape((-1,)))]
    available = [
        (label, samples[:, index])
        for index, label in enumerate(CHANNEL_LABELS[:samples.shape[1]])
    ]
    if channel == "all":
        return available
    if channel == "both":
        return available[:2]
    index = CHANNEL_INDEX[channel]
    if index >= samples.shape[1]:
        raise ValueError(
            f"--channel {channel} requires column {index + 1}, "
            f"but the file has {samples.shape[1]} columns"
        )
    return [available[index]]


def plot_time_domain(ax, samples, start, stop, sample_rate, channel):
    x, xlabel = make_time_axis(start, stop, sample_rate)
    for label, values in selected_series(samples, channel):
        ax.plot(x, values, linewidth=1.0, label=label)
    ax.set_title(f"ADC samples [{start}:{stop}]")
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Amplitude (signed 16-bit)")
    ax.grid(True, alpha=0.3)
    if samples.ndim == 2:
        ax.legend(loc="upper right")


def plot_fft(ax, samples, sample_rate, channel):
    count = sample_count(samples)
    if sample_rate > 0:
        freq = np.fft.rfftfreq(count, d=1.0 / sample_rate) / 1e6
        xlabel = "Frequency (MHz)"
    else:
        freq = np.fft.rfftfreq(count)
        xlabel = "Normalized frequency (cycles/sample)"

    for label, values in selected_series(samples, channel):
        window = np.hanning(values.size)
        centered = values.astype(np.float64) - np.mean(values)
        spectrum = np.fft.rfft(centered * window)
        magnitude_db = 20.0 * np.log10(np.maximum(np.abs(spectrum), 1e-12))
        ax.plot(freq, magnitude_db, linewidth=1.0, label=label)

    ax.set_title("FFT magnitude")
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Magnitude (dB)")
    ax.grid(True, alpha=0.3)
    if samples.ndim == 2:
        ax.legend(loc="upper right")


def main():
    args = parse_args()
    samples = apply_lane_order(load_wave(args.wave_file), args.lane_order, args.lanes_per_word)
    samples = select_word_lane(samples, args.word_lane, args.lanes_per_word)
    sample_rate = args.sample_rate
    if args.word_lane is not None:
        sample_rate /= args.lanes_per_word
    count = count_from_duration(args.duration_us, sample_rate)
    if count is None:
        count = args.count
    window, start, stop = select_window(samples, args.start, count)

    rows = 2 if args.fft else 1
    fig, axes = plt.subplots(rows, 1, figsize=(10, 4 * rows), constrained_layout=True)
    if rows == 1:
        axes = [axes]

    plot_time_domain(axes[0], window, start, stop, sample_rate, args.channel)
    if args.fft:
        plot_fft(axes[1], window, sample_rate, args.channel)

    if args.save:
        fig.savefig(args.save, dpi=150)
    if not args.no_show:
        plt.show()


if __name__ == "__main__":
    main()
