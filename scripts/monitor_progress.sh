#!/bin/bash
# 1시간마다 826t 실행 진행상황을 progress_live.md에 기록

CSV="output/experiments/agent_qwen25_step2_fixed_826t.csv"
MD="progress_live.md"
LOG="progress_live_log.tsv"
TOTAL_TABLES=826
TOTAL_CELLS=84907
START_TS=$(date +%s)

# 로그 헤더
echo -e "timestamp\ttables\tannotations\tpct_tables\teta_hours" > "$LOG"

while true; do
    NOW=$(date "+%Y-%m-%d %H:%M:%S")
    CURRENT_TS=$(date +%s)
    ELAPSED=$(( CURRENT_TS - START_TS ))

    if [ -f "$CSV" ]; then
        LINES=$(wc -l < "$CSV")
        TABLES=$(cut -d',' -f1 "$CSV" | sort -u | wc -l)
    else
        LINES=0
        TABLES=0
    fi

    PCT_T=$(echo "scale=1; $TABLES * 100 / $TOTAL_TABLES" | bc 2>/dev/null || echo "?")
    REMAINING=$(( TOTAL_TABLES - TABLES ))

    if [ "$TABLES" -gt 0 ] && [ "$ELAPSED" -gt 0 ]; then
        AVG_SEC=$(( ELAPSED / TABLES ))
        ETA_SEC=$(( AVG_SEC * REMAINING ))
        ETA_H=$(( ETA_SEC / 3600 ))
        ETA_DATE=$(date -d "+${ETA_SEC} seconds" "+%m/%d %H:%M" 2>/dev/null)
    else
        ETA_H="?"
        ETA_DATE="계산 중"
    fi

    # MD 파일 덮어쓰기 (최신 상태)
    cat > "$MD" << MDEOF
# 826t 진행 상황

**실험**: agent_qwen25_step2_fixed_826t
**마지막 업데이트**: $NOW

| 항목 | 값 |
|------|----|
| 완료 테이블 | **$TABLES / $TOTAL_TABLES** ($PCT_T%) |
| 어노테이션 | $LINES / $TOTAL_CELLS |
| 잔여 테이블 | $REMAINING |
| 예상 잔여 | ~${ETA_H}시간 |
| 예상 완료 | $ETA_DATE |

## 시간별 기록

| 시각 | 테이블 | 어노테이션 | 진행률 | 잔여(h) |
|------|--------|-----------|--------|---------|
MDEOF

    # 로그에서 기록 테이블 재생성
    tail -n +2 "$LOG" | while IFS=$'\t' read -r ts t a p e; do
        echo "| $ts | $t | $a | ${p}% | ~${e}h |"
    done >> "$MD"

    # 로그 추가
    echo -e "$NOW\t$TABLES\t$LINES\t$PCT_T\t$ETA_H" >> "$LOG"

    sleep 3600
done
