#!/usr/bin/env python3
"""Export one BDT training waveform as Siglent SDG arbitrary-waveform data."""

import argparse
import csv
from pathlib import Path


DEFAULT_DURATION_US = 30.0
DEFAULT_AMPLITUDE_VPP = 1.0
DEFAULT_MAX_CODE = 32767
np = None


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Convert one row of a 1250-bin BDT training waveform array into "
            "signed 16-bit arbitrary-waveform samples for a Siglent SDG."
        )
    )
    parser.add_argument(
        "waveforms",
        type=Path,
        help="Input .npy array, for example ml_ready/X_train.npy",
    )
    parser.add_argument(
        "--index",
        type=int,
        default=0,
        help="Row index to export. Default: 0",
    )
    parser.add_argument(
        "--output-prefix",
        type=Path,
        default=Path("siglent_bdt_wave"),
        help="Output prefix. Default: siglent_bdt_wave",
    )
    parser.add_argument(
        "--mode",
        choices=("normalize", "counts"),
        default="normalize",
        help=(
            "normalize: scale the selected waveform to the requested Vpp; "
            "counts: preserve ADC-count amplitude using --adc-counts-per-volt. "
            "Default: normalize"
        ),
    )
    parser.add_argument(
        "--target-peak-counts",
        type=float,
        help=(
            "Scale the baseline-subtracted waveform so its absolute peak is "
            "this many ADC counts before converting to volts. Requires "
            "--mode counts."
        ),
    )
    parser.add_argument(
        "--adc-counts-per-volt",
        type=float,
        help="ADC counts per input volt. Required with --mode counts.",
    )
    parser.add_argument(
        "--norm-stats",
        type=Path,
        help=(
            "Optional .npy with [mean, sigma]. If the input row is z-score "
            "normalized, this restores raw training units before export."
        ),
    )
    parser.add_argument(
        "--amplitude-vpp",
        type=float,
        default=DEFAULT_AMPLITUDE_VPP,
        help="Siglent channel amplitude setting in Vpp. Default: 1.0",
    )
    parser.add_argument(
        "--offset-v",
        type=float,
        default=0.0,
        help="Siglent channel offset setting in volts. Default: 0",
    )
    parser.add_argument(
        "--center",
        choices=("median", "mean", "first", "none"),
        default="median",
        help="Baseline removal before scaling. Default: median",
    )
    parser.add_argument(
        "--headroom",
        type=float,
        default=0.95,
        help="Fraction of DAC full scale used in normalize mode. Default: 0.95",
    )
    parser.add_argument(
        "--invert",
        action="store_true",
        help="Invert the waveform polarity before export.",
    )
    parser.add_argument(
        "--duration-us",
        type=float,
        default=DEFAULT_DURATION_US,
        help=(
            "One output waveform period in microseconds. The 1250 input bins "
            "are interpolated across this duration. Default: 30.0"
        ),
    )
    parser.add_argument(
        "--awg-sample-rate-hz",
        type=float,
        help=(
            "Optional Siglent arbitrary-waveform sample rate. When set, the "
            "1250-bin waveform is linearly resampled so this sample rate "
            "preserves the requested waveform period."
        ),
    )
    parser.add_argument(
        "--burst-repetition-hz",
        type=float,
        help=(
            "Optional external or CH2 trigger repetition rate for the Siglent "
            "burst setup. This is recorded in the settings file and does not "
            "change the arbitrary waveform point spacing."
        ),
    )
    parser.add_argument(
        "--max-code",
        type=int,
        default=DEFAULT_MAX_CODE,
        help="Positive full-scale signed short code. Default: 32767",
    )
    parser.add_argument(
        "--allow-clipping",
        action="store_true",
        help="Allow clipping instead of failing when counts mode exceeds full scale.",
    )
    return parser.parse_args()


def baseline(values, mode):
    if mode == "median":
        return float(np.median(values))
    if mode == "mean":
        return float(np.mean(values))
    if mode == "first":
        return float(values[0])
    return 0.0


def load_waveform(path, index):
    waveforms = np.load(path)
    if waveforms.ndim != 2:
        raise ValueError(f"{path} must be a 2-D array, got shape {waveforms.shape}")
    if not 0 <= index < waveforms.shape[0]:
        raise ValueError(f"--index {index} is outside array with {waveforms.shape[0]} rows")
    if waveforms.shape[1] != 1250:
        raise ValueError(
            f"Expected 1250 waveform bins, got {waveforms.shape[1]}. "
            "Use --duration-us only for timing changes, not length changes."
        )
    return waveforms[index].astype(np.float64)


