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

#include "adc_stream_config.h"

#define STREAM_WIDTH RFDC_STREAM_WIDTH
#define CHANNEL_COUNT RFDC_CHANNEL_COUNT
#define PACKED_WIDTH RFDC_PACKED_WIDTH
#define SAMPLES_PER_WORD RFDC_SAMPLES_PER_WORD
#define CAPTURE_WORDS RFDC_CAPTURE_WORDS
#define PRETRIGGER_WORDS (CAPTURE_WORDS / 5)
#define POSTTRIGGER_WORDS (CAPTURE_WORDS - PRETRIGGER_WORDS - 1)
#define SUM_GATE_DISABLED 0
#define SUM_GATE_VETO 1
#define SUM_GATE_REQUIRE 2
#define BDT_SOURCE_BINS 1250
#define BDT_SOURCE_WINDOW_WORDS 3072
#define DUMMY_BDT_FEATURES 250
#define BDT_SCORE_FRAC_BITS 10
#define BDT_SCORE_SCALE_RAW (1 << BDT_SCORE_FRAC_BITS)
#define OUTPUT_METADATA_WORDS 1
#define OUTPUT_WORDS (CAPTURE_WORDS + OUTPUT_METADATA_WORDS)

typedef ap_axis<STREAM_WIDTH, 0, 0, 0> pkt;
typedef ap_uint<32> trigger_pkt;
typedef ap_int<16> sample_t;
typedef ap_int<20> sum_sample_t;
typedef ap_int<24> sum_accum_t;
typedef ap_int<32> bdt_score_raw_t;

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

static sum_sample_t average_toward_zero(sum_accum_t accumulator)
{
#pragma HLS INLINE
    if (accumulator < 0) {
        return (sum_sample_t)(-((-accumulator) >> RFDC_WORD_AVERAGE_SHIFT));
    }
    return (sum_sample_t)(accumulator >> RFDC_WORD_AVERAGE_SHIFT);
}

static void summarize_sum_word(ap_uint<STREAM_WIDTH> data_word,
                               ap_uint<STREAM_WIDTH> trigger_word,
                               ap_uint<STREAM_WIDTH> adc_b_word,
                               ap_uint<STREAM_WIDTH> adc_a_word,
                               sum_sample_t sum_threshold,
                               bool& word_over_threshold,
                               sum_sample_t& word_average)
{
#pragma HLS INLINE
    bool over_threshold = false;
    sum_accum_t accumulator = 0;

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
        accumulator += (sum_accum_t)sum_sample;
        if (sum_sample >= sum_threshold) {
            over_threshold = true;
        }
    }

    word_over_threshold = over_threshold;
    // NumPy's mean(...).astype(np.int16), used by the training scripts,
    // truncates negative values toward zero rather than toward -infinity.
    word_average = average_toward_zero(accumulator);
}

static void advance_index(unsigned int& index, unsigned int limit)
{
#pragma HLS INLINE
    index++;
    if (index == limit) {
        index = 0;
    }
}

static unsigned int circular_offset(unsigned int start_index,
                                    unsigned int offset,
                                    unsigned int limit)
{
#pragma HLS INLINE
    unsigned int index = start_index + offset;
    if (index >= limit) {
        index -= limit;
    }
    return index;
}

static ap_uint<PACKED_WIDTH> pack_metadata(bdt_score_raw_t bdt_score_raw,
                                           bool bdt_score_valid,
                                           bool bdt_score_real)
{
#pragma HLS INLINE
    ap_uint<PACKED_WIDTH> metadata = 0;
    metadata.range(31, 0) = (ap_uint<32>)bdt_score_raw;
    metadata[32] = bdt_score_valid ? 1 : 0;
    metadata[33] = bdt_score_real ? 1 : 0;
    return metadata;
}

#ifdef USE_CONIFER_BDT
#include "bdt_sum_trigger_conifer.h"
#else
static const unsigned int BDT_FEATURE_COUNT = DUMMY_BDT_FEATURES;

static unsigned int bdt_feature_offset(unsigned int i)
{
#pragma HLS INLINE
    return i * (BDT_SOURCE_BINS / DUMMY_BDT_FEATURES);
}

