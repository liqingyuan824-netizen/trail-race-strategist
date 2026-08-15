# W1 synthetic FIT fixtures

All fixture bytes in this directory are invented for tests. They are minimal
FIT protocol records assembled from public FIT protocol field definitions, do
not originate from a person or device, and contain no real GPS, heart-rate, or
account data. The `.fit.b64` representation exists so the repository patch
remains text-only; tests decode it only into a temporary private directory.
