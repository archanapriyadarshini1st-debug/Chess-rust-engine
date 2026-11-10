use chess_rust_engine::search::bench;
use chess_rust_engine::uci;

fn main() {
    // Fancy magics are found once; do it before the first timed search/bench.
    let _ = chess_rust_engine::attacks::tables();
    let mut args = std::env::args().skip(1);
    match args.next().as_deref() {
        Some("bench") => {
            let depth: i32 = args.next().and_then(|s| s.parse().ok()).unwrap_or(8);
            let threads: usize = args.next().and_then(|s| s.parse().ok()).unwrap_or(1);
            let hash: usize = args.next().and_then(|s| s.parse().ok()).unwrap_or(16);
            let _ = bench(depth, threads, hash);
        }
        Some("datagen") => {
            let n: usize = args.next().and_then(|s| s.parse().ok()).unwrap_or(20_000);
            let depth: i32 = args.next().and_then(|s| s.parse().ok()).unwrap_or(6);
            let out = args
                .next()
                .unwrap_or_else(|| "datasets/selfplay.jsonl".into());
            chess_rust_engine::datagen::run(n, depth, &out);
        }
        Some("hce-dump") => {
            chess_rust_engine::datagen::dump_hce();
        }
        Some("perft") => {
            let depth: u32 = args.next().and_then(|s| s.parse().ok()).unwrap_or(5);
            let fen = args.next();
            let pos = if let Some(f) = fen {
                chess_rust_engine::board::Position::from_fen(&f)
                    .unwrap_or_else(|| chess_rust_engine::board::Position::startpos())
            } else {
                chess_rust_engine::board::Position::startpos()
            };
            let start = std::time::Instant::now();
            let n = chess_rust_engine::perft::perft(&pos, depth);
            let ms = start.elapsed().as_millis().max(1);
            println!("perft {} = {}  ({:.2} Mnps)", depth, n, n as f64 / ms as f64 / 1000.0);
        }
        _ => uci::run(),
    }
}
