`timescale 1 ns / 1 ps

module pps_trigger_axis (
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME aclk, ASSOCIATED_BUSIF m_axis, ASSOCIATED_RESET aresetn" *)
    input  wire        aclk,

    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 aresetn RST" *)
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME aresetn, POLARITY ACTIVE_LOW" *)
    input  wire        aresetn,

    input  wire        pps_in,

    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 m_axis TDATA" *)
    output wire [31:0] m_axis_tdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 m_axis TVALID" *)
    output wire        m_axis_tvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 m_axis TREADY" *)
    input  wire        m_axis_tready,

    output wire        dbg_pps_sync_level,
    output wire        dbg_axis_level,
    output wire        dbg_axis_valid
);

(* ASYNC_REG = "TRUE" *) reg [1:0] pps_sync;
reg [31:0] axis_data;

always @(posedge aclk) begin
    if (!aresetn) begin
        pps_sync  <= 2'b00;
        axis_data <= 32'b0;
    end else begin
        pps_sync <= {pps_sync[0], pps_in};
        if (m_axis_tready)
            axis_data <= {31'b0, pps_sync[1]};
    end
end

assign m_axis_tdata  = axis_data;
assign m_axis_tvalid = aresetn;

assign dbg_pps_sync_level = pps_sync[1];
assign dbg_axis_level     = axis_data[0];
assign dbg_axis_valid     = m_axis_tvalid;

endmodule
