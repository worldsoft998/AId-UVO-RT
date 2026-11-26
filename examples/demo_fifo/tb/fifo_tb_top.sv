// ---------------------------------------------------------------------------
// Demo testbench top (user space).
//
//   vsim -c -do "do scripts/questa/compile.do"
//   vsim -c -sv_seed 1 +NUM_TXNS=500 +STIM_MODE=1 work.tb_top_opt
// ---------------------------------------------------------------------------
`timescale 1ns/1ps

module tb_top;

    import uvm_pkg::*;
    import fifo_tb_pkg::*;

    logic clk = 1'b0;
    logic rst_n = 1'b0;

    always #5 clk = ~clk;   // 100 MHz

    fifo_if #(.WIDTH(8), .DEPTH(16)) vif (.clk(clk));

    fifo #(.WIDTH(8), .DEPTH(16)) u_dut (
        .clk       (clk),
        .rst_n     (rst_n),
        .wr_en     (vif.wr_en),
        .wdata     (vif.wdata),
        .rd_en     (vif.rd_en),
        .rdata     (vif.rdata),
        .full      (vif.full),
        .empty     (vif.empty),
        .level     (vif.level),
        .overflow  (vif.overflow),
        .underflow (vif.underflow)
    );

    assign vif.rst_n = rst_n;

    initial begin
        vif.wr_en = 1'b0;
        vif.rd_en = 1'b0;
        vif.wdata = '0;
        repeat (4) @(posedge clk);
        rst_n = 1'b1;
    end

    initial begin
        uvm_config_db#(virtual fifo_if)::set(null, "*", "vif", vif);
        run_test();
    end

    initial begin
        #2_000_000;
        `uvm_fatal("TIMEOUT", "simulation watchdog expired")
    end

endmodule
