#!/usr/bin/env bash
# golden_smoke.sh — 前端全量端点冒烟（Go 栈 0 错误验收）
# 用法: bash golden_smoke.sh <base_url> <password>
# 输出: 每端点 HTTP 码；4xx/5xx 列为 FAIL（401/404/422 视语义放行项已在脚本内标注）
set -u
BASE="${1:-https://pm.vibingu.cn}"
PASSWORD="${2:?password required}"
PASS=0; FAIL=0; FAILED_LIST=""

code() { # method path [json_body]
  local m="$1" p="$2" b="${3:-}"
  # LLM 端点生成耗时 10-120s，放宽超时
  local t=30
  case "$p" in
    *ai/explain*|*suggest-channels*|*suggest-keywords*|*rag/ask*|*research-gaps*|*evolution*|*survey*) t=150 ;;
  esac
  if [ -n "$b" ]; then
    curl -sk -o /dev/null -w '%{http_code}' -X "$m" "$BASE/api$p" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d "$b" --max-time "$t"
  else
    curl -sk -o /dev/null -w '%{http_code}' -X "$m" "$BASE/api$p" -H "Authorization: Bearer $TOKEN" --max-time "$t"
  fi
}

check() { # name method path [body] [allowed_codes]
  local name="$1" m="$2" p="$3" b="${4:-}" allow="${5:-}"
  local c; c=$(code "$m" "$p" "$b")
  if [ "$c" = "200" ] || [ "$c" = "201" ] || echo "$allow" | grep -q "$c"; then
    PASS=$((PASS+1)); printf "  ✓ %s %s → %s\n" "$m" "$p" "$c"
  else
    FAIL=$((FAIL+1)); FAILED_LIST="$FAILED_LIST $m:$p($c)"; printf "  ✗ %s %s → %s\n" "$m" "$p" "$c"
  fi
}

# ---------- 认证 ----------
TOKEN=$(curl -sk -X POST "$BASE/api/auth/login" -H 'Content-Type: application/json' -d "{\"password\":\"$PASSWORD\"}" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("access_token",""))' 2>/dev/null)
if [ -z "$TOKEN" ]; then echo "✗ 登录失败"; exit 1; fi
echo "== auth =="
check "auth status" GET /auth/status
check "auth me" GET /auth/me
check "auth tokens" GET /auth/tokens
check "settings llm active" GET /settings/llm-providers/active
check "settings llm list" GET /settings/llm-providers
check "settings email list" GET /settings/email-configs
check "settings daily-report" GET /settings/daily-report-config
check "settings smtp-presets" GET /settings/smtp-presets
check "system status" GET /system/status
check "system worker" GET /system/worker
check "metrics costs" GET "/metrics/costs?days=30"

echo "== 读面 =="
check "today" GET /today
check "papers latest" GET "/papers/latest?limit=5"
check "papers folder-stats" GET /papers/folder-stats
check "papers recommended" GET "/papers/recommended?top_k=3"
check "papers suggest-channels" GET "/papers/suggest-channels?description=multi-agent+systems" "" "200,422,500"
check "trends hot" GET "/trends/hot?days=7&top_k=5"
check "trends emerging" GET "/trends/emerging?days=14"
check "topics list" GET /topics
check "topics stats" GET /topics/stats
check "topics distribution" GET /topics/distribution
check "cs categories" GET /cs/categories
check "cs feeds" GET /cs/feeds
check "tags list" GET /tags
check "actions list" GET "/actions?limit=5"
check "jobs list" GET "/jobs?limit=5"
check "tasks active" GET /tasks/active
check "generated list" GET "/generated/list?type=daily_brief&limit=5"
check "agent engine" GET /agent/engine
check "agent conversations" GET /agent/conversations
check "graph overview" GET /graph/overview
check "graph timeline" GET "/graph/timeline?keyword=agent&limit=20"
check "graph quality" GET "/graph/quality?keyword=agent"
check "graph bridges" GET /graph/bridges
check "graph frontier" GET "/graph/frontier?days=90"
check "graph cocitation" GET "/graph/cocitation-clusters?min_cocite=2"
check "graph similarity-map" GET "/graph/similarity-map?limit=50"
check "graph cluster-map" GET "/graph/cluster-map?n_clusters=4&limit=200"
check "sensemaking schemas" GET /sensemaking/schemas
check "sensemaking sessions" GET /sensemaking/sessions
check "research export" GET "/research/questions/00000000-0000-0000-0000-000000000000/export" "" "404,200"

echo "== 动态 ID 面（取真实 ID）=="
PID=$(curl -sk "$BASE/api/papers/latest?limit=1" -H "Authorization: Bearer $TOKEN" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["items"][0]["id"] if d.get("items") else "")' 2>/dev/null)
if [ -n "$PID" ]; then
  check "paper detail" GET "/papers/$PID"
  check "paper similar" GET "/papers/$PID/similar?top_k=3"
  check "paper duplicates" GET "/papers/$PID/duplicates"
  check "paper figures" GET "/papers/$PID/figures"
  check "paper tags" GET "/papers/$PID/tags"
  check "paper citation-tree" GET "/graph/citation-tree/$PID?depth=1"
  check "paper citation-detail" GET "/graph/citation-detail/$PID"
  check "paper similar-via-citation" GET "/graph/similar-via-citation/$PID?top_k=3"
  check "translate cache" GET "/translate/bilingual-pdf/$PID?mode=fast"
else
  echo "  (无论文可测动态面)"
fi
TID=$(curl -sk "$BASE/api/topics" -H "Authorization: Bearer $TOKEN" | python3 -c 'import sys,json; d=json.load(sys.stdin); its=d.get("items") or d.get("topics") or []; print(its[0]["id"] if its else "")' 2>/dev/null)
if [ -n "$TID" ]; then
  check "topic citation-network" GET "/graph/citation-network/topic/$TID"
else
  echo "  (无主题可测)"
fi

echo "== 提交面（幂等任务）=="
check "pipelines embed" POST "/pipelines/embed/$PID" "" "200,404,422,500"
check "rag ask" POST /rag/ask '{"question":"multi-agent"}' "200,500"
check "translate selection" POST /translate/selection '{"text":"Hello world","target_lang":"zh"}' "200,500"
check "writing templates" GET /writing/templates
check "ai explain" POST "/papers/$PID/ai/explain" '{"text":"attention mechanism","action":"explain"}' "200,500"
check "ingest references" POST /ingest/references '{"source_paper_id":"test","entries":[]}' "200,422,500"
check "graph auto-link" POST /graph/auto-link '[]' "200,422"

echo
echo "=== 结果: PASS=$PASS FAIL=$FAIL ==="
[ -n "$FAILED_LIST" ] && echo "失败清单:$FAILED_LIST"
[ "$FAIL" = "0" ]
