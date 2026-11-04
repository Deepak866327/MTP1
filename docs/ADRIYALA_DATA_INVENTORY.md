# Adriyala evidence and data readiness

Audited 4 November 2026 for Phase 5. MTP scanned PDF pp.24–26 were visually inspected again. The repository has no raw monitoring CSV/XLSX table. The site-plan image and plotted line distances do not establish reliable global station positions.

| Evidence needed | Available material | Readiness |
| --- | --- | --- |
| Physical panel geometry | MTP p.24, transcribed JSON | Available; physical/computational dimensions differ |
| Computational field, seam plane, extraction | MTP p.25; examples/adriyala_geometry.json | Available as reported geometry |
| Baseline p and influence angle | p=1.3 m and beta=20 degrees on p.25; p.26 calls amplitude Smax | Applied by explicit Phase 4 reconstruction; original naming/conventions unconfirmed |
| Fit/test assignment | S11–S58 fitting, S61–S99 testing | Available |
| Monitoring station x/y and survey transform | p.24 site map; station details contain an unfinished placeholder | Missing reliable numeric table/transform |
| Raw measured Uz and actual station spacing/order | Only plotted curves on pp.25–26 | Missing raw table |
| Vertical datum and sign of raw observations | Negative subsidence visible in plots | Raw datum/sign metadata missing; do not infer all preprocessing |
| Observation stage/date for each plotted series | Broad observation dates on p.24 | Exact plotted measurement stage not established |
| Original engine/code/conventions | Report description and equations | Code unavailable; rotation/area/support/amplitude details not fully confirmed |
| Reported RMSE | Approximately 0.25 m fitting and 0.26 m testing, p.26 | Source-reported; not independently recomputed from raw observations |
| Digitized observed/reported-model traces | data/adriyala_digitized/report_traces.json | Approximate published-curve audit available |

The observation period begins 2014-10-15, panel completion is stated as 2016-12-29, and observation end/sealing as 2017-10-27. These dates do not establish which measurement stage each graph uses. No date/stage is assigned to invented station records.

The approximate audit compares curves already printed in the report. It uses no global station coordinates and does not call the rebuilt solver. Its approximately 0.249/0.253 m trace RMSE values have digitization and resampling uncertainty; they do not establish exact original-RMSE reproduction.

For actual rebuilt-model comparison, supply station_id, line_id, x_m, y_m and observed Uz, plus metadata documenting the coordinate reference/origin/orientation, vertical datum/sign, measurement stage, measurement provenance and fixed fit/test line assignment. Coordinates must already be in the model's global metre frame. If only line distance is available, an independently documented survey transform is required before prediction; the software will not invent one.

The provided CSV template has only a header and the JSON template has null fields for unknown metadata. Their validation failure is intentional. Replace unknowns with sourced measurements and documented metadata, retaining original raw files. The Phase 5 workflow applies only an explicitly declared vertical-sign conversion and reports any discrepancy from published errors without fitting or datum adjustment.

Phase 5 status: **station comparison software and approximate published-curve audit implemented; exact Adriyala field reproduction incomplete**. Phase 6 can use verified station inputs when available; do not calibrate a spatial model to the unlocated plot-distance traces as though their survey coordinates were known.

Phase 6 software is now implemented: bounded multi-start amplitude/beta fitting, saved fit objectives and identifiability diagnostics, frozen held-out evaluation and manual-parameter comparison. Independent-reference synthetic parameter recovery passes. Actual Adriyala fitting remains pending the same station evidence plus documented site bounds; the synthetic demonstration bounds are not validated Adriyala bounds. See [Phase 6 implementation](PHASE6_IMPLEMENTATION.md).
