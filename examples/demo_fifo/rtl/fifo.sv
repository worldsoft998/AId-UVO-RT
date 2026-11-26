// ---------------------------------------------------------------------------
// Demo DUT: parameterised synchronous FIFO.
//
// This file is USER SPACE. The optimizer never reads, parses or modifies it --
// it only talks to the simulator that elaborates it.
// ---------------------------------------------------------------------------
`timescale 1ns/1ps

module fifo #(
    parameter int WIDTH = 8,
    parameter int DEPTH = 16,
    parameter int AW    = (DEPTH <= 2) ? 1 : $clog2(DEPTH)
) (
    input  logic             clk,
    input  logic             rst_n,
    input  logic             wr_en,
    input  logic [WIDTH-1:0] wdata,
    input  logic             rd_en,
    output logic [WIDTH-1:0] rdata,
    output logic             full,
    output logic             empty,
    output logic [AW:0]      level,
    output logic             overflow,
    output logic             underflow
);

    logic [WIDTH-1:0] mem[0:DEPTH-1];
    logic [AW-1:0]    wptr, rptr;
    logic [AW:0]      count;

    assign full    = (count == DEPTH[AW:0]);
    assign empty   = (count == '0);
    assign level   = count;
    assign rdata   = empty ? '0 : mem[rptr];

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wptr      <= '0;
            rptr      <= '0;
            count     <= '0;
            overflow  <= 1'b0;
            underflow <= 1'b0;
        end else begin
            overflow  <= 1'b0;
            underflow <= 1'b0;

            if (wr_en && !full) begin
                mem[wptr] <= wdata;
                wptr      <= wptr + 1'b1;
            end else if (wr_en && full) begin
                overflow  <= 1'b1;
            end

            if (rd_en && !empty) begin
                rptr <= rptr + 1'b1;
            end else if (rd_en && empty) begin
                underflow <= 1'b1;
            end

            case ({wr_en && !full, rd_en && !empty})
                2'b10:   count <= count + 1'b1;
                2'b01:   count <= count - 1'b1;
                default: count <= count;
            endcase
        end
    end

`ifdef AIDUVO_SIM
    // Optional assertion set, enabled only by a compile-time switch in the
    // *user's* build. The optimizer never adds this.
    property p_no_overflow_without_full;
        @(posedge clk) disable iff (!rst_n) overflow |-> full;
    endproperty
    assert property (p_no_overflow_without_full);
`endif

endmodule
