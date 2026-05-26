#!/usr/bin/env python3
"""Plot ADC samples captured by the RFSoC Vitis ADC example."""

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def parse_args():
    parser = argparse.ArgumentParser(
        description="Plot one-sample-per-line ADC data from wave.txt."
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
        default=2.4576e9,
        help="Sample rate in samples/second. Default: 2.4576e9",
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
    return parser.parse_args()


def load_wave(path):
    samples = np.loadtxt(path, dtype=np.int16)
    return np.atleast_1d(samples)


def select_window(samples, start, count):
    if start < 0:
        raise ValueError("--start must be non-negative")
    if count < 0:
        raise ValueError("--count must be non-negative")
    if start >= samples.size:
        raise ValueError(f"--start {start} is past the end of {samples.size} samples")
    stop = samples.size if count == 0 else min(samples.size, start + count)
    return samples[start:stop], start, stop


def make_time_axis(start, stop, sample_rate):
    sample_numbers = np.arange(start, stop)
    if sample_rate > 0:
        return sample_numbers / sample_rate * 1e6, "Time (us)"
    return sample_numbers, "Sample index"


def plot_time_domain(ax, samples, start, stop, sample_rate):
    x, xlabel = make_time_axis(start, stop, sample_rate)
    ax.plot(x, samples, linewidth=1.0)
    ax.set_title(f"ADC samples [{start}:{stop}]")
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Amplitude (signed 16-bit)")
    ax.grid(True, alpha=0.3)


def plot_fft(ax, samples, sample_rate):
    window = np.hanning(samples.size)
    centered = samples.astype(np.float64) - np.mean(samples)
    spectrum = np.fft.rfft(centered * window)
    magnitude_db = 20.0 * np.log10(np.maximum(np.abs(spectrum), 1e-12))

    if sample_rate > 0:
        freq = np.fft.rfftfreq(samples.size, d=1.0 / sample_rate) / 1e6
        xlabel = "Frequency (MHz)"
    else:
        freq = np.fft.rfftfreq(samples.size)
        xlabel = "Normalized frequency (cycles/sample)"

    ax.plot(freq, magnitude_db, linewidth=1.0)
    ax.set_title("FFT magnitude")
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Magnitude (dB)")
    ax.grid(True, alpha=0.3)


def main():
    args = parse_args()
    samples = load_wave(args.wave_file)
    window, start, stop = select_window(samples, args.start, args.count)

    rows = 2 if args.fft else 1
    fig, axes = plt.subplots(rows, 1, figsize=(10, 4 * rows), constrained_layout=True)
    if rows == 1:
        axes = [axes]

    plot_time_domain(axes[0], window, start, stop, args.sample_rate)
    if args.fft:
        plot_fft(axes[1], window, args.sample_rate)

    if args.save:
        fig.savefig(args.save, dpi=150)
    if not args.no_show:
        plt.show()


if __name__ == "__main__":
    main()
