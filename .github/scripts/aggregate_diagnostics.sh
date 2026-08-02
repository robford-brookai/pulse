#!/usr/bin/env bash
set -e

# Expect environment variables ci310 ci311 ci312 ci313 ci314 to be set to each step's outcome
fail_count=0
for id in ci310 ci311 ci312 ci313 ci314; do
  outcome_var=$(printenv "$id")
  echo "$id -> ${outcome_var:-unknown}"
  if [ "${outcome_var:-unknown}" != "success" ]; then
    fail_count=$((fail_count+1))
  fi
done
if [ "$fail_count" -eq 0 ]; then
  echo "healthy=true" >> "$GITHUB_OUTPUT"
else
  echo "healthy=false" >> "$GITHUB_OUTPUT"
fi
