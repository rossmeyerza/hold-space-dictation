#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <chrome-extension-id>" >&2
  exit 2
fi

extension_id="$1"
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
host_path="$repo_dir/native/host.py"
target_dir="$HOME/.config/google-chrome/NativeMessagingHosts"
target_file="$target_dir/com.ross.hold_space_dictation.json"

chmod +x "$host_path"
mkdir -p "$target_dir"
sed \
  -e "s#__HOST_PATH__#$host_path#g" \
  -e "s#__EXTENSION_ID__#$extension_id#g" \
  "$repo_dir/native/com.ross.hold_space_dictation.json.template" > "$target_file"

echo "Installed native messaging host:"
echo "$target_file"
