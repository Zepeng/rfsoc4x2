#!/usr/bin/env python3
"""Export small HLS headers from the CsI BDT NumPy artifacts."""

from __future__ import annotations

import argparse
import ast
import math
import struct
from pathlib import Path
from typing import Iterable, List, Sequence


def _read_npy_header(path: Path):
    with path.open("rb") as handle:
        magic = handle.read(6)
        if magic != b"\x93NUMPY":
            raise ValueError(f"{path} is not a .npy file")

        major, minor = handle.read(2)
        if (major, minor) == (1, 0):
            header_len = struct.unpack("<H", handle.read(2))[0]
        elif major in (2, 3):
            header_len = struct.unpack("<I", handle.read(4))[0]
        else:
            raise ValueError(f"Unsupported .npy version {major}.{minor} in {path}")

        encoding = "utf-8" if major == 3 else "latin1"
        header = ast.literal_eval(handle.read(header_len).decode(encoding))
        data = handle.read()

    return header, data


def _unpack_npy_without_numpy(path: Path) -> List[float]:
    header, data = _read_npy_header(path)
    if header.get("fortran_order"):
        raise ValueError(f"Fortran-order arrays are not supported: {path}")

    descr = header["descr"]
    shape = header["shape"]
    count = math.prod(shape)
    if descr[0] not in ("<", ">", "|"):
        raise ValueError(f"Unsupported dtype byte order {descr!r} in {path}")

    kind = descr[1]
    itemsize = int(descr[2:])
    endian = "<" if descr[0] in ("<", "|") else ">"

    if kind == "i":
        codes = {1: "b", 2: "h", 4: "i", 8: "q"}
    elif kind == "u":
        codes = {1: "B", 2: "H", 4: "I", 8: "Q"}
    elif kind == "f":
        codes = {4: "f", 8: "d"}
    else:
        raise ValueError(f"Unsupported dtype kind {descr!r} in {path}")

    if itemsize not in codes:
        raise ValueError(f"Unsupported dtype size {descr!r} in {path}")

    expected = count * itemsize
    if len(data) < expected:
        raise ValueError(f"Truncated .npy payload in {path}")

    fmt = f"{endian}{count}{codes[itemsize]}"
    return list(struct.unpack(fmt, data[:expected]))


def load_npy(path: Path) -> List[float]:
    try:
        import numpy as np  # type: ignore
    except ImportError:
        return _unpack_npy_without_numpy(path)

    return np.load(str(path)).reshape(-1).tolist()


def format_values(values: Sequence[int], per_line: int = 12) -> str:
    lines = []
    for start in range(0, len(values), per_line):
        chunk = values[start:start + per_line]
        lines.append("    " + ", ".join(str(value) for value in chunk))
    return ",\n".join(lines)


