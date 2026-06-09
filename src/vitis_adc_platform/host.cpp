/**
* Copyright (C) 2019-2021 Xilinx, Inc
*
* Licensed under the Apache License, Version 2.0 (the "License"). You may
* not use this file except in compliance with the License. A copy of the
* License is located at
*
*     http://www.apache.org/licenses/LICENSE-2.0
*
* Unless required by applicable law or agreed to in writing, software
* distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
* WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
* License for the specific language governing permissions and limitations
* under the License.
*/

/* Modified by Tan F. Wong to serve as a simple example host code
* to load streamed samples from ADC0 on ZU48DR.
* 7/20/2023
*/

#include "xcl2.hpp"
#include "ap_int.h"

#include <arpa/inet.h>
#include <errno.h>
#include <netdb.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#define DATA_SIZE 2048
#define STREAM_WIDTH 128
#define CHANNEL_COUNT 4
#define PACKED_WIDTH (CHANNEL_COUNT * STREAM_WIDTH)

typedef ap_uint<PACKED_WIDTH> data_t;

static const size_t SAMPLES_PER_WORD = STREAM_WIDTH / 16;
static const size_t SAMPLES_PER_FRAME = DATA_SIZE * SAMPLES_PER_WORD;
static const size_t PACKED_WORDS_PER_FRAME = DATA_SIZE;
static const size_t METADATA_WORDS_PER_FRAME = 1;
static const size_t PACKED_WORDS_PER_TRANSFER =
    PACKED_WORDS_PER_FRAME + METADATA_WORDS_PER_FRAME;
static const double BDT_SCORE_SCALE = 1024.0;
static const double DEFAULT_SAMPLE_RATE_HZ = 614.4e6;
static const double DEFAULT_FRAME_RATE_HZ = 1000.0;
static const char* HOST_BUILD_TAG =
    "test_adc host build: PPS plus sum-threshold trigger and BDT score";

enum class StreamMode {
    NONE,
    TCP,
    UDP,
};

struct Options {
    std::string binary_file;
    StreamMode stream_mode = StreamMode::NONE;
    std::string host;
    std::string port;
    double frame_rate_hz = DEFAULT_FRAME_RATE_HZ;
    double sample_rate_hz = DEFAULT_SAMPLE_RATE_HZ;
    uint64_t frames = 1;
    bool save_wave = true;
    std::string wave_file = "wave.txt";
    size_t udp_payload_bytes = 1400;
};

static void usage(const char* argv0)
{
    std::cout
        << HOST_BUILD_TAG << "\n\n"
        << "Usage:\n"
        << "  " << argv0 << " <XCLBIN File>\n"
        << "  " << argv0 << " <XCLBIN File> --tcp <host> <port> [options]\n"
        << "  " << argv0 << " <XCLBIN File> --udp <host> <port> [options]\n\n"
        << "Four-channel build: external 1PPS rising edge arms candidate captures in FPGA.\n"
        << "The kernel returns only events whose channel-sum waveform passes the\n"
        << "sum-maximum threshold and prints a BDT score for design verification.\n"
        << "wave.txt rows are: <ADC_D> <ADC_C> <ADC_B> <ADC_A>.\n"
        << "Each waveform contains about 20% pretrigger and 80% post-trigger samples.\n\n"
        << "Options:\n"
        << "  --rate <Hz>          Host pacing limit for streaming. Set above the PPS rate.\n"
        << "                       Default: 1000\n"
        << "  --frames <N>         Number of frames to send. Use 0 to stream until stopped.\n"
        << "                       Default: 1 without networking, 0 with networking.\n"
        << "  --sample-rate <Hz>   ADC sample rate written into frame headers.\n"
        << "                       Default: 614.4e6\n"
        << "  --wave <file>        Also save captured samples as text. In streaming\n"
        << "                       mode this file is overwritten each frame.\n"
        << "  --no-wave            Do not write wave.txt in one-shot mode.\n"
        << "  --udp-payload <B>    Max ADC payload bytes per UDP packet. Default: 1400\n";
}

