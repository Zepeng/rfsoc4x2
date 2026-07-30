#ifndef ADC_STREAM_CONFIG_H
#define ADC_STREAM_CONFIG_H

/*
 * RFDC AXI stream format for the two-sample-word evaluation build.
 *
 * The ADC sample rate remains 614.4 MS/s after decimation by 8. Reducing the
 * RFDC word from eight samples to two samples raises the fabric clock from
 * 76.8 MHz to 307.2 MHz. Keep the total capture at 16,384 samples/channel so
 * comparisons with the eight-sample-word build use the same time window.
 */
#define RFDC_SAMPLE_BITS 16
#define RFDC_SAMPLES_PER_WORD 2
#define RFDC_WORD_AVERAGE_SHIFT 1
#define RFDC_STREAM_WIDTH (RFDC_SAMPLE_BITS * RFDC_SAMPLES_PER_WORD)
#define RFDC_CHANNEL_COUNT 4
#define RFDC_SAMPLES_PER_FRAME 16384
#define RFDC_CAPTURE_WORDS (RFDC_SAMPLES_PER_FRAME / RFDC_SAMPLES_PER_WORD)
#define RFDC_PACKED_WIDTH (RFDC_CHANNEL_COUNT * RFDC_STREAM_WIDTH)
#define RFDC_FABRIC_CLOCK_HZ 307200000

#endif
