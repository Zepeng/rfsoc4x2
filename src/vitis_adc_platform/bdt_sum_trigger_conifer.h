#ifndef BDT_SUM_TRIGGER_CONIFER_H
#define BDT_SUM_TRIGGER_CONIFER_H

#include "ap_fixed.h"
#include "ap_int.h"

#include "BDT.h"
#include "parameters.h"

#ifndef BDT_TREE_SCORES_EXTERNAL
#include "BDT.cpp"
#endif

#include "bdt_feature_indices.h"

#ifdef BDT_USE_NORM_CONFIG
#include "bdt_norm_config.h"
#endif

#ifndef BDT_NORM_MEAN
#define BDT_NORM_MEAN 0.0f
#endif

#ifndef BDT_NORM_INV_SIGMA
#define BDT_NORM_INV_SIGMA 1.0f
#endif

static_assert(BDT_MODEL_INPUTS == n_features,
              "BDT feature-index count must match conifer n_features");

static input_t bdt_preprocess_sample(sum_sample_t sample)
{
#pragma HLS INLINE
    ap_fixed<32, 16> normalized =
        ((ap_fixed<32, 16>)sample - (ap_fixed<32, 16>)BDT_NORM_MEAN) *
        (ap_fixed<32, 16>)BDT_NORM_INV_SIGMA;
    ap_fixed<18, 8, AP_TRN, AP_SAT> saturated = normalized;
    return (input_t)saturated;
}

static bdt_score_raw_t bdt_score_to_raw(score_t score)
{
#pragma HLS INLINE
    ap_int<BDT_SCORE_BITS> score_bits;
    score_bits.range(BDT_SCORE_BITS - 1, 0) =
        score.range(BDT_SCORE_BITS - 1, 0);
    return (bdt_score_raw_t)score_bits;
}

static bdt_score_raw_t bdt_sum_score(
    const sum_sample_t downsample_history[BDT_SOURCE_BINS],
    unsigned int start_index,
    bool& score_valid,
    bool& score_real)
{
#pragma HLS INLINE off
    input_arr_t features;
#pragma HLS ARRAY_PARTITION variable=features complete

bdt_prepare_features:
    for (unsigned int i = 0; i < n_features; ++i) {
#pragma HLS PIPELINE II = 1
        unsigned int offset = BDT_FEATURE_INDEX[i];
        unsigned int index = circular_offset(start_index,
                                             offset,
                                             BDT_SOURCE_BINS);
        features[i] = bdt_preprocess_sample(downsample_history[index]);
    }

    score_t score[BDT::fn_classes(n_classes)];
#pragma HLS ARRAY_PARTITION variable=score complete
    bdt.decision_function(features, score);

    score_valid = true;
    score_real = true;
    return bdt_score_to_raw(score[0]);
}

#endif
