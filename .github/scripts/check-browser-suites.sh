#!/usr/bin/env bash
# Each harness owns a disposable library and HTTP server. Keep the long
# language suite on its own display while its companion checks run in sequence.
set -euo pipefail
browser=${1:?provide a Playwright browser}
output=${2:?provide an artifact directory}
mkdir -p "$output"

run_suite() {
  local name=$1 started=$SECONDS
  shift
  echo "Starting $name ($browser)"
  if "$@" >"$output/$name.log" 2>&1; then
    echo "Passed $name ($browser) in $((SECONDS - started))s"
  else
    echo "Failed $name ($browser), see $name.log" >&2
    tail -n 40 "$output/$name.log" >&2
    return 1
  fi
}

run_suite interface env GTK_OVERLAY_SCROLLING=0 xvfb-run -a -n 99 python packaging/check_browser_languages.py \
  --headed --browser "$browser" --output "$output" &
interface_pid=$!

failed=0
if [[ $browser == chromium ]]; then
  run_suite integrity python packaging/check_workflow_integrity.py \
    --output "$output/workflow-integrity" || failed=1
fi
run_suite dropbox xvfb-run -a -n 199 python packaging/check_dropbox_connector_ui.py \
  --headed --browser "$browser" --output "$output/dropbox-connector" || failed=1
run_suite cloud xvfb-run -a -n 199 python packaging/check_cloud_connections_ui.py \
  --headed --browser "$browser" --output "$output/cloud-connections" || failed=1
wait "$interface_pid" || failed=1
exit "$failed"