static uint64_t parse_u64(const std::string& value, const std::string& name)
{
    char* end = nullptr;
    errno = 0;
    unsigned long long result = strtoull(value.c_str(), &end, 10);
    if (errno != 0 || end == value.c_str() || *end != '\0') {
        throw std::runtime_error("Invalid integer for " + name + ": " + value);
    }
    return static_cast<uint64_t>(result);
}

static double parse_double(const std::string& value, const std::string& name)
{
    char* end = nullptr;
    errno = 0;
    double result = strtod(value.c_str(), &end);
    if (errno != 0 || end == value.c_str() || *end != '\0') {
        throw std::runtime_error("Invalid number for " + name + ": " + value);
    }
    return result;
}

static Options parse_args(int argc, char** argv)
{
    if (argc == 2 && (std::string(argv[1]) == "-h" ||
                      std::string(argv[1]) == "--help" ||
                      std::string(argv[1]) == "--version")) {
        usage(argv[0]);
        exit(EXIT_SUCCESS);
    }

    if (argc < 2) {
        usage(argv[0]);
        exit(EXIT_FAILURE);
    }

    Options options;
    options.binary_file = argv[1];

    for (int i = 2; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--tcp" || arg == "--udp") {
            if (i + 2 >= argc) {
                throw std::runtime_error(arg + " requires <host> <port>");
            }
            if (options.stream_mode != StreamMode::NONE) {
                throw std::runtime_error("Only one of --tcp or --udp can be used");
            }
            options.stream_mode = (arg == "--tcp") ? StreamMode::TCP : StreamMode::UDP;
            options.host = argv[++i];
            options.port = argv[++i];
            options.frames = 0;
            options.save_wave = false;
        } else if (arg == "--rate") {
            if (++i >= argc) {
                throw std::runtime_error("--rate requires a value");
            }
            options.frame_rate_hz = parse_double(argv[i], "--rate");
        } else if (arg == "--frames") {
            if (++i >= argc) {
                throw std::runtime_error("--frames requires a value");
            }
            options.frames = parse_u64(argv[i], "--frames");
        } else if (arg == "--sample-rate") {
            if (++i >= argc) {
                throw std::runtime_error("--sample-rate requires a value");
            }
            options.sample_rate_hz = parse_double(argv[i], "--sample-rate");
        } else if (arg == "--wave") {
            if (++i >= argc) {
                throw std::runtime_error("--wave requires a file path");
            }
            options.wave_file = argv[i];
            options.save_wave = true;
        } else if (arg == "--no-wave") {
            options.save_wave = false;
        } else if (arg == "--udp-payload") {
            if (++i >= argc) {
                throw std::runtime_error("--udp-payload requires a value");
            }
            options.udp_payload_bytes = static_cast<size_t>(parse_u64(argv[i], "--udp-payload"));
        } else if (arg == "-h" || arg == "--help") {
            usage(argv[0]);
            exit(EXIT_SUCCESS);
        } else {
            throw std::runtime_error("Unknown argument: " + arg);
        }
    }

    if (options.frame_rate_hz <= 0.0) {
        throw std::runtime_error("--rate must be positive");
    }
    if (options.sample_rate_hz <= 0.0) {
        throw std::runtime_error("--sample-rate must be positive");
    }
    if (options.udp_payload_bytes == 0 || options.udp_payload_bytes > 60000) {
        throw std::runtime_error("--udp-payload must be between 1 and 60000");
    }

    return options;
}

static void append_bytes(std::vector<uint8_t>& out, const void* data, size_t size)
{
    const uint8_t* bytes = static_cast<const uint8_t*>(data);
    out.insert(out.end(), bytes, bytes + size);
}

static void append_u16(std::vector<uint8_t>& out, uint16_t value)
{
    uint16_t be = htons(value);
    append_bytes(out, &be, sizeof(be));
}

static void append_u32(std::vector<uint8_t>& out, uint32_t value)
{
    uint32_t be = htonl(value);
    append_bytes(out, &be, sizeof(be));
}

