# EXP-Z9-2: continue training S45 on fresh shards (fine-tune, 285 min)

Agent Z9. DRAFT / pre-registered before any result.

## Hypothesis
Training is time-bound (CPU PyTorch, 150 min, <= 16M positions, a few epochs). Every net so far was trained from scratch on shards the previous nets never saw, so no data has been *accumulated*.
Resuming S45 on 3 unseen shards (6,7,8, <= 6M each, min depth 20, lam 1.0) with lr 1e-3 for 285 min should lower validation loss on the (position-hash disjoint) validation split and, if loss tracks play, gain Elo.

## Change
\`lichess-bulk.yml\` (branch \`agentZ9/resume-s45\`): two new optional inputs \`resume_net\`, \`train_lr\`. Defaults reproduce the old behaviour exactly. Run 43425821163 with resume_net=nets/default.nnue (S45, sha256 7739137c...), train_lr=0.001, train_minutes=285, shards 6,7,8, max_out 6000000, gate 40 games.

## Measured by
1. \`== start val_loss\` (S45 on the new data's validation split) vs final best val_loss in the train log. The trainer rolls back automatically if the resumed net cannot beat its start loss.
2. If it improves: promote-lichess-net.yml publishes \`nnue/lichess-bulk-43425821163\`. Build a candidate = stack + that net, then run (a) fixed-node A/B vs S45 and vs 964d07 (600+ games, tools in EXP-Z9-1), (b) \`sprt.yml\` 10+0.1 elo0=0/elo1=10 against the stack with the 964d07 net, (c) SF19 ladder 3000 with >= 3 replicas of 100 games.

## Decision rule
KEEP only if (1) val_loss improves AND (2a) fixed-node score vs S45 is > 50 % with CI lower bound > 0 over >= 1200 games AND (2b) not negative. Lower val_loss alone is NOT a promotion reason (EXP-Z9-1 shows 2 % val_loss difference was not visible in play).

## Possible downsides to check before shipping
- Positions are human Lichess games; check the engine's play in endgames (fifty_move_mate and perft tests unaffected by net).
- Net scale drift vs search margins: compare average |eval| on bench positions before/after.
- Rollback: \`UseNNUE=false\` and \`git revert\` of the net commit.
