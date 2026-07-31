#ifndef BDT_NORM_CONFIG_H
#define BDT_NORM_CONFIG_H

/*
 * Global scalar z-score used by the deployed CsI Conifer model.
 *
 * The original ml_ready/norm_stats.npy is not present in this repository.
 * These float32 constants are reconstructed from
 * csi_bdt_prj_kv260/pynq_data/X_test.npy. That array contains normalized
 * integer ADC values on the exact lattice
 *
 *     normalized = (adc_count - mean) * inverse_sigma.
 *
 * Raw counts -1, 0, and +1 map to -1.40844965, +0.138947397, and
 * +1.68634439, respectively.
 */
#define BDT_NORM_MEAN (-0.0897942781f)
#define BDT_NORM_INV_SIGMA 1.54739702f

#endif
