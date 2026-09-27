#!/usr/bin/env bash
# Create the price book v1 (docs/PLAN-GTM.md §4) in Stripe as products + prices with stable lookup_keys.
# Idempotent: a lookup_key that already exists is skipped. Test mode by default; live needs ALLOW_LIVE=1.
#
# Usage (key is read from the env file, never typed on the command line; app.env is a docker env file, not shell,
# so only the one line is read):
#   sudo bash -c 'export STRIPE_SECRET_KEY="$(grep -m1 ^STRIPE_SECRET_KEY= /opt/blockid/app.env | cut -d= -f2-)";
#                 ALLOW_LIVE=1 bash scripts/stripe/seed-prices.sh'
set -euo pipefail

: "${STRIPE_SECRET_KEY:?STRIPE_SECRET_KEY is not set (add it to /opt/blockid/app.env)}"
case "$STRIPE_SECRET_KEY" in
  sk_test_*|rk_test_*) MODE=test ;;
  sk_live_*|rk_live_*) MODE=live
    [ "${ALLOW_LIVE:-0}" = 1 ] || { echo "Live key detected; re-run with ALLOW_LIVE=1 to seed live mode." >&2; exit 1; } ;;
  *) echo "STRIPE_SECRET_KEY does not look like a Stripe secret key." >&2; exit 1 ;;
esac
echo "Seeding Stripe ($MODE mode)"

api() { curl -sS -u "$STRIPE_SECRET_KEY:" "$@"; }

# product <id> <name>: fixed ids (bid_*) so monthly and yearly prices share one product.
product() {
  local id=$1 name=$2
  local got; got=$(api "https://api.stripe.com/v1/products/$id")
  if grep -q '"object": "product"' <<<"$got"; then return; fi
  api https://api.stripe.com/v1/products -d "id=$id" -d "name=$name" -d "tax_code=txcd_10000000" >/dev/null
  echo "  + product $id"
}

# price <lookup_key> <product id> <product name> <amount in cents AUD> <tax: inclusive|exclusive> [interval: month|year]
price() {
  local key=$1 pid=$2 name=$3 cents=$4 tax=$5 interval=${6:-}
  product "$pid" "$name"
  local got; got=$(api -G https://api.stripe.com/v1/prices -d "lookup_keys[]=$key")
  if grep -q '"lookup_key": "'"$key"'"' <<<"$got"; then
    echo "  = $key (exists)"; return
  fi
  local args=(-d currency=aud -d "unit_amount=$cents" -d "tax_behavior=$tax" -d "lookup_key=$key" -d "product=$pid")
  [ -n "$interval" ] && args+=(-d "recurring[interval]=$interval")
  local out; out=$(api https://api.stripe.com/v1/prices "${args[@]}")
  if echo "$out" | grep -q '"error"'; then echo "  ! $key: $out" >&2; exit 1; fi
  echo "  + $key $(echo "$out" | grep -m1 '"id"' | tr -d ' ",')"
}

# One-off reports: consumer prices, GST included (Australian Consumer Law).
price passport_check      bid_passport_check       "Passport check report"                  5900 inclusive
price valuation_ai        bid_valuation_ai         "Valuation report"                      29900 inclusive
price valuation_expert    bid_valuation_expert     "Valuation report, expert-reviewed"     89000 inclusive
price people_report       bid_people_report        "People report"                          4900 inclusive
price people_report_10    bid_people_report_10     "People report pack (10)"               39000 inclusive
price people_report_50    bid_people_report_50     "People report pack (50)"              169000 inclusive
price cv_analysis         bid_cv_analysis          "CV analysis add-on"                     1900 inclusive
price team_report         bid_team_report          "Team report (up to 6 people)"          19900 inclusive

# Business plans: shown "+GST", so GST is added on top.
price founder_monthly     bid_founder              "Founder plan"                           4900 exclusive month
price founder_yearly      bid_founder              "Founder plan"                          49000 exclusive year
price growth_monthly      bid_growth               "Growth plan"                           14900 exclusive month
price growth_yearly       bid_growth               "Growth plan"                          149000 exclusive year
price angel_group_monthly bid_angel_group          "Angel group plan"                      19900 exclusive month
price recruiter_monthly   bid_recruiter            "Recruiter team plan"                   29900 exclusive month
price recruiter_extra     bid_recruiter_extra      "Recruiter extra people report"          3500 exclusive

echo "Done. Extra holders (A\$2/holder/yr) and white label are quoted/invoiced, not seeded here."
