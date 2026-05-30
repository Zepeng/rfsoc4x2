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

typedef ap_axis<STREAM_WIDTH, 0, 0, 0> pkt;

extern "C" {
void dummy_kernel(ap_uint<PACKED_WIDTH>* buffer0,
                  hls::stream<pkt>& data_in,
                  hls::stream<pkt>& trigger_in,
                  unsigned int size,
                  unsigned int output_words) {
#pragma HLS INTERFACE m_axi port = buffer0 bundle = gmem0
#pragma HLS INTERFACE axis port = data_in
#pragma HLS INTERFACE axis port = trigger_in

    if (output_words < size) {
        return;
    }

capture_two_channels:
    for (unsigned int i = 0; i < size; i++) {
#pragma HLS PIPELINE II = 1
        pkt data_value = data_in.read();
        pkt trigger_value = trigger_in.read();
        ap_uint<PACKED_WIDTH> packed = 0;
        packed.range(STREAM_WIDTH - 1, 0) = data_value.data;
        packed.range(PACKED_WIDTH - 1, STREAM_WIDTH) = trigger_value.data;
        buffer0[i] = packed;
    }
}
}
