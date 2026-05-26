#!/usr/bin/env python3
"""Receive streamed ADC frames from the RFSoC Vitis ADC example."""

import argparse
import socket
import struct
import time
from pathlib import Path

import numpy as np

TCP_HEADER = struct.Struct(">4sHHQQII")
UDP_HEADER = struct.Struct(">4sHHQQIHHII")
TCP_MAGIC = b"RFT1"
UDP_MAGIC = b"RFU1"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Receive binary ADC frames sent by test_adc --tcp/--udp."
    )
    parser.add_argument(
        "--mode",
        choices=("tcp", "udp"),
        default="tcp",
        help="Receive TCP or UDP frames. Default: tcp",
    )
    parser.add_argument(
        "--bind",
        default="0.0.0.0",
        help="Local interface to bind. Default: 0.0.0.0",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Local port to listen on. Default: 5000",
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=0,
        help="Number of frames to receive. Use 0 for unlimited. Default: 0",
    )
    parser.add_argument(
        "--plot",
        action="store_true",
        help="Live-plot received frames.",
    )
    parser.add_argument(
        "--plot-count",
        type=int,
        default=4096,
        help="Number of samples to plot from each frame. Default: 4096",
    )
    parser.add_argument(
        "--save-dir",
        type=Path,
        help="Directory for saved frames. Created if needed.",
    )
    parser.add_argument(
        "--save-text",
        action="store_true",
        help="Save each received frame as wave_XXXXXXXX.txt.",
    )
    parser.add_argument(
        "--save-npy",
        action="store_true",
        help="Save each received frame as wave_XXXXXXXX.npy.",
    )
    return parser.parse_args()


def recv_exact(sock, size):
    chunks = []
    remaining = size
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("socket closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def payload_to_samples(payload):
    return np.frombuffer(payload, dtype="<i2").copy()


def print_frame(frame_id, sample_rate_hz, samples, start_time):
    elapsed = time.monotonic() - start_time
    print(
        f"frame={frame_id} samples={samples.size} "
        f"sample_rate={sample_rate_hz}Hz elapsed={elapsed:.3f}s "
        f"min={samples.min()} max={samples.max()} mean={samples.mean():.2f}"
    )


def save_frame(args, frame_id, samples):
    if not args.save_text and not args.save_npy:
        return
    if args.save_dir is None:
        args.save_dir = Path(".")
    args.save_dir.mkdir(parents=True, exist_ok=True)

    stem = args.save_dir / f"wave_{frame_id:08d}"
    if args.save_text:
        np.savetxt(stem.with_suffix(".txt"), samples, fmt="%d")
    if args.save_npy:
        np.save(stem.with_suffix(".npy"), samples)


class LivePlot:
    def __init__(self, plot_count):
        import matplotlib.pyplot as plt

        self.plt = plt
        self.plot_count = plot_count
        self.fig, self.ax = plt.subplots(figsize=(10, 4), constrained_layout=True)
        self.line, = self.ax.plot([], [], linewidth=1.0)
        self.ax.set_xlabel("Sample index")
        self.ax.set_ylabel("Amplitude (signed 16-bit)")
        self.ax.grid(True, alpha=0.3)
        plt.ion()
        plt.show(block=False)

    def update(self, frame_id, samples):
        count = samples.size if self.plot_count == 0 else min(self.plot_count, samples.size)
        y = samples[:count]
        x = np.arange(count)
        self.line.set_data(x, y)
        self.ax.set_title(f"ADC frame {frame_id}")
        self.ax.set_xlim(0, max(1, count - 1))
        ymin = int(y.min()) if y.size else -1
        ymax = int(y.max()) if y.size else 1
        if ymin == ymax:
            ymin -= 1
            ymax += 1
        margin = max(1, int(0.05 * (ymax - ymin)))
        self.ax.set_ylim(ymin - margin, ymax + margin)
        self.fig.canvas.draw_idle()
        self.plt.pause(0.001)


def handle_frame(args, plotter, frame_id, sample_rate_hz, payload, start_time):
    samples = payload_to_samples(payload)
    print_frame(frame_id, sample_rate_hz, samples, start_time)
    save_frame(args, frame_id, samples)
    if plotter:
        plotter.update(frame_id, samples)


def receive_tcp(args, plotter):
    start_time = time.monotonic()
    received = 0

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((args.bind, args.port))
        server.listen(1)
        print(f"Listening for TCP on {args.bind}:{args.port}")
        conn, addr = server.accept()
        with conn:
            print(f"Accepted connection from {addr[0]}:{addr[1]}")
            while args.frames == 0 or received < args.frames:
                header = recv_exact(conn, TCP_HEADER.size)
                magic, version, header_size, frame_id, sample_rate_hz, sample_count, payload_bytes = TCP_HEADER.unpack(header)
                if magic != TCP_MAGIC or version != 1 or header_size != TCP_HEADER.size:
                    raise RuntimeError("invalid TCP frame header")
                expected_bytes = sample_count * np.dtype("<i2").itemsize
                if payload_bytes != expected_bytes:
                    raise RuntimeError("TCP payload size does not match sample count")
                payload = recv_exact(conn, payload_bytes)
                handle_frame(args, plotter, frame_id, sample_rate_hz, payload, start_time)
                received += 1


def receive_udp(args, plotter):
    start_time = time.monotonic()
    received = 0
    pending = {}

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((args.bind, args.port))
        print(f"Listening for UDP on {args.bind}:{args.port}")
        while args.frames == 0 or received < args.frames:
            packet, addr = sock.recvfrom(65535)
            if len(packet) < UDP_HEADER.size:
                continue

            fields = UDP_HEADER.unpack(packet[:UDP_HEADER.size])
            magic, version, header_size, frame_id, sample_rate_hz, sample_count, chunk_index, chunk_count, payload_offset, chunk_bytes = fields
            if magic != UDP_MAGIC or version != 1 or header_size != UDP_HEADER.size:
                continue
            payload = packet[UDP_HEADER.size:]
            if len(payload) != chunk_bytes:
                continue

            frame = pending.get(frame_id)
            if frame is None:
                frame = {
                    "sample_rate_hz": sample_rate_hz,
                    "sample_count": sample_count,
                    "chunks": [None] * chunk_count,
                    "received": 0,
                    "first_seen": time.monotonic(),
                }
                pending[frame_id] = frame

            if chunk_index >= len(frame["chunks"]):
                continue
            if frame["chunks"][chunk_index] is None:
                frame["chunks"][chunk_index] = payload
                frame["received"] += 1

            if frame["received"] == len(frame["chunks"]):
                assembled = b"".join(frame["chunks"])
                expected_bytes = frame["sample_count"] * np.dtype("<i2").itemsize
                if len(assembled) == expected_bytes:
                    handle_frame(args, plotter, frame_id, frame["sample_rate_hz"], assembled, start_time)
                    received += 1
                del pending[frame_id]

            now = time.monotonic()
            stale = [fid for fid, frame in pending.items() if now - frame["first_seen"] > 2.0]
            for fid in stale:
                del pending[fid]


def main():
    args = parse_args()
    plotter = LivePlot(args.plot_count) if args.plot else None
    if args.mode == "tcp":
        receive_tcp(args, plotter)
    else:
        receive_udp(args, plotter)


if __name__ == "__main__":
    main()
