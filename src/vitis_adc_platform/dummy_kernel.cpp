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
#define SAMPLES_PER_WORD (STREAM_WIDTH / 16)
#define CAPTURE_WORDS 2048
#define PRETRIGGER_WORDS (CAPTURE_WORDS / 5)
#define POSTTRIGGER_WORDS (CAPTURE_WORDS - PRETRIGGER_WORDS - 1)
#define SUM_MAX_THRESHOLD 200

typedef ap_axis<STREAM_WIDTH, 0, 0, 0> pkt;
typedef ap_uint<32> trigger_pkt;
typedef ap_int<16> sample_t;
typedef ap_int<20> sum_sample_t;

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

static void read_stream_words(hls::stream<pkt>& data_in,
                              hls::stream<pkt>& trigger_in,
                              hls::stream<pkt>& adc_b_in,
                              hls::stream<pkt>& adc_a_in,
                              ap_uint<PACKED_WIDTH>& packed,
                              ap_uint<STREAM_WIDTH>& data_word,
                              ap_uint<STREAM_WIDTH>& trigger_word,
                              ap_uint<STREAM_WIDTH>& adc_b_word,
                              ap_uint<STREAM_WIDTH>& adc_a_word)
{
#pragma HLS INLINE
    pkt data_value = data_in.read();
    pkt trigger_value = trigger_in.read();
    pkt adc_b_value = adc_b_in.read();
    pkt adc_a_value = adc_a_in.read();
    data_word = data_value.data;
    trigger_word = trigger_value.data;
    adc_b_word = adc_b_value.data;
    adc_a_word = adc_a_value.data;
    packed = pack_stream_words(data_value, trigger_value, adc_b_value, adc_a_value);
}

static sample_t sign_extend_sample(ap_uint<16> raw)
{
#pragma HLS INLINE
    sample_t sample;
    sample.range(15, 0) = raw;
    return sample;
}

static void summarize_sum_word(ap_uint<STREAM_WIDTH> data_word,
                               ap_uint<STREAM_WIDTH> trigger_word,
                               ap_uint<STREAM_WIDTH> adc_b_word,
                               ap_uint<STREAM_WIDTH> adc_a_word,
                               bool& word_over_threshold)
{
#pragma HLS INLINE
    bool over_threshold = false;

sum_word_lanes:
    for (unsigned int lane = 0; lane < SAMPLES_PER_WORD; ++lane) {
#pragma HLS UNROLL
        ap_uint<16> data_raw = data_word.range(16 * lane + 15, 16 * lane);
        ap_uint<16> trigger_raw = trigger_word.range(16 * lane + 15, 16 * lane);
        ap_uint<16> adc_b_raw = adc_b_word.range(16 * lane + 15, 16 * lane);
        ap_uint<16> adc_a_raw = adc_a_word.range(16 * lane + 15, 16 * lane);

        sum_sample_t sum_sample =
            (sum_sample_t)sign_extend_sample(data_raw) +
            (sum_sample_t)sign_extend_sample(trigger_raw) +
            (sum_sample_t)sign_extend_sample(adc_b_raw) +
            (sum_sample_t)sign_extend_sample(adc_a_raw);
        if (sum_sample >= SUM_MAX_THRESHOLD) {
            over_threshold = true;
        }
    }

    word_over_threshold = over_threshold;
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

    ap_uint<1> over_threshold_ring[CAPTURE_WORDS];
#pragma HLS BIND_STORAGE variable=over_threshold_ring type=ram_2p impl=bram

init_trigger_state:
    for (unsigned int i = 0; i < CAPTURE_WORDS; ++i) {
#pragma HLS PIPELINE II = 1
        over_threshold_ring[i] = 0;
    }

    unsigned int write_idx = 0;
    unsigned int pretrigger_count = 0;
    unsigned int posttrigger_count = 0;
    unsigned int over_threshold_count = 0;
    bool pretrigger_ready = false;
    bool previous_ext_trigger_level = false;
    bool ext_trigger_armed = false;
    bool triggered = false;
    bool event_accepted = false;

capture_external_trigger:
    while (!event_accepted) {
        bool candidate_complete = false;

    capture_candidate:
        while (!candidate_complete) {
#pragma HLS PIPELINE II = 1
#pragma HLS DEPENDENCE variable=capture_buffer inter false
            ap_uint<PACKED_WIDTH> packed;
            ap_uint<STREAM_WIDTH> data_word;
            ap_uint<STREAM_WIDTH> trigger_word;
            ap_uint<STREAM_WIDTH> adc_b_word;
            ap_uint<STREAM_WIDTH> adc_a_word;
            read_stream_words(data_in,
                              trigger_in,
                              adc_b_in,
                              adc_a_in,
                              packed,
                              data_word,
                              trigger_word,
                              adc_b_word,
                              adc_a_word);
            trigger_pkt ext_trigger_word = ext_trigger_in.read();

            bool word_over_threshold = false;
            summarize_sum_word(data_word,
                               trigger_word,
                               adc_b_word,
                               adc_a_word,
                               word_over_threshold);

            bool overwritten_over_threshold = (over_threshold_ring[write_idx] != 0);
            if (overwritten_over_threshold && over_threshold_count != 0) {
                over_threshold_count--;
            }
            over_threshold_ring[write_idx] = word_over_threshold ? 1 : 0;
            if (word_over_threshold) {
                over_threshold_count++;
            }

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
                    candidate_complete = true;
                }
            }
        }

        bool sum_max_accept = (over_threshold_count == 0);
        if (sum_max_accept) {
            event_accepted = true;
        } else {
            triggered = false;
            posttrigger_count = 0;
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