static void bdt_gather_feature(ap_int<32>& accumulator,
                               unsigned int i,
                               sum_sample_t sample)
{
#pragma HLS INLINE
    accumulator += (ap_int<32>)sample;
}

static bdt_score_raw_t bdt_finalize_score(ap_int<32> accumulator,
                                          bool& score_valid,
                                          bool& score_real)
{
#pragma HLS INLINE off
    score_valid = true;
    score_real = false;
    ap_int<32> average = accumulator / DUMMY_BDT_FEATURES;
    return average * BDT_SCORE_SCALE_RAW;
}
#endif

static_assert(BDT_SOURCE_BINS < CAPTURE_WORDS,
              "BDT downsampling requires fewer output bins than capture words");
static_assert(BDT_FEATURE_COUNT <= BDT_SOURCE_BINS,
              "BDT feature count must fit inside the downsampled waveform");
static_assert(STREAM_WIDTH == SAMPLES_PER_WORD * 16,
              "Each RFDC stream lane must contain one signed 16-bit sample");
static_assert((1U << RFDC_WORD_AVERAGE_SHIFT) == SAMPLES_PER_WORD,
              "Word-average shift must match the samples per RFDC word");
static_assert(CAPTURE_WORDS * SAMPLES_PER_WORD == RFDC_SAMPLES_PER_FRAME,
              "Capture words must preserve the configured sample count");
static_assert(PRETRIGGER_WORDS + 1 + POSTTRIGGER_WORDS == CAPTURE_WORDS,
              "Accepted trigger window must initialize every capture word");
#ifdef USE_CONIFER_BDT
static_assert(BDT_FEATURE_CAPTURE_WORDS == CAPTURE_WORDS,
              "Generated BDT source-word map has the wrong capture length");
static_assert(BDT_FEATURE_SOURCE_BINS == BDT_SOURCE_BINS,
              "Generated BDT source-word map has the wrong downsample length");
static_assert(BDT_FEATURE_SOURCE_START_WORD == PRETRIGGER_WORDS,
              "BDT source window must start at the accepted PPS word");
static_assert(BDT_FEATURE_SOURCE_WINDOW_WORDS == BDT_SOURCE_WINDOW_WORDS,
              "Generated BDT source map has the wrong time-window length");
static_assert(BDT_FEATURE_SOURCE_START_WORD +
                  BDT_FEATURE_SOURCE_WINDOW_WORDS <= CAPTURE_WORDS,
              "BDT source window must fit inside the capture");
static_assert((BDT_FEATURE_COUNT % 2) == 0,
              "Two-port BDT gather requires an even feature count");
#endif

