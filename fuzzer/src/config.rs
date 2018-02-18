// Copyright 2018, Kevin Laeufer <laeufer@cs.berkeley.edu>

// this module contains code to load the fuzz configuration TOML
// which is generated by the FIRRTL instrumentation pass
// (and potentially extended/modified by hand)

use toml;
use config::toml::value::Datetime;
use colored::*;
use prettytable::Table;
use prettytable::row::Row;
use prettytable::cell::Cell;

use std::fs::File;
use std::io::prelude::*;

use run::TestSize;

pub struct Config {
	size: TestSize,
	data: ConfigData,
}


impl Config {
	pub fn from_file(word_size: usize, filename: &str) -> Self {
		let mut file = File::open(filename).expect("failed to open config");
		let mut contents = String::new();
		file.read_to_string(&mut contents).expect("failed to read config");
		let data: ConfigData = toml::from_str(&contents).unwrap();
		let size = Config::determine_test_size(word_size, &data);
		let config = Config { size, data };
		config.validate();
		config
	}

	fn determine_test_size(word_size: usize, data: &ConfigData) -> TestSize {
		let div_2_ceil = |a, b| (a + (b - 1)) / b;
		let to_bytes = |b| div_2_ceil(div_2_ceil(b, 8), word_size) * word_size;

		let input_bits : usize = data.input_bits() as usize;
		let coverage_bits : usize = data.coverage.iter().map(|ref c| c.counterbits as usize).sum();

		TestSize { input: to_bytes(input_bits), coverage: to_bytes(coverage_bits) }
	}

	fn validate(&self) {
		// we currently only support 1-bit counters!
		assert!(self.data.coverage.iter().all(|ref c| c.counterbits == 1));

		// we expect each coverage point to be followed by its inverted version
		let mut expect_inverted = false;
		let mut last_name = String::new();
		for cov in self.data.coverage.iter() {
			if expect_inverted {
				assert_eq!(cov.name, last_name);
				assert!(cov.inverted);
				expect_inverted = false;
			} else {
				assert!(!cov.inverted);
				last_name = cov.name.clone();
				expect_inverted = true;
			}
		}

		// make sure the size is large enough to hold coverage and inputs
		let input_bits : usize = self.data.input_bits() as usize;
		assert!(input_bits <= self.size.input * 8);
		let coverage_bits : usize = self.data.coverage.iter().map(|ref c| c.counterbits as usize).sum();
		assert!(coverage_bits <= self.size.coverage * 8);
	}

	pub fn get_test_size(&self) -> TestSize { self.size }

	pub fn get_inputs(&self) -> Vec<(String,u32)> {
		let mut ii = Vec::with_capacity(self.data.input.len());
		for field in &self.data.input {
			ii.push((field.name.clone(), field.width));
		}
		ii
	}

	pub fn coverage_signal_count(&self) -> usize {
		// WARN: this assumes that we have an inverted version of every coverage point!
		assert!(self.data.coverage.len() % 2 == 0);
		self.data.coverage.len() / 2
	}

	pub fn print_header(&self) {
		println!("Fuzzing {}", self.data.general.module.bold());
		println!("Instrumented on:   {}", self.data.general.timestamp);
		println!("Coverage Signals:  {}", self.coverage_signal_count());
		println!("Input Fields:      {}", self.data.input.len());
		let width = self.data.input_bits();
		println!("Total Input Width: {}", width);
		println!("Allocated Bytes per Input:    {}", self.size.input);
		println!("Allocated Bytes for Coverage: {}", self.size.coverage);
	}

	pub fn print_inputs(&self, inputs: &[u8]) {
		let cycle_count = inputs.len() / self.size.input;
		assert_eq!(cycle_count * self.size.input, inputs.len());

		// print the inputs as a table! (one row per cycle)
		let mut table = Table::new();

		let mut head_row = vec![Cell::new("C")];
		for field in &self.data.input { head_row.push(Cell::new(&field.name)); }
		table.add_row(Row::new(head_row));

		// bits are labled left to right (the MSB is bit0!)
		let read_bit = |cycle: usize, bit: usize| -> char {
			let byte_ii = cycle * self.size.input + bit / 8;
			let byte = inputs[byte_ii];
			let bit_ii = 7 - (bit % 8);
			let is_set = (byte & (1 << bit_ii)) != 0;
			if is_set { '1' } else { '0' }
		};

		for cycle in 0..cycle_count {
			let mut row = vec![Cell::new(&cycle.to_string())];
			let mut bit = 0;
			for field in &self.data.input {
				let mut bit_str = String::with_capacity(field.width as usize);
				for _ in 0..field.width {
					bit_str.push(read_bit(cycle, bit));
					bit += 1;
				}
				row.push(Cell::new(&bit_str));
			}
			table.add_row(Row::new(row));
		}

		table.printstd();
		//println!("{:?}", inputs)
	}

	// the coverage map is inverted, i.e., a 0 means covered, a 1 means not covered
	pub fn print_coverage(&self, coverage: &[u8], inverted: bool) {
		assert_eq!(coverage.len(), self.size.coverage);

		// print the coverage as a table!
		let mut table = Table::new();
		table.add_row(row!["C?", "T?", "F?", "name", "expression", "source location"]);

		// we expect each coverage point to be followed by its inverted version
		let mut coverage_count = 0u64;
		for cov in self.data.coverage.iter() {
			if cov.inverted { continue; }
			// check if true + false are covered (one of them is trivially true)
			let byte_ii = (cov.index / 8) as usize;
			let byte = if inverted { !coverage[byte_ii] } else { coverage[byte_ii] };
			// the index of the NOT inverted signal
			let bit_ii = 7 - (cov.index as usize - 8 * byte_ii);
			let bit_ii_inv = bit_ii - 1;
			let covered_true  = ((byte >> bit_ii) & 1) == 1;
			let covered_false = ((byte >> bit_ii_inv) & 1) == 1;
			let covered = covered_true && covered_false;
			// create table row
			let covd       = if covered { "X" } else { "" };
			let covd_true  = if covered_true { "X" } else { "" };
			let covd_false = if covered_false { "X" } else { "" };
			let src = format!("{}:{}", cov.filename, cov.line);
			table.add_row(row![covd, covd_true, covd_false, cov.name, cov.human, src]);
			// increment coverage count
			coverage_count += if covered { 1 } else { 0 }
		}

		table.printstd();
		println!("Covered a total of {}/{} signals.", coverage_count, self.coverage_signal_count());
	}
}

#[derive(Debug, Deserialize)]
struct General {
	filename: String,
	instrumented: String,
	module: String,
	timestamp: Datetime
}
#[derive(Debug, Deserialize)]
struct Coverage {
	name: String,
	inverted: bool,
	index: i32,
	counterbits: i32,
	filename: String,
	line: i32,
	column: i32,
	human: String,
}
#[derive(Debug, Deserialize)]
struct Input {
	name: String,
	width: u32,
}


#[derive(Debug, Deserialize)]
pub struct ConfigData {
	general: General,
	coverage: Vec<Coverage>,
	input: Vec<Input>,
}

impl ConfigData {
	fn input_bits(&self) -> u32 {
		self.input.iter().map(|ii| ii.width).sum::<u32>()
	}
}