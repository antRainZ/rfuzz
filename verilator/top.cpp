
#include <iostream>
#include <sstream>
#include <fstream>
#include <vector>
#include <cstdint>
#include <cassert>
#include <algorithm>

#include <VVerilatorHarness.h>
#include <verilated.h>
#if VM_TRACE
# include <verilated_vcd_c.h>	// Trace file format header
#endif
#define TOP_TYPE VVerilatorHarness

#ifdef USE_AFL
#include <afl.hpp>
#else
#include <fpga_queue.hpp>
#endif

// TODO: autogenerate
static constexpr size_t CoverageSize = 8;
static constexpr size_t InputSize    = 40;

static inline void apply_input(TOP_TYPE* top, const uint8_t* input) {
	top->io_input_bytes_0  = input[ 0];
	top->io_input_bytes_1  = input[ 1];
	top->io_input_bytes_2  = input[ 2];
	top->io_input_bytes_3  = input[ 3];
	top->io_input_bytes_4  = input[ 4];
	top->io_input_bytes_5  = input[ 5];
	top->io_input_bytes_6  = input[ 6];
	top->io_input_bytes_7  = input[ 7];
	top->io_input_bytes_8  = input[ 8];
	top->io_input_bytes_9  = input[ 9];
	top->io_input_bytes_10 = input[10];
	top->io_input_bytes_11 = input[11];
	top->io_input_bytes_12 = input[12];
	top->io_input_bytes_13 = input[13];
	top->io_input_bytes_14 = input[14];
	top->io_input_bytes_15 = input[15];
	top->io_input_bytes_16 = input[16];
	top->io_input_bytes_17 = input[17];
	top->io_input_bytes_18 = input[18];
	top->io_input_bytes_19 = input[19];
	top->io_input_bytes_20 = input[20];
	top->io_input_bytes_21 = input[21];
	top->io_input_bytes_22 = input[22];
	top->io_input_bytes_23 = input[23];
	top->io_input_bytes_24 = input[24];
	top->io_input_bytes_25 = input[25];
	top->io_input_bytes_26 = input[26];
	top->io_input_bytes_27 = input[27];
	top->io_input_bytes_28 = input[28];
	top->io_input_bytes_29 = input[29];
	top->io_input_bytes_30 = input[30];
	top->io_input_bytes_31 = input[31];
	top->io_input_bytes_32 = input[32];
	top->io_input_bytes_33 = input[33];
	top->io_input_bytes_34 = input[34];
	top->io_input_bytes_35 = input[35];
	top->io_input_bytes_36 = input[36];
	top->io_input_bytes_37 = input[37];
	top->io_input_bytes_38 = input[38];
	top->io_input_bytes_39 = input[39];
}
static inline void read_coverage(TOP_TYPE* top, uint8_t* coverage) {
	coverage[ 0] = top->io_coverage_bytes_0;
	coverage[ 1] = top->io_coverage_bytes_1;
	coverage[ 2] = top->io_coverage_bytes_2;
	coverage[ 3] = top->io_coverage_bytes_3;
	coverage[ 4] = top->io_coverage_bytes_4;
	coverage[ 5] = top->io_coverage_bytes_5;
	coverage[ 6] = top->io_coverage_bytes_6;
	coverage[ 7] = top->io_coverage_bytes_7;
}


// Override Verilator definition so first $finish ends simulation
// Note: VL_USER_FINISH needs to be defined when compiling Verilator code
void vl_finish(const char* filename, int linenum, const char* hier) {
	Verilated::flushCall();
	exit(0);
}

using namespace std;

struct Simulation {
	TOP_TYPE* top = nullptr;
	vluint64_t main_time = 0;
	VerilatedVcdC* tfp = nullptr;
	void step() {
		top->clock = 0;
		top->eval();
		#if VM_TRACE
		if (tfp) { tfp->dump(main_time); }
		#endif
		main_time++;
		top->clock = 1;
		top->eval();
		#if VM_TRACE
		if (tfp) { tfp->dump(main_time); }
		#endif
		main_time++;
	}
	uint64_t cycles() { return main_time / 2; }
};

static inline void run_test(Simulation& sim, Fuzzer& fuzzer) {
	// reset circuit for one cycles
	sim.top->reset = 1;
	sim.step();
	sim.top->reset = 0;
	// run for as many cycles as we get data
	uint8_t input[InputSize];
	while(fuzzer.pop(input, InputSize)) {
		apply_input(sim.top, input);
		sim.step();
	}
	uint8_t coverage[CoverageSize];
	read_coverage(sim.top, coverage);
	fuzzer.push(coverage, CoverageSize);
}

Simulation global_sim;
// Called by $time in Verilog converts to double, to match what SystemC does
double sc_time_stamp () { return global_sim.main_time; }
int main(int argc, char** argv) {
	ActiveFuzzer fuzzer;
	fuzzer.init(CoverageSize);

	Verilated::commandArgs(argc, argv);
	Simulation& sim = global_sim;
	sim.top = new TOP_TYPE;

	// If verilator was invoked with --trace
#if VM_TRACE
	Verilated::traceEverOn(true);
	sim.tfp = new VerilatedVcdC;
	sim.top->trace(sim.tfp, 99);
	sim.tfp->open ("dump.vcd");
#endif

	while(!fuzzer.done()) {
		run_test(sim, fuzzer);
	}

	cout << "Simulation completed after " << sim.cycles() << " cycles" << endl;

	// finish last cycle
	sim.top->eval();
#if VM_TRACE
	if (sim.tfp) { sim.tfp->dump(sim.main_time); }
	if (sim.tfp) { sim.tfp->close(); }
#endif
}