extern "C" {
void dummy_kernel(ap_uint<PACKED_WIDTH>* buffer0,
                  hls::stream<pkt>& data_in,
                  hls::stream<pkt>& trigger_in,
                  hls::stream<pkt>& adc_b_in,
                  hls::stream<pkt>& adc_a_in,
                  hls::stream<trigger_pkt>& ext_trigger_in,
                  unsigned int size,
                  unsigned int output_words,
                  unsigned int sum_gate_mode,
                  int sum_threshold) {
#pragma HLS INTERFACE m_axi port = buffer0 bundle = gmem0
#pragma HLS INTERFACE axis port = data_in
#pragma HLS INTERFACE axis port = trigger_in
#pragma HLS INTERFACE axis port = adc_b_in
#pragma HLS INTERFACE axis port = adc_a_in
#pragma HLS INTERFACE axis port = ext_trigger_in

    if (size != CAPTURE_WORDS || output_words < OUTPUT_WORDS) {
        return;
    }
    sum_sample_t active_sum_threshold = (sum_sample_t)sum_threshold;

    ap_uint<PACKED_WIDTH> capture_buffer[CAPTURE_WORDS];
#pragma HLS BIND_STORAGE variable=capture_buffer type=ram_2p impl=uram latency=2

    ap_uint<1> over_threshold_ring[CAPTURE_WORDS];
#pragma HLS BIND_STORAGE variable=over_threshold_ring type=ram_2p impl=bram

    sum_sample_t word_average_buffer[CAPTURE_WORDS];
#pragma HLS BIND_STORAGE variable=word_average_buffer type=ram_2p impl=bram

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
#pragma HLS DEPENDENCE variable=word_average_buffer inter false
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
            sum_sample_t word_average = 0;
            summarize_sum_word(data_word,
                               trigger_word,
                               adc_b_word,
                               adc_a_word,
                               active_sum_threshold,
                               word_over_threshold,
                               word_average);

            bool overwritten_over_threshold = (over_threshold_ring[write_idx] != 0);
            if (overwritten_over_threshold && over_threshold_count != 0) {
                over_threshold_count--;
            }
            over_threshold_ring[write_idx] = word_over_threshold ? 1 : 0;
            if (word_over_threshold) {
                over_threshold_count++;
            }

            capture_buffer[write_idx] = packed;
            word_average_buffer[write_idx] = word_average;
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

        bool has_over_threshold = (over_threshold_count != 0);
        bool sum_gate_accept = true;
        if (sum_gate_mode == SUM_GATE_VETO) {
            sum_gate_accept = !has_over_threshold;
        } else if (sum_gate_mode == SUM_GATE_REQUIRE) {
            sum_gate_accept = has_over_threshold;
        }
        if (sum_gate_accept) {
            event_accepted = true;
        } else {
            triggered = false;
            posttrigger_count = 0;
        }
    }

    unsigned int read_idx = write_idx;

#ifdef USE_CONIFER_BDT
    input_arr_t bdt_features;
#pragma HLS ARRAY_PARTITION variable=bdt_features complete
#pragma HLS ARRAY_PARTITION variable=BDT_FEATURE_SOURCE_WORD complete

gather_bdt_feature_pairs:
    for (unsigned int pair_idx = 0;
         pair_idx < BDT_FEATURE_COUNT / 2;
         ++pair_idx) {
#pragma HLS PIPELINE II = 1
        unsigned int feature_idx0 = 2 * pair_idx;
        unsigned int feature_idx1 = feature_idx0 + 1;
        unsigned int source_idx0 =
            circular_offset(read_idx,
                            bdt_feature_source_word(feature_idx0),
                            CAPTURE_WORDS);
        unsigned int source_idx1 =
            circular_offset(read_idx,
                            bdt_feature_source_word(feature_idx1),
                            CAPTURE_WORDS);
        sum_sample_t sample0 = word_average_buffer[source_idx0];
        sum_sample_t sample1 = word_average_buffer[source_idx1];
        bdt_gather_feature(bdt_features, feature_idx0, sample0);
        bdt_gather_feature(bdt_features, feature_idx1, sample1);
    }

    bool bdt_score_valid = false;
    bool bdt_score_real = false;
    bdt_score_raw_t bdt_score_raw =
        bdt_finalize_score(bdt_features, bdt_score_valid, bdt_score_real);

#else
    ap_int<32> bdt_features = 0;
    unsigned int downsample_accumulator = 0;
    unsigned int downsample_bin_idx = 0;
    unsigned int feature_write_idx = 0;
#endif

write_triggered_waveform:
    for (unsigned int out_idx = 0; out_idx < CAPTURE_WORDS; ++out_idx) {
#pragma HLS PIPELINE II = 1
        buffer0[out_idx] = capture_buffer[read_idx];
#ifndef USE_CONIFER_BDT
        sum_sample_t word_average = word_average_buffer[read_idx];
#endif
        advance_index(read_idx, CAPTURE_WORDS);

#ifndef USE_CONIFER_BDT
        downsample_accumulator += BDT_SOURCE_BINS;
        if (downsample_accumulator >= CAPTURE_WORDS) {
            downsample_accumulator -= CAPTURE_WORDS;
            if (feature_write_idx < BDT_FEATURE_COUNT &&
                downsample_bin_idx == bdt_feature_offset(feature_write_idx)) {
                bdt_gather_feature(bdt_features,
                                   feature_write_idx,
                                   word_average);
                feature_write_idx++;
            }
            downsample_bin_idx++;
        }
#endif
    }

#ifndef USE_CONIFER_BDT
    bool bdt_score_valid = false;
    bool bdt_score_real = false;
    bdt_score_raw_t bdt_score_raw =
        bdt_finalize_score(bdt_features, bdt_score_valid, bdt_score_real);
#endif

    buffer0[CAPTURE_WORDS] =
        pack_metadata(bdt_score_raw, bdt_score_valid, bdt_score_real);
}
}
