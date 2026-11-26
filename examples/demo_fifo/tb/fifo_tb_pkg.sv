// ---------------------------------------------------------------------------
// Demo UVM testbench (user space).
//
// Shows the *kind* of environment the optimizer accelerates: randomised
// stimulus with plusarg knobs, functional covergroups, and a scoreboard.
// The optimizer never reads this file. It only sees, at run time:
//   - the hierarchy reported by the simulator,
//   - the coverage database,
//   - the transcript.
// ---------------------------------------------------------------------------
`timescale 1ns/1ps

package fifo_tb_pkg;

    import uvm_pkg::*;
    `include "uvm_macros.svh"

    // ------------------------------------------------------------- knobs
    // These plusargs are the *user's* control surface. AId-UVO-RT learns
    // which combinations are effective; it never inspects this code.
    class fifo_cfg extends uvm_object;
        `uvm_object_utils(fifo_cfg)
        int unsigned num_txns  = 200;
        int unsigned stim_mode = 0;   // 0=uniform 1=corner 2=back-to-back
        int unsigned rd_ratio  = 50;  // percent of cycles that read
        int unsigned err_rate  = 0;   // percent of illegal stimulus
        function new(string name = "fifo_cfg");
            super.new(name);
        endfunction
        function void from_plusargs();
            void'($value$plusargs("NUM_TXNS=%d",  num_txns));
            void'($value$plusargs("STIM_MODE=%d", stim_mode));
            void'($value$plusargs("RD_RATIO=%d",  rd_ratio));
            void'($value$plusargs("ERR_RATE=%d",  err_rate));
        endfunction
    endclass

    // ------------------------------------------------------- transaction
    typedef enum bit [1:0] {OP_IDLE, OP_WRITE, OP_READ, OP_BOTH} fifo_op_e;

    class fifo_item extends uvm_sequence_item;
        rand bit [7:0] wdata;
        rand bit       wr_en;
        rand bit       rd_en;
        fifo_op_e      op;
        bit            full, empty, overflow, underflow;
        bit [4:0]      level;
        `uvm_object_utils_begin(fifo_item)
            `uvm_field_int(wdata, UVM_ALL_ON)
            `uvm_field_int(wr_en, UVM_ALL_ON)
            `uvm_field_int(rd_en, UVM_ALL_ON)
        `uvm_object_utils_end
        function new(string name = "fifo_item");
            super.new(name);
        endfunction
        function void classify();
            if (wr_en && rd_en)      op = OP_BOTH;
            else if (wr_en)          op = OP_WRITE;
            else if (rd_en)          op = OP_READ;
            else                     op = OP_IDLE;
        endfunction
    endclass

    // --------------------------------------------------------- sequence
    class fifo_seq extends uvm_sequence #(fifo_item);
        `uvm_object_utils(fifo_seq)
        fifo_cfg cfg;
        function new(string name = "fifo_seq");
            super.new(name);
        endfunction
        task body();
            fifo_item it;
            repeat (cfg.num_txns) begin
                it = fifo_item::type_id::create("it");
                start_item(it);
                if (!it.randomize() with {
                        (cfg.stim_mode == 0) -> { wdata dist {[0:255] := 1}; }
                        (cfg.stim_mode == 1) -> { wdata inside {8'h00, 8'hFF, 8'h55, 8'hAA}; }
                        wr_en dist {1 := 60, 0 := 40};
                        rd_en dist {1 := cfg.rd_ratio, 0 := (100 - cfg.rd_ratio)};
                    }) `uvm_error("SEQ", "randomize failed")
                it.classify();
                finish_item(it);
            end
        endtask
    endclass

    // ---------------------------------------------------------- driver
    class fifo_driver extends uvm_driver #(fifo_item);
        `uvm_component_utils(fifo_driver)
        virtual fifo_if vif;
        function new(string name, uvm_component parent);
            super.new(name, parent);
        endfunction
        function void build_phase(uvm_phase phase);
            super.build_phase(phase);
            if (!uvm_config_db#(virtual fifo_if)::get(this, "", "vif", vif))
                `uvm_fatal("NOVIF", "fifo_if not set")
        endfunction
        task run_phase(uvm_phase phase);
            fifo_item it;
            vif.drv_cb.wr_en <= 1'b0;
            vif.drv_cb.rd_en <= 1'b0;
            forever begin
                seq_item_port.get_next_item(it);
                @(vif.drv_cb);
                vif.drv_cb.wr_en <= it.wr_en;
                vif.drv_cb.rd_en <= it.rd_en;
                vif.drv_cb.wdata <= it.wdata;
                seq_item_port.item_done();
            end
        endtask
    endclass

    // --------------------------------------------------------- monitor
    class fifo_monitor extends uvm_analyzer #(fifo_item);
        `uvm_component_utils(fifo_monitor)
        virtual fifo_if vif;
        uvm_analysis_port #(fifo_item) ap;
        function new(string name, uvm_component parent);
            super.new(name, parent);
            ap = new("ap", this);
        endfunction
        function void build_phase(uvm_phase phase);
            super.build_phase(phase);
            if (!uvm_config_db#(virtual fifo_if)::get(this, "", "vif", vif))
                `uvm_fatal("NOVIF", "fifo_if not set")
        endfunction
        task run_phase(uvm_phase phase);
            fifo_item it;
            forever begin
                @(vif.mon_cb);
                it = fifo_item::type_id::create("it");
                it.wr_en     = vif.mon_cb.wr_en;
                it.rd_en     = vif.mon_cb.rd_en;
                it.wdata     = vif.mon_cb.wdata;
                it.full      = vif.mon_cb.full;
                it.empty     = vif.mon_cb.empty;
                it.level     = vif.mon_cb.level;
                it.overflow  = vif.mon_cb.overflow;
                it.underflow = vif.mon_cb.underflow;
                it.classify();
                ap.write(it);
            end
        endtask
    endclass

    // ------------------------------------------------------- coverage
    class fifo_coverage extends uvm_subscriber #(fifo_item);
        `uvm_component_utils(fifo_coverage)

        covergroup cg_ops;
            option.per_instance = 1;
            cp_op: coverpoint item.op {
                bins idle  = {OP_IDLE};
                bins write = {OP_WRITE};
                bins read  = {OP_READ};
                bins both  = {OP_BOTH};
            }
            cp_full:  coverpoint item.full;
            cp_empty: coverpoint item.empty;
            cp_level: coverpoint item.level {
                bins lvl[] = {[0:16]};
            }
            x_op_full:  cross cp_op, cp_full;
            x_op_empty: cross cp_op, cp_empty;
        endgroup

        covergroup cg_flags;
            option.per_instance = 1;
            cp_overflow:  coverpoint item.overflow;
            cp_underflow: coverpoint item.underflow;
            x_flags: cross cp_overflow, cp_underflow;
        endgroup

        function new(string name, uvm_component parent);
            super.new(name, parent);
            cg_ops = new();
            cg_flags = new();
        endfunction

        function void write(fifo_item t);
            cg_ops.sample();
            cg_flags.sample();
        endfunction
    endclass

    // ------------------------------------------------------ scoreboard
    class fifo_scoreboard extends uvm_subscriber #(fifo_item);
        `uvm_component_utils(fifo_scoreboard)
        bit [7:0] model[$];
        function new(string name, uvm_component parent);
            super.new(name, parent);
        endfunction
        function void write(fifo_item t);
            if (t.wr_en && !t.full) model.push_back(t.wdata);
            if (t.rd_en && !t.empty && model.size() > 0) begin
                bit [7:0] exp = model.pop_front();
                if (t.wdata !== 8'bx && exp === 8'bx) ; // no-op
            end
            if (t.overflow)  `uvm_info("SB", "overflow seen", UVM_HIGH)
            if (t.underflow) `uvm_info("SB", "underflow seen", UVM_HIGH)
        endfunction
    endclass

    // ------------------------------------------------------------- env
    class fifo_env extends uvm_env;
        `uvm_component_utils(fifo_env)
        fifo_driver   drv;
        fifo_monitor  mon;
        fifo_coverage cov;
        fifo_scoreboard sb;
        function new(string name, uvm_component parent);
            super.new(name, parent);
        endfunction
        function void build_phase(uvm_phase phase);
            super.build_phase(phase);
            drv = fifo_driver::type_id::create("drv", this);
            mon = fifo_monitor::type_id::create("mon", this);
            cov = fifo_coverage::type_id::create("cov", this);
            sb  = fifo_scoreboard::type_id::create("sb", this);
        endfunction
        function void connect_phase(uvm_phase phase);
            mon.ap.connect(cov.analysis_export);
            mon.ap.connect(sb.analysis_export);
        endfunction
    endclass

    // ------------------------------------------------------------ test
    class fifo_base_test extends uvm_test;
        `uvm_component_utils(fifo_base_test)
        fifo_env env;
        fifo_cfg cfg;
        function new(string name = "fifo_base_test", uvm_component parent = null);
            super.new(name, parent);
        endfunction
        function void build_phase(uvm_phase phase);
            super.build_phase(phase);
            cfg = fifo_cfg::type_id::create("cfg");
            cfg.from_plusargs();
            uvm_config_db#(fifo_cfg)::set(this, "*", "cfg", cfg);
            env = fifo_env::type_id::create("env", this);
        endfunction
        task run_phase(uvm_phase phase);
            fifo_seq seq;
            phase.raise_objection(this);
            seq = fifo_seq::type_id::create("seq");
            seq.cfg = cfg;
            seq.start(env.drv.seq_item_port);
            #200;
            phase.drop_objection(this);
        endtask
    endclass

endpackage
