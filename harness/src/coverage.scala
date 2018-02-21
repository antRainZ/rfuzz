package pynq

import chisel3._
import chisel3.util._

class SaturatingCounter(width : Int) extends Module {
	val io = this.IO(new Bundle {
		val enable = Input(Bool())
		val value = Output(UInt(width.W))
	})
	val count = RegInit(0.U(width.W))
	io.value := count
	val max = ((1 << width) - 1).U
	count := Mux(!io.enable || count === max, count, count + 1.U)
}

class CoverageControl extends Bundle {
	val start_next = Input(Bool())
	val done_next = Output(Bool())
}


class Coverage(conf: DUTConfig) extends Module {
	val out_width = 64
	// all counter output values concatenated
	val coverage_width = conf.coverageCounters.map{ case (_,w) => w }.reduce(_+_)
	// output(0) is the test id!
	val output_count = div2Ceil(coverage_width, out_width)
	val test_id_width = 64

	val io = this.IO(new Bundle {
		val control = new CoverageControl
		// from DUT
		val coverage_signals = Input(UInt(conf.coverageCounters.size.W))
		// simple axi stream producer
		val axis_ready = Input(Bool())
		val axis_valid = Output(Bool())
		val axis_data  = Output(UInt(out_width.W))
	})
	val axis_fire = io.axis_ready && io.axis_valid

	val collecting = RegInit(false.B)
	when(io.control.start_next) { collecting := true.B }
	when(io.control.done_next) { collecting := false.B }

	val connect_coverage = !collecting
	//val cov_gen = new TrueCounterGenerator(1)
	val cov_gen = new TrueOrFalseLatchGenerator
	val coverage = cov_gen.cover(connect_coverage, io.coverage_signals)

	// axis
	io.axis_valid := collecting
	if(output_count > 1) {
		// create counter to emit data in multiple steps
		val output_ii = Module(new WrappingCounter(log2Ceil(output_count)))
		output_ii.io.max := (output_count - 1).U
		output_ii.io.enable := axis_fire
		io.control.done_next := axis_fire && output_ii.io.last
		// select current output value based on counter
		io.axis_data := MuxLookup(output_ii.io.value, 0.U, {
		var left = coverage_width - 1
		(0 until output_count).map{ case(ii) => ii.U -> {
			val right = left - out_width + 1
			val out = if(right >= 0) { coverage(left, right) } else {
				Cat(coverage(left, 0), 0.U((-right).W)) }
			left = left - out_width
			out }}
		})
	} else {
		// send all coverage data in a single transaction
		io.control.done_next := axis_fire
		io.axis_data := Cat(coverage, 0.U((out_width - coverage_width).W))
	}
}

// Coverage Generators:
// * given a set of cover points
// * generate a set of 8bit counter outputs with TOML description

class TrueCounterGenerator(counter_width: Int) {
	def cover(connect: Bool, cover_points: UInt) : UInt = {
		Cat(
			for(ii <- (0 until cover_points.getWidth).reverse) yield {
				val counter = Module(new SaturatingCounter(counter_width))
				counter.io.enable := Mux(connect, cover_points(ii), false.B)
				counter.io.value
			})
	}
	def bits(cover_points: Int) : Int = cover_points * (1 * 8)
}

class TrueOrFalseLatchGenerator {
	def cover(connect: Bool, cover_points: UInt) : UInt = {
		Cat({
			for(ii <- (0 until cover_points.getWidth).reverse) yield {
				val pos = Module(new SaturatingCounter(1))
				pos.io.enable := Mux(connect, cover_points(ii), false.B)
				val neg = Module(new SaturatingCounter(1))
				neg.io.enable := Mux(connect, ~cover_points(ii), false.B)
				Seq(0.U(7.W), pos.io.value, 0.U(7.W), neg.io.value)
			}}.flatten)
	}
	def bits(cover_points: Int) : Int = cover_points * (2 * 8)
}