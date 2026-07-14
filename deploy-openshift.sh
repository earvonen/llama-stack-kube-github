#!/usr/bin/env bash
# Deploy the openshift/ Kustomize overlay with github-mcp fsGroup matched to the
# namespace UID range (required for nginx emptyDir volumes on OpenShift restricted SCC).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
NAMESPACE="${OPENSHIFT_NAMESPACE:-agentic-demo}"
KUSTOMIZE_DIR="${KUSTOMIZE_DIR:-${ROOT}/openshift}"

if ! command -v oc >/dev/null 2>&1; then
  echo "error: oc not found in PATH" >&2
  exit 1
fi

echo "==> Ensuring namespace ${NAMESPACE} exists" >&2
oc apply -f "${KUSTOMIZE_DIR}/namespace.yaml"

FSGROUP=""
for _ in $(seq 1 30); do
  FSGROUP="$(oc get namespace "${NAMESPACE}" -o jsonpath='{.metadata.annotations.openshift\.io/sa\.scc\.uid-range}' 2>/dev/null | cut -d/ -f1)"
  if [[ -n "${FSGROUP}" ]]; then
    break
  fi
  sleep 1
done

if [[ -z "${FSGROUP}" ]]; then
  echo "error: namespace ${NAMESPACE} has no openshift.io/sa.scc.uid-range annotation" >&2
  exit 1
fi

echo "==> Applying overlay (github-mcp fsGroup=${FSGROUP})" >&2
oc kustomize "${KUSTOMIZE_DIR}" \
  | sed "s/^\([[:space:]]*fsGroup:\) [0-9][0-9]*/\1 ${FSGROUP}/" \
  | oc apply -f -

echo "==> Deployments in ${NAMESPACE}:" >&2
oc get deploy,pods -n "${NAMESPACE}"
