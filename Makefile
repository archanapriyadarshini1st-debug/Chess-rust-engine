# OpenBench / native build. `make EXE=chess-rust-engine-<hash>` is what
# OpenBench invokes; see https://github.com/AndyGrant/OpenBench/wiki
ifndef EXE
	EXE := chess-rust-engine
endif

RUSTFLAGS_NATIVE := -C target-cpu=native

.PHONY: all native openbench release debug test perft clean

all: native

native:
	RUSTFLAGS="$(RUSTFLAGS_NATIVE)" cargo rustc --release --bin chess-rust-engine -- --emit link=$(EXE)

openbench:
	cargo rustc --release --bin chess-rust-engine -- -C target-cpu=native --emit link=$(EXE)

release:
	cargo build --release

debug:
	cargo build

test:
	cargo test --release

perft:
	cargo run --release -- perft 6

bench:
	cargo run --release -- bench 10

clean:
	cargo clean
	rm -f $(EXE) $(EXE).exe
