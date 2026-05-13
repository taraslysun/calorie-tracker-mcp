#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
LOG=/tmp/bucket_ingest.log
echo "[$(date '+%H:%M:%S')] start" >> "$LOG"
uv run --group ingest python scripts/bucket_ingest.py \
    --page-limit 200 --embed-batch 32 --bucket-concurrency 1 >> "$LOG" 2>&1
RC=$?
END=$(date '+%H:%M:%S')
echo "[$END] exit rc=$RC" >> "$LOG"

POINTS=$(uv run python -c '
import asyncio, os
from dotenv import load_dotenv
load_dotenv()
from tablycja_client import cache as qc
async def go():
    c=qc.make_client()
    try:
        i=await c.get_collection(qc.collection_name())
        print(i.points_count)
    finally:
        await c.close()
asyncio.run(go())
' 2>/dev/null || echo "?")

if [[ $RC -eq 0 ]]; then
    TITLE="Bucket ingest done"
    MSG="rc=0  points=$POINTS  at $END"
    SOUND="Glass"
else
    TITLE="Bucket ingest FAILED"
    MSG="rc=$RC  points=$POINTS  at $END  -- see $LOG"
    SOUND="Basso"
fi
osascript -e "display notification \"$MSG\" with title \"$TITLE\" sound name \"$SOUND\""
say -v Samantha "$TITLE"
exit $RC