def apply_norm_stats(values, path):
    if path is None:
        return values, None

    stats = np.load(path).reshape(-1).astype(np.float64)
    if stats.size < 2:
        raise ValueError("--norm-stats must contain at least [mean, sigma]")
    mean = float(stats[0])
    sigma = float(stats[1])
    if sigma == 0.0:
        raise ValueError("--norm-stats sigma must be nonzero")
    return values * sigma + mean, (mean, sigma)


def resample_waveform(values, output_points):
    if output_points <= 0:
        raise ValueError("Output point count must be positive")
    if output_points == values.size:
        return values

    input_x = np.linspace(0.0, 1.0, values.size)
    output_x = np.linspace(0.0, 1.0, output_points)
    return np.interp(output_x, input_x, values)


def waveform_period_seconds(args):
    if args.duration_us <= 0.0:
        raise ValueError("--duration-us must be positive")
    return args.duration_us * 1e-6


def output_timing(args, input_points, requested_period_s):
    if args.awg_sample_rate_hz is None:
        point_rate_hz = input_points / requested_period_s
        return input_points, requested_period_s, point_rate_hz

    if args.awg_sample_rate_hz <= 0.0:
        raise ValueError("--awg-sample-rate-hz must be positive")

    output_points = int(round(args.awg_sample_rate_hz * requested_period_s))
    if output_points < 8:
        raise ValueError(
            "--awg-sample-rate-hz is too low for the requested period; "
            "Siglent SDG arbitrary waveforms need at least 8 points"
        )
    actual_period_s = output_points / args.awg_sample_rate_hz
    return output_points, actual_period_s, args.awg_sample_rate_hz


def make_codes(values, args):
    if args.amplitude_vpp <= 0.0:
        raise ValueError("--amplitude-vpp must be positive")
    if not 0.0 < args.headroom <= 1.0:
        raise ValueError("--headroom must be in the range (0, 1]")
    if args.max_code <= 0 or args.max_code > 32767:
        raise ValueError("--max-code must be in the range 1..32767")

    center_value = baseline(values, args.center)
    centered = values - center_value
    if args.invert:
        centered = -centered

    peak_count_scale = None
    if args.target_peak_counts is not None:
        if args.mode != "counts":
            raise ValueError("--target-peak-counts requires --mode counts")
        if args.target_peak_counts <= 0.0:
            raise ValueError("--target-peak-counts must be positive")
        peak_counts = float(np.max(np.abs(centered)))
        if peak_counts == 0.0:
            raise ValueError("Selected waveform is flat after baseline removal")
        peak_count_scale = args.target_peak_counts / peak_counts
        centered = centered * peak_count_scale

    if args.mode == "normalize":
        peak = float(np.max(np.abs(centered)))
        if peak == 0.0:
            raise ValueError("Selected waveform is flat after baseline removal")
        scaled = centered / peak * args.max_code * args.headroom
        codes = np.rint(scaled)
    else:
        if args.adc_counts_per_volt is None or args.adc_counts_per_volt <= 0.0:
            raise ValueError("--mode counts requires positive --adc-counts-per-volt")
        volts_from_counts = centered / args.adc_counts_per_volt
        scaled = volts_from_counts / (args.amplitude_vpp / 2.0) * args.max_code
        clipped = np.any((scaled < -args.max_code) | (scaled > args.max_code))
        if clipped and not args.allow_clipping:
            required_vpp = 2.0 * float(np.max(np.abs(volts_from_counts)))
            raise ValueError(
                "Counts-mode waveform exceeds the requested amplitude. "
                f"Use --amplitude-vpp at least {required_vpp:.6g}, "
                "choose normalize mode, or pass --allow-clipping."
            )
        codes = np.rint(np.clip(scaled, -args.max_code, args.max_code))

    codes = np.clip(codes, -args.max_code, args.max_code).astype("<i2")
    volts = args.offset_v + (codes.astype(np.float64) / args.max_code) * (
        args.amplitude_vpp / 2.0
    )
    return centered, codes, volts, center_value, peak_count_scale


def write_csv(path, raw, centered, codes, volts):
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["index", "training_value", "centered_value", "dac_code", "voltage"])
        for i, (raw_value, centered_value, code, voltage) in enumerate(
            zip(raw, centered, codes, volts)
        ):
            writer.writerow(
                [
                    i,
                    f"{raw_value:.10g}",
                    f"{centered_value:.10g}",
                    int(code),
                    f"{voltage:.10g}",
                ]
            )


