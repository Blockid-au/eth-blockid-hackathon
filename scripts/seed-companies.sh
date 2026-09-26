#!/usr/bin/env bash
# Runs real companies through the full Studio flow on the live stack (admin session):
# AI valuation -> approve -> ticker -> holders -> issue on BlockID Chain -> anchor on Hoodi -> optional revaluation.
# Usage: scripts/seed-companies.sh "url|name|revalue_pct" ...
set -uo pipefail
B=${B:-https://eth.blockid.au/api}; CK=$(mktemp); OWNER=0xc309691C60957A55bB619383A06d3F69A94f4585
curl -s -H 'Origin: https://eth.blockid.au' -c "$CK" -H 'content-type: application/json' -d '{"username":"admin","password":"admin"}' "$B/v1/auth/login" >/dev/null
rand_addr(){ ~/.foundry/bin/cast wallet new --json 2>/dev/null | jq -r '(.data // .) | if type=="array" then .[0].address else .address end'; }
wait_status(){ local path=$1 re=$2; for _ in $(seq 1 120); do s=$(curl -s -H 'Origin: https://eth.blockid.au' -b "$CK" "$B$path" | jq -r .status); [[ "$s" =~ $re ]] && { echo "$s"; return; }; sleep 8; done; echo timeout; }
for spec in "$@"; do
  IFS='|' read -r url name reval <<<"$spec"
  echo "== $name ($url)"
  vid=$(curl -s -H 'Origin: https://eth.blockid.au' -b "$CK" -H 'content-type: application/json' -d "{\"url\":\"$url\"}" "$B/v1/studio/valuations" | jq -r .id)
  st=$(wait_status "/v1/studio/valuations/$vid" '^(waiting_approval|failed)$'); echo "   valuation $vid: $st"
  [ "$st" = waiting_approval ] || continue
  curl -s -H 'Origin: https://eth.blockid.au' -b "$CK" -H 'content-type: application/json' -d '{"approved":true}' "$B/v1/studio/valuations/$vid/decision" | jq -c '{svi:.svi.index,band:.svi.band,mid:.svi.valuation_mid_aud}'
  tk=$(curl -s -H 'Origin: https://eth.blockid.au' -b "$CK" "$B/v1/studio/tickers/suggest?name=$(jq -rn --arg n "$name" '$n|@uri')" | jq -r '[.candidates[]|select(.available)][0].ticker')
  a1=$(rand_addr); a2=$(rand_addr); a3=$(rand_addr)
  body=$(jq -n --arg v "$vid" --arg n "$name" --arg t "$tk" --arg o "$OWNER" --arg a1 "$a1" --arg a2 "$a2" --arg a3 "$a3" \
    '{valuation_id:$v,name:$n,ticker:$t,holders:[{name:"Founders",wallet:$o,pct:52},{name:"Seed fund",wallet:$a1,pct:23},{name:"ESOP pool",wallet:$a2,pct:15},{name:"Angel investors",wallet:$a3,pct:10}]}')
  cid=$(curl -s -H 'Origin: https://eth.blockid.au' -b "$CK" -H 'content-type: application/json' -d "$body" "$B/v1/studio/companies" | jq -r .id)
  curl -s -H 'Origin: https://eth.blockid.au' -b "$CK" -X POST "$B/v1/studio/companies/$cid/submit" >/dev/null
  curl -s -H 'Origin: https://eth.blockid.au' -b "$CK" -X POST "$B/v1/admin/companies/$cid/approve-issue" >/dev/null
  echo "   $tk issue: $(wait_status "/v1/companies/$tk" '^(issued|failed)$')"
  curl -s -H 'Origin: https://eth.blockid.au' -b "$CK" -X POST "$B/v1/admin/companies/$cid/approve-anchor" >/dev/null
  echo "   $tk anchor: $(wait_status "/v1/companies/$tk" '^(anchored|failed)$')"
  if [ -n "$reval" ] && [ "$reval" != 0 ]; then
    cur=$(curl -s -H 'Origin: https://eth.blockid.au' "$B/v1/companies/$tk" | jq -r .valuation_aud)
    nv=$(python3 -c "print(round($cur*(1+$reval/100)))")
    curl -s -H 'Origin: https://eth.blockid.au' -b "$CK" -H 'content-type: application/json' -d "{\"valuation_aud\":$nv,\"note\":\"SVI re-run ${reval}%\"}" "$B/v1/admin/companies/$cid/revalue" | jq -c '{ticker,mark_aud}'
  fi
done
rm -f "$CK"
