#!/usr/bin/env python3
"""Receive triggered ADC events over TCP from test_adc and save them as a GIF or MP4.

test_adc (on the board) is the TCP client; this script is the TCP server. It collects
N events (default 10), then renders one frame per event into an animation.

Wire format (must match host.cpp): a 32-byte big-endian header per frame
    magic="RFT3", version=3, header_size=32, frame_id, sample_rate_hz,
    sample_count (per channel), payload_bytes
followed by sample_count * 4 little-endian int16 samples, interleaved as
    ADC_D, ADC_C, ADC_B, ADC_A.
"""

import argparse
import socket
import struct
from pathlib import Path

import numpy as np

TCP_HEADER = struct.Struct(">4sHHQQII")
TCP_MAGIC_V3 = b"RFT3"
CHANNEL_COUNT = 4
CHANNEL_LABELS = (
    "ADC_D",
    "ADC_C",
    "ADC_B",
    "ADC_A",
)
CHANNEL_KEYS = ("data", "trigger", "adc-b", "adc-a")


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bind", default="0.0.0.0",
                   help="Local interface to listen on. Default: 0.0.0.0")
    p.add_argument("--port", type=int, default=5000,
                   help="Local TCP port to listen on. Default: 5000")
    p.add_argument("--events", type=int, default=10,
                   help="Number of events (frames) to capture. Default: 10")
    p.add_argument("--output", type=Path, default=Path("events.gif"),
                   help="Output file. .gif -> Pillow, .mp4/.mov/.avi -> ffmpeg. "
                        "Default: events.gif")
    p.add_argument("--fps", type=float, default=2.0,
                   help="Playback frames per second (one event per frame). Default: 2")
    p.add_argument("--count", type=int, default=2000,
                   help="Samples per channel to plot from each event. 0 = all. "
                        "Default: 2000")
    p.add_argument("--start", type=int, default=0,
                   help="First sample index to plot from each event. Default: 0")
    p.add_argument("--channels", nargs="+", choices=CHANNEL_KEYS, default=list(CHANNEL_KEYS),
                   help="Channels to plot. Default: all four")
    p.add_argument("--lanes-per-word", type=int, default=2,
                   help="Decimation factor used with --word-lane: keep 1 of every N "
                        "samples (matches plot_wave.py). Default: 2")
    p.add_argument("--word-lane", type=int, default=0, metavar="N",
                   help="Keep lane N of every --lanes-per-word samples; default 0 gives "
                        "the smooth decimated view. Use -1 for full-rate (all samples). "
                        "Default: 0")
    p.add_argument("--dpi", type=int, default=110, help="Output resolution. Default: 110")
    args = p.parse_args()
    if args.events <= 0:
        p.error("--events must be positive")
    if args.lanes_per_word <= 0:
        p.error("--lanes-per-word must be positive")
    if args.word_lane != -1 and not 0 <= args.word_lane < args.lanes_per_word:
        p.error("--word-lane must be -1 (full rate) or 0..--lanes-per-word - 1")
    return args


def recv_exact(sock, size):
    chunks = []
    remaining = size
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("socket closed before frame was complete")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def receive_events(args):
    """Listen, accept one board connection, and return a list of captured events."""
    events = []
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((args.bind, args.port))
        server.listen(1)
        print(f"Listening for TCP on {args.bind}:{args.port} "
              f"(run test_adc with --tcp <this-PC-ip> {args.port})")
        conn, addr = server.accept()
        with conn:
            print(f"Connected to {addr[0]}:{addr[1]}; capturing {args.events} events...")
            while len(events) < args.events:
                magic, version, header_size, frame_id, rate, n_samp, payload_bytes = \
                    TCP_HEADER.unpack(recv_exact(conn, TCP_HEADER.size))
                if magic != TCP_MAGIC_V3 or version != 3 or header_size != TCP_HEADER.size:
                    raise RuntimeError(f"unexpected header (magic={magic!r} version={version}); "
                                       "is the board sending the 4-channel RFT3 stream?")
                expected = n_samp * CHANNEL_COUNT * 2
                if payload_bytes != expected:
                    raise RuntimeError("payload size does not match sample count")
                payload = recv_exact(conn, payload_bytes)
                samples = np.frombuffer(payload, dtype="<i2").reshape((-1, CHANNEL_COUNT))
                events.append({"frame_id": frame_id, "sample_rate": float(rate),
                               "samples": samples})
                print(f"  event {len(events)}/{args.events}: frame={frame_id} "
                      f"samples/ch={samples.shape[0]} rate={rate/1e6:.1f} MS/s")
    return events


def transform(samples, sample_rate, args):
    """Optionally keep one decimated lane, then window with --start/--count."""
    rate = sample_rate
    if args.word_lane >= 0:
        n = samples.shape[0]
        aligned = n - (n % args.lanes_per_word)
        samples = samples[args.word_lane:aligned:args.lanes_per_word]
        rate = sample_rate / args.lanes_per_word
    start = min(args.start, samples.shape[0])
    stop = samples.shape[0] if args.count == 0 else min(samples.shape[0], start + args.count)
    return samples[start:stop], rate, start


def render(events, args):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation, PillowWriter, FFMpegWriter

    cols = [CHANNEL_KEYS.index(c) for c in args.channels]

    # Pre-transform every event and find global axis limits for a stable animation.
    prepared = []
    ymin, ymax, xmax = 0, 0, 1.0
    for ev in events:
        win, rate, start = transform(ev["samples"], ev["sample_rate"], args)
        n = win.shape[0]
        x = (np.arange(start, start + n) / rate * 1e6) if rate > 0 else np.arange(start, start + n)
        prepared.append({"frame_id": ev["frame_id"], "x": x, "win": win})
        if n:
            sel = win[:, cols]
            ymin, ymax = min(ymin, int(sel.min())), max(ymax, int(sel.max()))
            xmax = max(xmax, float(x[-1]) if n > 1 else 1.0)
    xlabel = "Time (us)" if (events and events[0]["sample_rate"] > 0) else "Sample index"
    margin = max(1, int(0.05 * (ymax - ymin)))

    fig, ax = plt.subplots(figsize=(10, 4), constrained_layout=True)
    lines = [ax.plot([], [], linewidth=1.0, label=CHANNEL_LABELS[c])[0] for c in cols]
    ax.set_xlim(0, xmax)
    ax.set_ylim(ymin - margin, ymax + margin)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Amplitude (signed 16-bit)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right")

    def update(i):
        p = prepared[i]
        for line, c in zip(lines, cols):
            line.set_data(p["x"], p["win"][:, c])
        ax.set_title(f"Event {i + 1}/{len(prepared)}  (frame {p['frame_id']})")
        return lines

    anim = FuncAnimation(fig, update, frames=len(prepared), blit=False)
    suffix = args.output.suffix.lower()
    if suffix == ".gif":
        writer = PillowWriter(fps=args.fps)
    elif suffix in (".mp4", ".mov", ".avi", ".mkv"):
        writer = FFMpegWriter(fps=args.fps, bitrate=4000)
    else:
        raise SystemExit(f"unsupported output extension '{suffix}'; use .gif or .mp4")
    anim.save(str(args.output), writer=writer, dpi=args.dpi)
    plt.close(fig)
    print(f"Saved {len(prepared)} events to {args.output}")


def main():
    args = parse_args()
    events = receive_events(args)
    render(events, args)


if __name__ == "__main__":
    main()