static void append_u64(std::vector<uint8_t>& out, uint64_t value)
{
    for (int shift = 56; shift >= 0; shift -= 8) {
        out.push_back(static_cast<uint8_t>((value >> shift) & 0xff));
    }
}

static uint64_t sample_rate_header_value(double sample_rate_hz)
{
    return static_cast<uint64_t>(sample_rate_hz + 0.5);
}

static std::vector<uint8_t> make_tcp_header(uint64_t frame_id,
                                            uint64_t sample_rate_hz,
                                            uint32_t sample_count,
                                            uint32_t payload_bytes)
{
    std::vector<uint8_t> header;
    header.reserve(32);
    append_bytes(header, "RFT3", 4);
    append_u16(header, 3);
    append_u16(header, 32);
    append_u64(header, frame_id);
    append_u64(header, sample_rate_hz);
    append_u32(header, sample_count);
    append_u32(header, payload_bytes);
    return header;
}

static std::vector<uint8_t> make_udp_header(uint64_t frame_id,
                                            uint64_t sample_rate_hz,
                                            uint32_t sample_count,
                                            uint16_t chunk_index,
                                            uint16_t chunk_count,
                                            uint32_t payload_offset,
                                            uint32_t chunk_bytes)
{
    std::vector<uint8_t> header;
    header.reserve(40);
    append_bytes(header, "RFU3", 4);
    append_u16(header, 3);
    append_u16(header, 40);
    append_u64(header, frame_id);
    append_u64(header, sample_rate_hz);
    append_u32(header, sample_count);
    append_u16(header, chunk_index);
    append_u16(header, chunk_count);
    append_u32(header, payload_offset);
    append_u32(header, chunk_bytes);
    return header;
}

static int open_socket(const Options& options)
{
    struct addrinfo hints;
    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = (options.stream_mode == StreamMode::TCP) ? SOCK_STREAM : SOCK_DGRAM;

    struct addrinfo* results = nullptr;
    int rc = getaddrinfo(options.host.c_str(), options.port.c_str(), &hints, &results);
    if (rc != 0) {
        throw std::runtime_error(std::string("getaddrinfo failed: ") + gai_strerror(rc));
    }

    int fd = -1;
    for (struct addrinfo* ai = results; ai != nullptr; ai = ai->ai_next) {
        fd = socket(ai->ai_family, ai->ai_socktype, ai->ai_protocol);
        if (fd < 0) {
            continue;
        }
        if (connect(fd, ai->ai_addr, ai->ai_addrlen) == 0) {
            break;
        }
        close(fd);
        fd = -1;
    }
    freeaddrinfo(results);

    if (fd < 0) {
        throw std::runtime_error("Failed to connect to " + options.host + ":" + options.port);
    }
    return fd;
}

static void send_all(int fd, const void* data, size_t size)
{
    const uint8_t* bytes = static_cast<const uint8_t*>(data);
    size_t sent = 0;
    while (sent < size) {
        ssize_t rc = send(fd, bytes + sent, size - sent, 0);
        if (rc < 0) {
            if (errno == EINTR) {
                continue;
            }
            throw std::runtime_error(std::string("send failed: ") + strerror(errno));
        }
        if (rc == 0) {
            throw std::runtime_error("send failed: socket closed");
        }
        sent += static_cast<size_t>(rc);
    }
}

static void send_tcp_frame(int fd,
                           uint64_t frame_id,
                           uint64_t sample_rate_hz,
                           const std::vector<int16_t>& samples)
{
    if ((samples.size() % CHANNEL_COUNT) != 0) {
        throw std::runtime_error("Four-channel TCP payload has an invalid sample count");
    }
    uint32_t sample_count = static_cast<uint32_t>(samples.size() / CHANNEL_COUNT);
    uint32_t payload_bytes = static_cast<uint32_t>(samples.size() * sizeof(samples[0]));
    std::vector<uint8_t> header = make_tcp_header(frame_id, sample_rate_hz, sample_count, payload_bytes);
    send_all(fd, header.data(), header.size());
    send_all(fd, samples.data(), payload_bytes);
}

