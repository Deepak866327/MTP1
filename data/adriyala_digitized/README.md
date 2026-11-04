# Approximate Adriyala published-profile digitization

`report_traces.json` stores manually picked image pixels and calibration anchors from MTP PDF p.25 Fig.10 and p.26 Fig.11. These pages were visually checked, including enlarged source-pixel overlays. The observed mine curve and reported fitted/predicted curve use the left subsidence axis. The estimated-strain trace uses a different axis and is excluded.

The data contains **no global station coordinates and no station identities**. Trace points and comparison samples are not assigned S11/S12/... IDs. No attempt is made to reconstruct the survey transform from the low-resolution site plan.

Each line records the original source-image path/hash, PDF page, left-axis zero and negative-value tick, approximate upper/lower plot borders, distance ticks, horizontal image shear, and sparse pixel picks `(image_x, observed_y, reported_model_y)`. There are 17 picked fitting-line pairs and 27 testing-line pairs. All source-pixel coordinates refer to the existing 1340-by-1895 PNGs in `docs/source_extracts/images`.

The photographed page is curved. Vertical calibration first normalizes each picked ordinate between piecewise-linear upper/lower plot borders, then maps it using the recorded left-axis zero/negative tick. Horizontal coordinates are approximately referred to the bottom axis using a 9-pixel (p.25) or 3-pixel (p.26) shear and the recorded distance ticks. Endpoint tick calibration extends linearly by no more than one tick interval; it is not a survey-coordinate transformation.

The two calibrated curves are linearly sampled on their common 10 m distance grid. This gives 45 fitting-line comparison points over 0–440 m and 40 testing-line points over 10–400 m. It does not recover the original monitoring-station counts or all local fluctuations. Comparing a more densely interpolated trace cannot restore information absent from the scan.

Assumed per-curve reading bounds are ±0.05 m vertically and ±10 m along the distance axis. They are rough digitization bounds, not measured field uncertainty or statistical confidence intervals. The diagnostic RMSE interval based on vertical bounds alone is ±0.10 m around the trace RMSE; it omits distance, scan-calibration and sparse-tracing uncertainty.

Run from the workspace:

```powershell
.\.venv\Scripts\python.exe -m subsidence audit-report-profiles data/adriyala_digitized/report_traces.json --output outputs/adriyala_published_audit
```

The audit retains source-page/PDF copies, original pixels, calibrated trace CSV, comparison CSV, published-curve plots, source-pixel overlays and a report. Its archived `digitization.json` can be rerun directly because source paths are rewritten to its copied `sources` directory and hashes are preserved. Input source PDFs and images are checked against their hashes before any audit is produced.

Computed approximate trace RMSE is 0.2492608102 m for S11–S58 and 0.2534653452 m for S61–S99. The printed report gives approximately 0.25 m and 0.26 m. This graphical audit supports approximate consistency of the published curves; it **does not evaluate the rebuilt engine at stations or independently reproduce the original field RMSE**. Keep exact reproduction marked incomplete.
