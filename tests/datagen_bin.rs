//! datagen-bin contract tests: record round trip, byte-reproducibility, game-id sidecar integrity.
use chess_rust_engine::board::Position;
use chess_rust_engine::datagen_bin::{pack_record, run, unpack_record, REC_LEN};

fn placement(fen: &str) -> String {
    let mut it = fen.split_whitespace();
    format!("{} {}", it.next().unwrap(), it.next().unwrap())
}

#[test]
fn record_round_trip() {
    let fens = [
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R b KQkq - 0 1",
        "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
        "4k3/8/8/8/8/8/8/4K3 b - - 0 1",
    ];
    for f in fens {
        let pos = Position::from_fen(f).unwrap();
        for (score, wdl) in [(0, 1u8), (-312, 0), (2499, 2), (-32000, 1)] {
            let rec = pack_record(&pos, score, wdl);
            assert_eq!(rec.len(), REC_LEN);
            let (back, s, w) = unpack_record(&rec).unwrap();
            assert_eq!(placement(&back.to_fen()), placement(&pos.to_fen()), "{f}");
            assert_eq!(s, score);
            assert_eq!(w, wdl);
        }
    }
}

#[test]
fn startpos_record_matches_trainer_layout() {
    // Hand-computed from tools/nnue/label_self.py::pack: occ = ranks 1,2,7,8; nibbles ascending square.
    let rec = pack_record(&Position::startpos(), 17, 1);
    assert_eq!(u64::from_le_bytes(rec[0..8].try_into().unwrap()), 0xFFFF_0000_0000_FFFF);
    // a1 rook(3) b1 knight(1) -> 0x13 ; c1 bishop(2) d1 queen(4) -> 0x42
    assert_eq!(rec[8], 0x13);
    assert_eq!(rec[9], 0x42);
    assert_eq!(rec[24], 0); // white to move
    assert_eq!(i16::from_le_bytes([rec[25], rec[26]]), 17);
    assert_eq!(rec[27], 1);
}

#[test]
fn generation_is_reproducible_and_game_ids_are_consistent() {
    std::env::set_var("CRE_DATAGEN_SEED", "424242");
    let dir = std::env::temp_dir();
    let a = dir.join(format!("cre_dgb_a_{}.bin", std::process::id()));
    let b = dir.join(format!("cre_dgb_b_{}.bin", std::process::id()));
    run(400, 3, a.to_str().unwrap(), 1);
    run(400, 3, b.to_str().unwrap(), 1);
    let (ra, rb) = (std::fs::read(&a).unwrap(), std::fs::read(&b).unwrap());
    assert!(ra.len() >= 400 * REC_LEN && ra.len() % REC_LEN == 0);
    assert_eq!(ra, rb, "same seed + 1 thread + fixed depth must be byte-identical");
    let ga = std::fs::read(format!("{}.gid", a.display())).unwrap();
    assert_eq!(ga.len(), ra.len() / REC_LEN * 4);
    assert_eq!(ga, std::fs::read(format!("{}.gid", b.display())).unwrap());

    // game ids: contiguous blocks, never reused after the block ends
    let gids: Vec<u32> = ga.chunks_exact(4).map(|c| u32::from_le_bytes(c.try_into().unwrap())).collect();
    let mut seen = std::collections::HashSet::new();
    let mut prev = None;
    for g in &gids {
        if Some(*g) != prev {
            assert!(seen.insert(*g), "game id {g} appears in two separate blocks");
            prev = Some(*g);
        }
    }
    assert!(seen.len() >= 2, "need several games");

    // every record decodes, label is sane, and the side to move is not in check (sampling filter)
    for rec in ra.chunks_exact(REC_LEN) {
        let (pos, score, wdl) = unpack_record(rec.try_into().unwrap()).expect("decodes");
        assert!(wdl <= 2);
        assert!(score.abs() <= 2500);
        assert!(!pos.in_check());
    }
    let meta = std::fs::read_to_string(format!("{}.meta.json", a.display())).unwrap();
    assert!(meta.contains("\"tool\": \"datagen-bin\""));
    for p in [&a, &b] {
        let _ = std::fs::remove_file(p);
        let _ = std::fs::remove_file(format!("{}.gid", p.display()));
        let _ = std::fs::remove_file(format!("{}.meta.json", p.display()));
    }
}