static void send_udp_frame(int fd,
                           uint64_t frame_id,
                           uint64_t sample_rate_hz,
                           const std::vector<int16_t>& samples,
                           size_t udp_payload_bytes)
{
    if ((samples.size() % CHANNEL_COUNT) != 0) {
        throw std::runtime_error("Four-channel UDP payload has an invalid sample count");
    }
    const uint8_t* payload = reinterpret_cast<const uint8_t*>(samples.data());
    size_t payload_bytes = samples.size() * sizeof(samples[0]);
    size_t chunk_count_size = (payload_bytes + udp_payload_bytes - 1) / udp_payload_bytes;
    if (chunk_count_size > 65535) {
        throw std::runtime_error("Too many UDP chunks; increase --udp-payload");
    }

    uint16_t chunk_count = static_cast<uint16_t>(chunk_count_size);
    for (uint16_t chunk = 0; chunk < chunk_count; ++chunk) {
        size_t offset = static_cast<size_t>(chunk) * udp_payload_bytes;
        size_t chunk_bytes = std::min(udp_payload_bytes, payload_bytes - offset);
        std::vector<uint8_t> packet = make_udp_header(
            frame_id,
            sample_rate_hz,
            static_cast<uint32_t>(samples.size() / CHANNEL_COUNT),
            chunk,
            chunk_count,
            static_cast<uint32_t>(offset),
            static_cast<uint32_t>(chunk_bytes));
        append_bytes(packet, payload + offset, chunk_bytes);

        ssize_t rc = send(fd, packet.data(), packet.size(), 0);
        if (rc < 0) {
            throw std::runtime_error(std::string("UDP send failed: ") + strerror(errno));
        }
        if (static_cast<size_t>(rc) != packet.size()) {
            throw std::runtime_error("UDP send wrote a partial packet");
        }
    }
}

static void pack_interleaved_channel_samples(
    const std::vector<data_t, aligned_allocator<data_t> >& source_hw_data,
    std::vector<int16_t>& samples)
{
    if (source_hw_data.size() < PACKED_WORDS_PER_FRAME) {
        throw std::runtime_error("Unexpected four-channel hardware buffer size");
    }

    samples.clear();
    samples.reserve(SAMPLES_PER_FRAME * CHANNEL_COUNT);
    for (size_t i = 0; i < DATA_SIZE; ++i) {
        ap_uint<STREAM_WIDTH> data_word =
            source_hw_data[i].range(STREAM_WIDTH - 1, 0);
        ap_uint<STREAM_WIDTH> trigger_word =
            source_hw_data[i].range(2 * STREAM_WIDTH - 1, STREAM_WIDTH);
        ap_uint<STREAM_WIDTH> adc_b_word =
            source_hw_data[i].range(3 * STREAM_WIDTH - 1, 2 * STREAM_WIDTH);
        ap_uint<STREAM_WIDTH> adc_a_word =
            source_hw_data[i].range(4 * STREAM_WIDTH - 1, 3 * STREAM_WIDTH);
        for (size_t j = 0; j < SAMPLES_PER_WORD; ++j) {
            samples.push_back(static_cast<int16_t>(static_cast<short>(data_word & 0xffff)));
            samples.push_back(static_cast<int16_t>(static_cast<short>(trigger_word & 0xffff)));
            samples.push_back(static_cast<int16_t>(static_cast<short>(adc_b_word & 0xffff)));
            samples.push_back(static_cast<int16_t>(static_cast<short>(adc_a_word & 0xffff)));
            data_word >>= 16;
            trigger_word >>= 16;
            adc_b_word >>= 16;
            adc_a_word >>= 16;
        }
    }
}

struct FrameMetadata {
    int32_t bdt_score_raw = 0;
    uint64_t metadata_low64 = 0;
    bool bdt_score_valid = false;
    bool bdt_score_real = false;

