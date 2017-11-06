package pynq

import chisel3._
import chisel3.util._
import chisel3.experimental.withReset

import scala.collection.immutable.ListMap

// WARN: all circuts designed with 64bit AXIS interface in mind

object div2Ceil {
	def apply(dividend: Int, divisor: Int): Int = (dividend + divisor - 1) / divisor
}

class Inputs(input_width: Int) extends Module {
	val max_cycles = 64
	val test_id_width = 64
	val in_width = 64
	val data_per_cycle = div2Ceil(input_width, in_width)

	val io = this.IO(new Bundle {
		// to DUT
		val input_signals = Output(UInt(input_width.W))
		// connect to coverage module
		val test_id = Output(UInt(test_id_width.W))
		val test_id_valid = Output(Bool())
		// internal control signals
		val test_cycles = Input(UInt(16.W))
		val last_load  = Output(Bool())
		val last_cycle = Output(Bool())
		// axis consumer
		val valid = Input(Bool())
		val data = Input(UInt(in_width.W))
		val ready = Output(Bool())
	})
	val sLoadTestId :: sLoadTest :: sRunTest :: Nil = Enum(3)
	val state = RegInit(sLoadTestId)
	val data_in_cycle_count = RegInit(0.U(log2Ceil(data_per_cycle).W))
	val load_cycle_count = RegInit(0.U(log2Ceil(max_cycles).W))
	val run_cycle_count = RegInit(0.U(log2Ceil(max_cycles).W))

	val q = Module(new Queue(UInt(input_width.W), max_cycles))
	assert(q.io.enq.ready || !q.io.enq.valid, "Never push when queue is full")
	assert(q.io.deq.valid || !q.io.deq.ready, "Never pop when queue is empty")
	io.input_signals := q.io.deq.bits

	// receive test data
	io.ready := (state === sLoadTestId || state === sLoadTest)
	q.io.enq.bits := Cat((0 until data_per_cycle - 1).map{ case(cycle) => {
		val reg = RegInit(0.U(in_width.W))
		when(data_in_cycle_count === cycle.U) { reg := io.data }
		reg
	}} ++ Seq(io.data))
	q.io.enq.valid := (state === sLoadTest) && io.valid

	// test id for coverage module
	val test_id = RegInit(0.U(test_id_width.W))
	when(state === sLoadTestId && io.valid) { test_id := io.data }
	io.test_id := test_id
	io.test_id_valid := true.B

	// control
	io.last_load := false.B
	io.last_cycle := false.B
	val last_data_in_cycle = data_in_cycle_count === (data_per_cycle - 1).U
	data_in_cycle_count := Mux(state =/= sLoadTest, 0.U,
		Mux(!io.valid, data_in_cycle_count,
			Mux(last_data_in_cycle, 0.U, data_in_cycle_count + 1.U)))
	load_cycle_count := Mux(state =/= sLoadTest, 0.U,
		Mux(io.valid && data_in_cycle_count === 0.U, load_cycle_count + 1.U, load_cycle_count))
	val last_data_in_test = load_cycle_count === io.test_cycles - 1.U && last_data_in_cycle
	run_cycle_count := Mux(state =/= sRunTest, 0.U, run_cycle_count + 1.U)
	val last_run_cycle = run_cycle_count === io.test_cycles - 1.U
	switch(state) {
	is(sLoadTestId) {
		when(io.valid) { state := sLoadTest }
	}
	is(sLoadTest) {
		when(io.valid && last_data_in_test) {
			io.last_load := true.B
			state := sRunTest
		}
	}
	is(sRunTest) {
		when(last_run_cycle) {
			io.last_cycle := true.B
			state := sLoadTest
		}
	}
	}


}


class Harness() extends Module {
	val axis_width = 64
	val axis_bit_count = div2Ceil(axis_width, 8)

	val io = this.IO(new Bundle {
		// TODO: split up into separate producer / consumer boundles
		val s_axis_tvalid = Input(Bool())
		val s_axis_tready = Output(Bool())
		val s_axis_tdata = Input(UInt(axis_width.W))
		val s_axis_tkeep = Input(UInt(axis_bit_count.W))
		val s_axis_tlast = Input(Bool())
		val m_axis_tvalid = Output(Bool())
		val m_axis_tready = Input(Bool())
		val m_axis_tdata = Output(UInt(axis_width.W))
		val m_axis_tkeep = Output(UInt(axis_bit_count.W))
		val m_axis_tlast = Output(Bool())
	})

	// control states
	val sIdle :: sLoadTest :: sRunTest :: sCollectCoverage :: Nil = Enum(4)
	val state = RegInit(sIdle)
	val test_cycles = RegInit(0.U(16.W))

	// modules
	val reset_dut_and_cov = Wire(Bool())
	reset_dut_and_cov := false.B
	val cov_conf = new CoverageConfig
	val dut_conf = new DUTConfig(cov_conf)
	val (dut, cov) = withReset(this.reset.toBool || reset_dut_and_cov) {
		(Module (new DUT(dut_conf) ), Module (new Coverage(cov_conf))) }
	val inp = Module (new Inputs(dut_conf.input_bits))

	// connect inputs
	inp.io.data  := io.s_axis_tdata
	inp.io.valid := Mux(state === sLoadTest, io.s_axis_tvalid, false.B)
	inp.io.test_cycles := test_cycles
	io.s_axis_tready := MuxLookup(state, false.B, Array(
		sIdle -> true.B, sLoadTest -> inp.io.ready))

	// connect coverage
	cov.io.coverage_signals := dut.io.coverage
	cov.io.test_id := inp.io.test_id
	cov.io.test_id_valid := inp.io.test_id_valid
	cov.io.do_collect := (state === sCollectCoverage)
	io.m_axis_tvalid := cov.io.valid
	io.m_axis_tdata  := cov.io.data
	io.m_axis_tkeep  := ((1 << axis_bit_count) - 1).U
	io.m_axis_tlast  := cov.io.last
	cov.io.ready     := io.m_axis_tready

	// control
	val test_count = RegInit(0.U(16.W))
	switch (state) {
	is (sIdle) {
		// wait for start of test buffer
		val magic_header = io.s_axis_tdata(63,32)
		val new_test_count = io.s_axis_tdata(31,16)
		val new_test_cycles = io.s_axis_tdata(15,0)
		val valid_header = (magic_header === "h19931993".U) && (new_test_count > 0.U)
		when (io.s_axis_tvalid && valid_header) {
			test_count := new_test_count
			test_cycles := new_test_cycles
			state := sLoadTest
		}
	}
	is(sLoadTest) {
		reset_dut_and_cov := true.B
		when(inp.io.last_load) { state := sRunTest }
	}
	is(sRunTest) {
		when(inp.io.last_cycle) { state := sCollectCoverage }
	}
	is(sCollectCoverage) {
		when(cov.io.last_send) {
			test_count := test_count - 1.U
			val tests_left = (test_count > 1.U)
			state := Mux(tests_left, sLoadTest, sIdle)
		}
	}
	}
}

object HarnessGenerator extends App {
	chisel3.Driver.execute(args, () => new Harness())
}