def write_feature_indices(
    path: Path,
    indices: Sequence[int],
    capture_words: int,
    source_bins: int,
    source_start_word: int,
    source_window_words: int,
) -> None:
    if not indices:
        raise ValueError("Feature-index array is empty")
    if any(index < 0 for index in indices):
        raise ValueError("Feature indices must be non-negative")
    if capture_words <= 0 or source_bins <= 0 or source_window_words <= 0:
        raise ValueError(
            "Capture words, source bins, and source-window words must be positive"
        )
    if source_start_word < 0:
        raise ValueError("Source-start word must be non-negative")
    if source_start_word + source_window_words > capture_words:
        raise ValueError("BDT source window must fit inside the capture")
    if source_bins >= source_window_words:
        raise ValueError("Source bins must be fewer than source-window words")
    if any(index >= source_bins for index in indices):
        raise ValueError("Feature indices must be smaller than source bins")

    body = format_values(indices)
    # Pick the two-sample RFDC word nearest the center of each model time bin.
    # The source window may be a trigger-relative subset of the full capture.
    source_words = [
        source_start_word
        + (((2 * index + 1) * source_window_words) // (2 * source_bins))
        for index in indices
    ]
    source_body = format_values(source_words)
    path.write_text(
        "#ifndef BDT_FEATURE_INDICES_H\n"
        "#define BDT_FEATURE_INDICES_H\n\n"
        f"#define BDT_MODEL_INPUTS {len(indices)}\n"
        "#define BDT_SCORE_BITS 18\n"
        "#define BDT_SCORE_INTEGER_BITS 8\n"
        f"#define BDT_FEATURE_CAPTURE_WORDS {capture_words}\n"
        f"#define BDT_FEATURE_SOURCE_BINS {source_bins}\n"
        f"#define BDT_FEATURE_SOURCE_START_WORD {source_start_word}\n"
        f"#define BDT_FEATURE_SOURCE_WINDOW_WORDS {source_window_words}\n\n"
        "static const unsigned int BDT_FEATURE_INDEX[BDT_MODEL_INPUTS] = {\n"
        f"{body}\n"
        "};\n\n"
        "static const unsigned int "
        "BDT_FEATURE_SOURCE_WORD[BDT_MODEL_INPUTS] = {\n"
        f"{source_body}\n"
        "};\n\n"
        "#endif\n",
        encoding="ascii",
    )


def write_norm_config(path: Path, stats: Sequence[float]) -> None:
    if len(stats) < 2:
        raise ValueError("norm_stats.npy must contain at least [mean, sigma]")

    mean = float(stats[0])
    sigma = float(stats[1])
    inv_sigma = 1.0 / (sigma + 1.0e-8)
    if not math.isfinite(mean) or not math.isfinite(inv_sigma):
        raise ValueError("Normalization constants must be finite")

    path.write_text(
        "#ifndef BDT_NORM_CONFIG_H\n"
        "#define BDT_NORM_CONFIG_H\n\n"
        f"#define BDT_NORM_MEAN {mean:.9g}f\n"
        f"#define BDT_NORM_INV_SIGMA {inv_sigma:.9g}f\n\n"
        "#endif\n",
        encoding="ascii",
    )


def as_int_indices(values: Iterable[float]) -> List[int]:
    indices = []
    for value in values:
        index = int(value)
        if float(value) != float(index):
            raise ValueError(f"Non-integer feature index: {value}")
        indices.append(index)
    return indices


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export bdt_feature_indices.h and optional bdt_norm_config.h"
    )
    parser.add_argument(
        "--top-feat-idx",
        type=Path,
        required=True,
        help="Path to top_feat_idx.npy from csi_bdt_prj_kv260/pynq_data",
    )
    parser.add_argument(
        "--norm-stats",
        type=Path,
        help="Optional path to norm_stats.npy with [mean, sigma]",
    )
    parser.add_argument(
        "--capture-words",
        type=int,
        default=8192,
        help="Trigger-aligned capture length in two-sample AXIS words. Default: 8192",
    )
    parser.add_argument(
        "--source-bins",
        type=int,
        default=1250,
        help="Downsampled BDT source length. Default: 1250",
    )
    parser.add_argument(
        "--source-start-word",
        type=int,
        default=0,
        help=(
            "First two-sample capture word in the BDT time window. "
            "Default: 0"
        ),
    )
    parser.add_argument(
        "--source-window-words",
        type=int,
        help=(
            "Number of two-sample words covered by the BDT time window. "
            "Default: the remainder of the capture"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("src/vitis_adc_platform"),
        help="Directory for generated HLS headers",
    )
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    feature_indices = as_int_indices(load_npy(args.top_feat_idx))
    source_window_words = args.source_window_words
    if source_window_words is None:
        source_window_words = args.capture_words - args.source_start_word
    feature_header = args.output_dir / "bdt_feature_indices.h"
    write_feature_indices(
        feature_header,
        feature_indices,
        args.capture_words,
        args.source_bins,
        args.source_start_word,
        source_window_words,
    )
    print(f"Wrote {feature_header} ({len(feature_indices)} indices)")

    if args.norm_stats is not None:
        norm_header = args.output_dir / "bdt_norm_config.h"
        write_norm_config(norm_header, load_npy(args.norm_stats))
        print(f"Wrote {norm_header}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