    double bdt_score() const
    {
        return static_cast<double>(bdt_score_raw) / BDT_SCORE_SCALE;
    }
};

static FrameMetadata extract_frame_metadata(
    const std::vector<data_t, aligned_allocator<data_t> >& source_hw_data)
{
    if (source_hw_data.size() < PACKED_WORDS_PER_TRANSFER) {
        throw std::runtime_error("Hardware buffer does not contain BDT metadata");
    }

    FrameMetadata metadata;
    data_t metadata_word = source_hw_data[PACKED_WORDS_PER_FRAME];
    uint32_t score_bits = static_cast<uint32_t>(metadata_word.range(31, 0));
    metadata.bdt_score_raw = static_cast<int32_t>(score_bits);
    metadata.metadata_low64 = static_cast<uint64_t>(metadata_word.range(63, 0));
    metadata.bdt_score_valid = (metadata_word.range(32, 32) != 0);
    metadata.bdt_score_real = (metadata_word.range(33, 33) != 0);
    return metadata;
}

static void write_wave_file(const std::string& path, const std::vector<int16_t>& samples)
{
    if ((samples.size() % CHANNEL_COUNT) != 0) {
        throw std::runtime_error("Four-channel wave payload has an invalid sample count");
    }

    FILE* fp = fopen(path.c_str(), "w");
    if (!fp) {
        throw std::runtime_error("Failed to open " + path + " for writing");
    }

    for (size_t i = 0; i < samples.size(); i += CHANNEL_COUNT) {
        fprintf(fp, "%d %d %d %d\n",
                static_cast<int>(samples[i]),
                static_cast<int>(samples[i + 1]),
                static_cast<int>(samples[i + 2]),
                static_cast<int>(samples[i + 3]));
    }
    fclose(fp);
}

