#!/bin/bash
# Wait for a rehearsal kernel, check its log, then submit it right after the next UTC reset.
# usage: scripts/rehearse_then_submit.sh <slug> <version> <message>
# Submits only if: kernel COMPLETE, log has every REQUIRED marker, and some game used tokens > 0.
set -u
SLUG=$1; VER=$2; MSG=$3
COMP=arc-prize-2026-arc-agi-3
OUT=${TMPDIR:-/tmp}/rehearse_$(echo $SLUG | tr / _)_v$VER
REQUIRED=("m2-robust: keepalive patch applied" "taaf.kaggle: TRUE_SUBMISSION=False")
[ -n "${EXTRA_MARKER:-}" ] && REQUIRED+=("$EXTRA_MARKER")
k() { "${KAGGLE_CLI:-kaggle}" "$@" 2>&1 | grep -v "outdated"; }

while true; do
  s=$(k kernels status $SLUG)
  echo "$s" | grep -q Authentication && { echo "AUTH FAIL"; exit 2; }
  echo "$s" | grep -qE "RUNNING|QUEUED" || break
  sleep 180
done
echo "$(date -u) status: $s"
echo "$s" | grep -q COMPLETE || { echo "NOT COMPLETE -> no submit"; exit 3; }

rm -rf $OUT; mkdir -p $OUT
k kernels output $SLUG -p $OUT --file-pattern "($(basename $SLUG)\.log|submission\.parquet|serve\.log)$" >/dev/null
python3 - "$OUT/$(basename $SLUG).log" > $OUT/log.txt <<'EOF'
import json,sys; print("".join(x.get("data","") for x in json.load(open(sys.argv[1]))))
EOF
ok=1
for m in "${REQUIRED[@]}"; do
  grep -qF "$m" $OUT/log.txt && echo "marker ok: $m" || { echo "MISSING: $m"; ok=0; }
done
# per-game summary lines look like "  ls20-9607627b: score=0.00, levels=0.0/7, actions=7, tokens=0"
# (the [finished] lines carry note="tokens=98" which must not count)
grep -E "^\s+[a-z0-9]{4}-[0-9a-f]+: score=.*, tokens=[1-9][0-9]*\s*$" $OUT/log.txt >/dev/null \
  && echo "tokens>0 ok" || { echo "MISSING: a game with tokens>0"; ok=0; }
[ -f $OUT/submission.parquet ] || { echo "MISSING submission.parquet"; ok=0; }
grep -E "^\s+[a-z0-9]{4}-[0-9a-f]+: score=" $OUT/log.txt | tail -4
[ $ok = 1 ] || { echo "CHECK FAILED -> no submit (log: $OUT/log.txt)"; exit 4; }

# wait for a fresh UTC day if today's slot is used
while true; do
  today=$(date -u +%Y-%m-%d)
  used=$(k competitions submissions $COMP --page-size 20 --csv | python3 -c "
import csv,sys; r=list(csv.DictReader(l for l in sys.stdin if ',' in l))
print(sum(1 for x in r if x.get('date','').startswith('$today')))")
  dup=$(k competitions submissions $COMP --page-size 20 --csv | grep -cF "$MSG")
  [ "$dup" -gt 0 ] && { echo "already submitted: $MSG"; exit 0; }
  # the competition allows only ONE pending submission per team (400 FAILED_PRECONDITION otherwise)
  pending=$(k competitions submissions $COMP --page-size 20 --csv | grep -c PENDING)
  [ "$used" = "0" ] && [ "$pending" = "0" ] && break
  echo "$(date -u) used today=$used pending=$pending; waiting"
  sleep 300
done
k competitions submit $COMP -k $SLUG -v $VER -f submission.parquet -m "$MSG"
sleep 30
k competitions submissions $COMP --page-size 3
