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
* load streamed ADC samples from ZU48DR to global memory.
* 7/20/2023
*/

#include "ap_int.h"
#include "ap_axi_sdata.h"
#include "hls_stream.h"

#define STREAM_WIDTH 128
#define CHANNEL_COUNT 4
#define PACKED_WIDTH (CHANNEL_COUNT * STREAM_WIDTH)
#define CAPTURE_WORDS 2048
#define PRETRIGGER_WORDS (CAPTURE_WORDS / 5)
#define POSTTRIGGER_WORDS (CAPTURE_WORDS - PRETRIGGER_WORDS - 1)

typedef ap_axis<STREAM_WIDTH, 0, 0, 0> pkt;
typedef ap_uint<32> trigger_pkt;

static ap_uint<PACKED_WIDTH> pack_stream_words(pkt data_value,
                                               pkt trigger_value,
                                               pkt adc_b_value,
                                               pkt adc_a_value)
{
#pragma HLS INLINE
    ap_uint<PACKED_WIDTH> packed = 0;
    packed.range(STREAM_WIDTH - 1, 0) = data_value.data;
    packed.range(2 * STREAM_WIDTH - 1, STREAM_WIDTH) = trigger_value.data;
    packed.range(3 * STREAM_WIDTH - 1, 2 * STREAM_WIDTH) = adc_b_value.data;
    packed.range(4 * STREAM_WIDTH - 1, 3 * STREAM_WIDTH) = adc_a_value.data;
    return packed;
}

static ap_uint<PACKED_WIDTH> read_packed_word(hls::stream<pkt>& data_in,
                                              hls::stream<pkt>& trigger_in,
                                              hls::stream<pkt>& adc_b_in,
                                              hls::stream<pkt>& adc_a_in)
{
#pragma HLS INLINE
    pkt data_value = data_in.read();
    pkt trigger_value = trigger_in.read();
    pkt adc_b_value = adc_b_in.read();
    pkt adc_a_value = adc_a_in.read();
    return pack_stream_words(data_value, trigger_value, adc_b_value, adc_a_value);
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
                  hls::stream<pkt>& adc_b_in,
                  hls::stream<pkt>& adc_a_in,
                  hls::stream<trigger_pkt>& ext_trigger_in,
                  unsigned int size,
                  unsigned int output_words) {
#pragma HLS INTERFACE m_axi port = buffer0 bundle = gmem0
#pragma HLS INTERFACE axis port = data_in
#pragma HLS INTERFACE axis port = trigger_in
#pragma HLS INTERFACE axis port = adc_b_in
#pragma HLS INTERFACE axis port = adc_a_in
#pragma HLS INTERFACE axis port = ext_trigger_in

    if (size != CAPTURE_WORDS || output_words < CAPTURE_WORDS) {
        return;
    }

    ap_uint<PACKED_WIDTH> capture_buffer[CAPTURE_WORDS];
#pragma HLS BIND_STORAGE variable=capture_buffer type=ram_2p impl=uram latency=2

    unsigned int write_idx = 0;
    unsigned int pretrigger_count = 0;
    unsigned int posttrigger_count = 0;
    bool pretrigger_ready = false;
    bool previous_ext_trigger_level = false;
    bool ext_trigger_armed = false;
    bool triggered = false;
    bool capture_complete = false;

capture_external_trigger:
    while (!capture_complete) {
#pragma HLS PIPELINE II = 1
#pragma HLS DEPENDENCE variable=capture_buffer inter false
        ap_uint<PACKED_WIDTH> packed =
            read_packed_word(data_in, trigger_in, adc_b_in, adc_a_in);
        trigger_pkt ext_trigger_word = ext_trigger_in.read();

        capture_buffer[write_idx] = packed;
        advance_index(write_idx, CAPTURE_WORDS);

        bool ext_trigger_level = ext_trigger_word[0];
        if (!ext_trigger_level) {
            ext_trigger_armed = true;
        }
        bool crossing =
            ext_trigger_armed && !previous_ext_trigger_level && ext_trigger_level;
        if (crossing) {
            ext_trigger_armed = false;
        }
        previous_ext_trigger_level = ext_trigger_level;

        if (!pretrigger_ready) {
            pretrigger_count++;
            if (pretrigger_count == PRETRIGGER_WORDS) {
                pretrigger_ready = true;
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
