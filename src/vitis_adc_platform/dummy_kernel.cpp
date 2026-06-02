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

/* Slightly modified by Tan F. Wong to serve as a simple example kernel to
* load streamed samples from ADC0 on ZU48DR to global memory.
* 7/20/2023
*/

#include "ap_int.h"
#include "ap_axi_sdata.h"
#include "hls_stream.h"

#define STREAM_WIDTH 128
#define PACKED_WIDTH (2 * STREAM_WIDTH)
#define CAPTURE_WORDS 8192
#define PRETRIGGER_WORDS (CAPTURE_WORDS / 5)
#define POSTTRIGGER_WORDS (CAPTURE_WORDS - PRETRIGGER_WORDS - 1)

typedef ap_axis<STREAM_WIDTH, 0, 0, 0> pkt;

static ap_uint<PACKED_WIDTH> pack_stream_words(pkt data_value, pkt trigger_value)
{
#pragma HLS INLINE
    ap_uint<PACKED_WIDTH> packed = 0;
    packed.range(STREAM_WIDTH - 1, 0) = data_value.data;
    packed.range(PACKED_WIDTH - 1, STREAM_WIDTH) = trigger_value.data;
    return packed;
}

static ap_uint<PACKED_WIDTH> read_packed_word(hls::stream<pkt>& data_in,
                                              hls::stream<pkt>& trigger_in)
{
#pragma HLS INLINE
    pkt data_value = data_in.read();
    pkt trigger_value = trigger_in.read();
    return pack_stream_words(data_value, trigger_value);
}

static ap_int<16> get_trigger_sample(ap_uint<PACKED_WIDTH> packed)
{
#pragma HLS INLINE
    return packed.range(STREAM_WIDTH + 15, STREAM_WIDTH);
}

static void advance_index(unsigned int& index, unsigned int limit)
{
#pragma HLS INLINE
    index++;
    if (index == limit) {
        index = 0;
    }
}

extern "C" {
void dummy_kernel(ap_uint<PACKED_WIDTH>* buffer0,
                  hls::stream<pkt>& data_in,
                  hls::stream<pkt>& trigger_in,
                  unsigned int size,
                  unsigned int output_words,
                  int trigger_threshold) {
#pragma HLS INTERFACE m_axi port = buffer0 bundle = gmem0
#pragma HLS INTERFACE axis port = data_in
#pragma HLS INTERFACE axis port = trigger_in

    if (size != CAPTURE_WORDS || output_words < CAPTURE_WORDS) {
        return;
    }

    ap_uint<PACKED_WIDTH> capture_buffer[CAPTURE_WORDS];
#pragma HLS BIND_STORAGE variable=capture_buffer type=ram_2p impl=uram latency=2

    ap_int<16> threshold = trigger_threshold;
    ap_int<16> previous_trigger_sample = 0;
    unsigned int write_idx = 0;
    unsigned int pretrigger_count = 0;
    unsigned int posttrigger_count = 0;
    bool trigger_armed = false;
    bool triggered = false;
    bool capture_complete = false;

capture_adc_c_threshold:
    while (!capture_complete) {
#pragma HLS PIPELINE II = 1
#pragma HLS DEPENDENCE variable=capture_buffer inter false
        ap_uint<PACKED_WIDTH> packed = read_packed_word(data_in, trigger_in);
        capture_buffer[write_idx] = packed;
        advance_index(write_idx, CAPTURE_WORDS);

        ap_int<16> trigger_sample = get_trigger_sample(packed);
        bool crossing =
            previous_trigger_sample < threshold && trigger_sample >= threshold;
        previous_trigger_sample = trigger_sample;

        if (!trigger_armed) {
            pretrigger_count++;
            if (pretrigger_count == PRETRIGGER_WORDS) {
                trigger_armed = true;
            }
        } else if (!triggered) {
            if (crossing) {
                triggered = true;
            }
        } else {
            posttrigger_count++;
            if (posttrigger_count == POSTTRIGGER_WORDS) {
                capture_complete = true;
            }
        }
    }

    unsigned int read_idx = write_idx;

write_triggered_waveform:
    for (unsigned int out_idx = 0; out_idx < CAPTURE_WORDS; ++out_idx) {
#pragma HLS PIPELINE II = 1
        buffer0[out_idx] = capture_buffer[read_idx];
        advance_index(read_idx, CAPTURE_WORDS);
    }
}
}
