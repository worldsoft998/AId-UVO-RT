// ---------------------------------------------------------------------------
// Demo testbench interface (user space).
// ---------------------------------------------------------------------------
`timescale 1ns/1ps

interface fifo_if #(
    parameter int WIDTH = 8,
    parameter int DEPTH = 16,
    parameter int LW    = (DEPTH <= 2) ? 2 : $clog2(DEPTH) + 1
) (input logic clk);

    logic             rst_n;
    logic             wr_en;
    logic [WIDTH-1:0] wdata;
    logic             rd_en;
    logic [WIDTH-1:0] rdata;
    logic             full;
    logic             empty;
    logic [LW-1:0]    level;
    logic             overflow;
    logic             underflow;

    clocking drv_cb @(posedge clk);
        default input #1step output #0;
        output wr_en, wdata, rd_en;
        input  full, empty, rdata;
    endclocking

    clocking mon_cb @(posedge clk);
        default input #1step;
        input wr_en, wdata, rd_en, rdata, full, empty, level, overflow, underflow;
    endclocking

    modport dut (
        input  clk, rst_n, wr_en, wdata, rd_en,
        output rdata, full, empty, level, overflow, underflow
    );

endinterface
