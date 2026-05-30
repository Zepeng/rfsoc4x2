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
TCP_MAGIC_V1 = b"RFT1"
TCP_MAGIC_V2 = b"RFT2"
UDP_MAGIC_V1 = b"RFU1"
UDP_MAGIC_V2 = b"RFU2"


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


def channel_count_from_header(magic, version, mode):
    if mode == "tcp":
        if magic == TCP_MAGIC_V1 and version == 1:
            return 1
        if magic == TCP_MAGIC_V2 and version == 2:
            return 2
    else:
        if magic == UDP_MAGIC_V1 and version == 1:
            return 1
        if magic == UDP_MAGIC_V2 and version == 2:
            return 2
    return 0


def payload_to_samples(payload, channel_count):
    samples = np.frombuffer(payload, dtype="<i2").copy()
    if channel_count == 2:
        return samples.reshape((-1, 2))
    return samples


def print_frame(frame_id, sample_rate_hz, samples, start_time):
    elapsed = time.monotonic() - start_time
    if samples.ndim == 2:
        data = samples[:, 0]
        trigger = samples[:, 1]
        print(
            f"frame={frame_id} samples={samples.shape[0]} channels=2 "
            f"sample_rate={sample_rate_hz}Hz elapsed={elapsed:.3f}s "
            f"data_min={data.min()} data_max={data.max()} data_mean={data.mean():.2f} "
            f"trig_min={trigger.min()} trig_max={trigger.max()} trig_mean={trigger.mean():.2f}"
        )
    else:
        print(
            f"frame={frame_id} samples={samples.size} channels=1 "
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
        self.lines = [
            self.ax.plot([], [], linewidth=1.0, label="RFDC_DATA_AXIS")[0],
            self.ax.plot([], [], linewidth=1.0, label="RFDC_TRIG_AXIS")[0],
        ]
        self.ax.set_xlabel("Sample index")
        self.ax.set_ylabel("Amplitude (signed 16-bit)")
        self.ax.grid(True, alpha=0.3)
        self.ax.legend(loc="upper right")
        plt.ion()
        plt.show(block=False)

    def update(self, frame_id, samples):
        total = samples.shape[0] if samples.ndim == 2 else samples.size
        count = total if self.plot_count == 0 else min(self.plot_count, total)
        x = np.arange(count)
        if samples.ndim == 2:
            y_values = [samples[:count, 0], samples[:count, 1]]
        else:
            y_values = [samples[:count], np.array([], dtype=samples.dtype)]

        visible = []
        for line, y in zip(self.lines, y_values):
            line.set_data(x[:y.size], y)
            line.set_visible(y.size != 0)
            if y.size:
                visible.append(y)

        self.ax.set_title(f"ADC frame {frame_id}")
        self.ax.set_xlim(0, max(1, count - 1))
        if visible:
            all_y = np.concatenate(visible)
            ymin = int(all_y.min())
            ymax = int(all_y.max())
        else:
            ymin = -1
            ymax = 1
        if ymin == ymax:
            ymin -= 1
            ymax += 1
        margin = max(1, int(0.05 * (ymax - ymin)))
        self.ax.set_ylim(ymin - margin, ymax + margin)
        self.fig.canvas.draw_idle()
        self.plt.pause(0.001)


def handle_frame(args, plotter, frame_id, sample_rate_hz, payload, channel_count, start_time):
    samples = payload_to_samples(payload, channel_count)
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
                channel_count = channel_count_from_header(magic, version, "tcp")
                if channel_count == 0 or header_size != TCP_HEADER.size:
                    raise RuntimeError("invalid TCP frame header")
                expected_bytes = sample_count * channel_count * np.dtype("<i2").itemsize
                if payload_bytes != expected_bytes:
                    raise RuntimeError("TCP payload size does not match sample count")
                payload = recv_exact(conn, payload_bytes)
                handle_frame(args, plotter, frame_id, sample_rate_hz, payload, channel_count, start_time)
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
            channel_count = channel_count_from_header(magic, version, "udp")
            if channel_count == 0 or header_size != UDP_HEADER.size:
                continue
            payload = packet[UDP_HEADER.size:]
            if len(payload) != chunk_bytes:
                continue

            frame = pending.get(frame_id)
            if frame is None:
                frame = {
                    "sample_rate_hz": sample_rate_hz,
                    "sample_count": sample_count,
                    "channel_count": channel_count,
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
                expected_bytes = (
                    frame["sample_count"] * frame["channel_count"] * np.dtype("<i2").itemsize
                )
                if len(assembled) == expected_bytes:
                    handle_frame(
                        args,
                        plotter,
                        frame_id,
                        frame["sample_rate_hz"],
                        assembled,
                        frame["channel_count"],
                        start_time,
                    )
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