def write_settings(path,
                   args,
                   input_points,
                   output_points,
                   center_value,
                   codes,
                   requested_period_s,
                   actual_period_s,
                   point_rate_hz,
                   norm_stats,
                   peak_count_scale):
    arb_frequency_hz = point_rate_hz / output_points
    with path.open("w") as handle:
        handle.write("Siglent SDG arbitrary waveform settings\n")
        handle.write("======================================\n")
        handle.write(f"Input file: {args.waveforms}\n")
        handle.write(f"Input row: {args.index}\n")
        handle.write(f"Mode: {args.mode}\n")
        if norm_stats is not None:
            mean, sigma = norm_stats
            handle.write(f"Undo normalization: mean={mean:.10g}, sigma={sigma:.10g}\n")
        handle.write(f"Baseline mode: {args.center}\n")
        handle.write(f"Removed baseline: {center_value:.10g}\n")
        if args.target_peak_counts is not None:
            handle.write(f"Target peak: {args.target_peak_counts:.10g} ADC counts\n")
            handle.write(f"Peak-count scale: {peak_count_scale:.10g}\n")
        handle.write(f"Input points: {input_points}\n")
        handle.write(f"Output points: {output_points}\n")
        handle.write(f"Requested period: {requested_period_s * 1e6:.10g} us\n")
        handle.write(f"Actual period: {actual_period_s * 1e6:.10g} us\n")
        handle.write(f"Arb frequency: {arb_frequency_hz:.10g} Hz\n")
        handle.write(f"Point rate: {point_rate_hz:.10g} samples/s\n")
        if args.burst_repetition_hz is not None:
            handle.write(f"Burst repetition: {args.burst_repetition_hz:.10g} Hz\n")
        handle.write(f"Channel amplitude: {args.amplitude_vpp:.10g} Vpp\n")
        handle.write(f"Channel offset: {args.offset_v:.10g} V\n")
        handle.write(f"DAC code min/max: {int(codes.min())} / {int(codes.max())}\n")
        handle.write("\n")
        handle.write("Use the .bin file as signed 16-bit arbitrary data for SCPI loading.\n")
        handle.write("Use the .csv file for inspection or for copying into an EasyWave template.\n")
        handle.write("Set the Siglent channel amplitude and offset to the values above.\n")
        if args.burst_repetition_hz is not None:
            handle.write("For PPS tests, set CH1 to N-cycle burst with one cycle per trigger.\n")
            handle.write("Use CH2 or an external source as the burst trigger at this repetition rate.\n")


def main():
    args = parse_args()
    if args.burst_repetition_hz is not None and args.burst_repetition_hz <= 0.0:
        raise SystemExit("--burst-repetition-hz must be positive")

    global np
    try:
        import numpy as np_module
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "NumPy is required to read .npy waveforms. "
            "Run this script in the same Python environment used for BDT training."
        ) from exc

    np = np_module
    raw_input = load_waveform(args.waveforms, args.index)
    raw, norm_stats = apply_norm_stats(raw_input, args.norm_stats)
    requested_period_s = waveform_period_seconds(args)
    output_points, actual_period_s, point_rate_hz = output_timing(
        args, raw.size, requested_period_s
    )
    raw = resample_waveform(raw, output_points)
    centered, codes, volts, center_value, peak_count_scale = make_codes(raw, args)

    prefix = args.output_prefix
    prefix.parent.mkdir(parents=True, exist_ok=True)
    bin_path = prefix.with_suffix(".bin")
    csv_path = prefix.with_suffix(".csv")
    settings_path = prefix.with_suffix(".settings.txt")

    codes.tofile(bin_path)
    write_csv(csv_path, raw, centered, codes, volts)
    write_settings(settings_path,
                   args,
                   raw_input.size,
                   raw.size,
                   center_value,
                   codes,
                   requested_period_s,
                   actual_period_s,
                   point_rate_hz,
                   norm_stats,
                   peak_count_scale)

    print(f"Wrote {bin_path}")
    print(f"Wrote {csv_path}")
    print(f"Wrote {settings_path}")
    print(f"Input points: {raw_input.size}")
    print(f"Output points: {raw.size}")
    print(f"Arb frequency: {point_rate_hz / raw.size:.6g} Hz")
    print(f"Point rate: {point_rate_hz:.6g} samples/s")
    if args.burst_repetition_hz is not None:
        print(f"Burst repetition: {args.burst_repetition_hz:.6g} Hz")
    print(f"Set channel amplitude: {args.amplitude_vpp:.6g} Vpp")
    print(f"Set channel offset: {args.offset_v:.6g} V")


if __name__ == "__main__":
    main()