int main(int argc, char** argv)
{
    Options options;
    try {
        options = parse_args(argc, argv);
    } catch (const std::exception& ex) {
        std::cerr << ex.what() << "\n\n";
        usage(argv[0]);
        return EXIT_FAILURE;
    }

    size_t vector_size_bytes = sizeof(data_t) * PACKED_WORDS_PER_TRANSFER;
    cl_int err;
    cl::Context context;
    cl::Kernel krnl;
    cl::CommandQueue q;

    std::vector<data_t, aligned_allocator<data_t> > source_hw_data(PACKED_WORDS_PER_TRANSFER);
    for (size_t i = 0; i < source_hw_data.size(); i++) {
        source_hw_data[i] = 99;
    }

    auto devices = xcl::get_xil_devices();
    auto fileBuf = xcl::read_binary_file(options.binary_file);
    cl::Program::Binaries bins{{fileBuf.data(), fileBuf.size()}};
    bool valid_device = false;
    for (unsigned int i = 0; i < devices.size(); i++) {
        auto device = devices[i];
        OCL_CHECK(err, context = cl::Context(device, nullptr, nullptr, nullptr, &err));
        OCL_CHECK(err, q = cl::CommandQueue(context, device, CL_QUEUE_PROFILING_ENABLE, &err));
        std::cout << "Trying to program device[" << i << "]: " << device.getInfo<CL_DEVICE_NAME>() << std::endl;
        cl::Program program(context, {device}, bins, nullptr, &err);
        if (err != CL_SUCCESS) {
            std::cout << "Failed to program device[" << i << "] with xclbin file!\n";
        } else {
            std::cout << "Device[" << i << "]: program successful!\n";
            OCL_CHECK(err, krnl = cl::Kernel(program, "dummy_kernel", &err));
            valid_device = true;
            break;
        }
    }
    if (!valid_device) {
        std::cout << "Failed to program any device found, exit!\n";
        return EXIT_FAILURE;
    }

    OCL_CHECK(err, cl::Buffer buffer(context, CL_MEM_USE_HOST_PTR | CL_MEM_WRITE_ONLY, vector_size_bytes,
                                    source_hw_data.data(), &err));

    unsigned int size = DATA_SIZE;
    unsigned int output_words = PACKED_WORDS_PER_TRANSFER;
    OCL_CHECK(err, err = krnl.setArg(0, buffer));
    OCL_CHECK(err, err = krnl.setArg(6, size));
    OCL_CHECK(err, err = krnl.setArg(7, output_words));

    int socket_fd = -1;
    if (options.stream_mode != StreamMode::NONE) {
        socket_fd = open_socket(options);
        std::cout << "Streaming "
                  << ((options.stream_mode == StreamMode::TCP) ? "TCP" : "UDP")
                  << " frames to " << options.host << ":" << options.port
                  << " at " << options.frame_rate_hz << " Hz\n";
    }
    size_t pretrigger_words = PACKED_WORDS_PER_FRAME / 5;
    size_t pretrigger_samples = pretrigger_words * SAMPLES_PER_WORD;
    std::cout << "External PPS trigger on PPS_TRIG_AXIS rising edge\n"
              << "Accepted events also require max(ADC_D + ADC_C + ADC_B + ADC_A) < 200\n"
              << "BDT score is printed for accepted threshold events but does not select events\n"
              << "Output columns are RFDC_DATA_AXIS/ADC_D, RFDC_TRIG_AXIS/ADC_C, "
              << "RFDC_ADC_B_AXIS/ADC_B, and RFDC_ADC_A_AXIS/ADC_A\n"
              << "Trigger word is near sample " << pretrigger_samples
              << " of " << SAMPLES_PER_FRAME << " per-channel samples\n";

    std::vector<int16_t> samples;
    uint64_t sample_rate_hz = sample_rate_header_value(options.sample_rate_hz);
    uint64_t frame_id = 0;
    auto next_frame_time = std::chrono::steady_clock::now();
    auto frame_period = std::chrono::duration<double>(1.0 / options.frame_rate_hz);

    try {
        while (options.frames == 0 || frame_id < options.frames) {
            if (frame_id == 0 || (frame_id % 60) == 0) {
                std::cout << "Waiting for trigger for frame " << frame_id << "\n";
            }
            OCL_CHECK(err, err = q.enqueueTask(krnl));
            OCL_CHECK(err, err = q.enqueueMigrateMemObjects({buffer}, CL_MIGRATE_MEM_OBJECT_HOST));
            q.finish();

            FrameMetadata metadata = extract_frame_metadata(source_hw_data);
            if (metadata.bdt_score_valid) {
                const char* score_label =
                    metadata.bdt_score_real ? "BDT" : "dummy BDT";
                std::cout << "Frame " << frame_id
                          << " " << score_label << " score: "
                          << std::setprecision(8) << metadata.bdt_score()
                          << " (raw " << metadata.bdt_score_raw << ")\n";
            } else {
                std::cout << "Frame " << frame_id
                          << " BDT score: unavailable"
                          << " (metadata low64 0x" << std::hex
                          << metadata.metadata_low64 << std::dec << ")\n";
            }

            pack_interleaved_channel_samples(source_hw_data, samples);

            if (options.stream_mode == StreamMode::TCP) {
                send_tcp_frame(socket_fd, frame_id, sample_rate_hz, samples);
            } else if (options.stream_mode == StreamMode::UDP) {
                send_udp_frame(socket_fd, frame_id, sample_rate_hz, samples, options.udp_payload_bytes);
            }

            if (options.save_wave) {
                std::cout << "Writing data to " << options.wave_file << "\n";
                write_wave_file(options.wave_file, samples);
            }

            ++frame_id;
            if (options.stream_mode == StreamMode::NONE) {
                break;
            }

            next_frame_time += std::chrono::duration_cast<std::chrono::steady_clock::duration>(frame_period);
            std::this_thread::sleep_until(next_frame_time);
        }
    } catch (const std::exception& ex) {
        if (socket_fd >= 0) {
            close(socket_fd);
        }
        std::cerr << "Runtime error: " << ex.what() << "\n";
        return EXIT_FAILURE;
    }

    if (socket_fd >= 0) {
        close(socket_fd);
    }
    return EXIT_SUCCESS;
}
