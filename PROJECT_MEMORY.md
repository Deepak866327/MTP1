# Project memory: subsidence prediction rebuild

Updated: 2026-11-04. This file is durable workspace context, not a claim of global or automatic cross-chat memory.

## User intent and current status

The user wants to understand MTP 1.pdf and subsidence pdf .pdf, rebuild the same scientific project with modest improvements, and receive a phase-by-phase document. On 2026-11-04 the user requested Phase 1 implementation. Phase 1 geometry, strict project inputs, independent meshes, previews and exports are implemented. Displacement/strain prediction is not implemented, and no field result has been reproduced here.

## Implemented Phase 1

- Python package: subsidence/; Python 3.11+, pinned numpy==2.4.6. Local .venv is installed. No app/plugin or cloud service is used.
- Input schema version 1: units in metres, global z upward, horizontal surface elevation, observation field rectangle, seam reference/normal, extraction rectangles, separate source_mesh and surface_grid spacings, evidence/provenance/notes. Unknown keys and invalid geometry are rejected.
- Seam normals are normalized/upward while preserving the original input vector. Extraction-corner and reference depths must be positive. Vertical planes are rejected; geometry above 12 degrees is flagged in summaries as outside the report's prediction scope.
- Exact rectangular union tiles are clipped against a source grid anchored at the extraction bounding box. Each disjoint fragment has its own midpoint on the seam plane. Overlaps are counted once. Both plan area and seam area (plan/nz) are exported; no inclined solver area choice is implied. The observation field never crops sources.
- Cell-centered surface arrays have shape (ny,nx,3), x fastest on flattening. Last cells are shortened for nondivisible extents. Source/surface spacing and domain changes are independent. Empty extraction is supported. Meshes default to a 2-million-point/cell safety limit.
- Examples: examples/synthetic_flat.json (800 sources, 2,000 surface points); examples/adriyala_geometry.json (5,775 sources, 10,857 surface points). Adriyala plan area 577,500 m2; plane corner depths 367.7991299-456.68 m; dip 10.30467587 degrees. These are geometry calculations, not reproduced field results.
- CLI from workspace: .\.venv\Scripts\python.exe -m subsidence validate examples/adriyala_geometry.json; use mesh <project.json> --output <new-or-empty-directory> to generate project.json, summary.json, geometry.npz, sources.csv, surface.csv, preview.svg.
- Generated example bundles: outputs/synthetic_flat and outputs/adriyala_geometry, including SVG previews and inspection PNG copies. outputs is ignored; regenerate with a fresh output directory.
- Verification: .\.venv\Scripts\python.exe -m unittest discover -s tests -v; 25 tests passed, including an independent union-area oracle, overlap/partial/empty regions, source-plane/depth checks, mesh independence, config/export round trips and CLI checks.
- Implementation conventions and acceptance evidence: docs/PHASE1_IMPLEMENTATION.md. README has setup/run instructions. The main plan and Word/PDF copies remain dated planning documents.
- Next numerical phase is Phase 2 flat-seam displacement plus analytical rectangular-integral checks. Phase 0 inclined/amplitude/support gaps remain logged; Phase 1 does not resolve them or add a solver.

## Sources

- MTP 1.pdf: 33 scanned PDF pages. Report titled Prediction of Surface Subsidence and Strain over Inclined Seam using Influence Function Method. Author Ayan Ahmed, supervisor Prof. Debasis Deb, IIT Kharagpur, 1 May 2026. Do not infer the user is the report's author.
- subsidence pdf .pdf: 28 scanned PDF pages, Chapter 12, Subsidence, from Fundamentals and Applications of Rock Mechanics by Deb and Verma. Printed pages 345–371, with final printed page repeated.
- OCR and page images are in docs/source_extracts. OCR is incomplete in places; consult images for equations and precise values. Important formula and case-study pages were visually checked.
- Main editable plan: docs/PROJECT_UNDERSTANDING_AND_REBUILD_PLAN.md. Word copy: docs/Subsidence_Project_Understanding_and_Rebuild_Plan.docx. Searchable 14-page PDF copy: docs/Subsidence_Project_Understanding_and_Rebuild_Plan.pdf. Initial transcribed inputs: docs/adriyala_reported_inputs.json.

## Core understanding

Mining-induced trough subsidence above longwall coal extraction. The Influence Function Method sums influence from small extracted elements. The chosen stochastic kernel is Phi(r) = exp(-pi*r^2/R^2)/R^2, with R = H*tan(beta) for flat geometry and settlement increment Smax*Phi*dA. Original engine is C++. The inclined extension retains the kernel concept and handles seam orientation/depth and local/global coordinate transformation. Reported applicability is flat and gently inclined single seams, approximately up to 12 degrees. This is final-subsidence prediction, without a demonstrated time model.

Outputs: Ux, Uy, Uz, Ex = dUx/dx, Ey = dUy/dy. Strains use centered finite differences. Original GUI already includes multiple rectangular extraction regions, field/grid/seam inputs, selectable colored maps, summary statistics, cursor inspection, and arbitrary profile lines. Reproduce these as existing features. Frontend technology is unspecified; do not invent it.

Training/testing in the report means calibration on one monitoring line and evaluation on another. It is not evidence of an ML engine. Stochastic kernel does not mean the software performs Monte Carlo uncertainty analysis.

## Adriyala facts, transcribed from MTP PDF pp.24–26

- Physical panel: 2333 m x 250 m; seam thickness 6.5–7 m; extraction height 3.5 m; gradient 1 in 5.5; depths 366.12–456.68 m.
- Computational field 2310 m x 470 m; dx=dy=10 m; 231x47=10,857 observation cells.
- Reported seam normal (-0.0186,-0.1779,0.9838). Norm approximately 0.999928; inferred dip approximately 10.305 degrees, consistent with gradient.
- Seam reference (0,120,-456.68) m. Extraction rectangle x=[0,2310], y=[120,370] m.
- p=1.3 m (trial and error); beta=20 degrees. Later text also labels the fitted amplitude Smax=1.3; resolve naming before coding.
- Fit line S11–S58; testing line S61–S99 using same parameters.
- Reported RMSE approximately 0.25 m fitting, 0.26 m testing, at subsidence magnitudes/ranges described as about 1.25 m and 1.6 m. These have not been independently recomputed.
- Map screenshot minimum Uz approximately -1.277 m.
- Observation start 2014-10-15; panel completion 2016-12-29; stated observation end/sealing 2017-10-27.

## Reproduction gaps and cautions

No complete original source code, raw station coordinates/observations, build system, exact calibration procedure, or full coordinate/area conventions are supplied. Field comparisons shown validate vertical subsidence for this case; independently measured horizontal displacement/strain is not provided. Estimated strain curves are model outputs. Synthetic checks cannot be called field validation. Digitized graphs can only support an explicitly approximate reproduction.

Equation 10, MTP PDF p.22, appears as Smax=p/n_s^z, meaning the normal's z component, not a confirmed square. Verify its interpretation, vector rotation, and amplitude normalization. Resolve vertical depth versus normal separation and plan area versus seam area. Plane formula: za=zref-[nx*(xa-xref)+ny*(ya-yref)]/nz. Source corner depths from reported computational inputs are approximately 456.68, 413.01, 411.47, 367.80 m; physical minimum depth differs slightly. Physical panel length 2333 and modeled length 2310 also differ.

Gaussian full-plane integral=1; inside radius R integral=1-exp(-pi)=0.9568. Finite-radius truncation needs an explicit support/normalization policy. Textbook finite-ring method normalizes weights. Do not renormalize only the mined portion. Horizontal cancellation requires symmetry about the evaluation point, not merely that an influence circle contains the panel. Separate dip, influence angle, and azimuth variable names; source notation reuses beta. Strain is dimensionless; 0.001 equals 1 mm/m.

MTP PDF pp.27–28 duplicate the same Uz/Ey page. Textbook pp.27–28 duplicate printed p.371. Report heading/table numbering is inconsistent; cite PDF page numbers.

## Implementation choices and remaining proposals

Preserve the scientific method and scope. Phase 1 uses Python/NumPy. SciPy/pandas with Plotly and local Streamlit UI remain the proposed stack for later phases, not implemented dependencies. If C++ is an academic requirement or original code becomes available, retain a C++ core; otherwise add it only for a measured performance need. No hosted website or cloud service is needed for the initial project.

Three modest improvements: repeatable bounded calibration of amplitude and beta; numerical convergence plus held-out field metrics; saved projects and complete export bundles. Sensitivity envelopes or shear/principal strain are optional. Never claim improved accuracy before testing. Steep seams, interacting multiple seams, time dependence, geological layering, and structural-damage classification are future research scope.

Phases, roughly 6–8 focused weeks if data is available: 0 specify equations/data; 1 geometry and independent meshes; 2 flat-seam displacement; 3 strains/profiles; 4 inclined model; 5 Adriyala baseline; 6 automatic calibration; 7 interface and exports; 8 sensitivity/final verification/report. Detailed tasks and acceptance criteria are in the plan.

Keep the test line out of fitting. Save raw measurements and datum/sign metadata. Evaluate predictions at station coordinates. Numerical checks should include zero extraction, symmetry, amplitude linearity, analytical flat-panel integral, coordinate round-trip and zero-dip limit, manufactured derivative fields, and mesh convergence. No arbitrary accuracy guarantees.

## Useful source locations

MTP p.4 abstract; pp.15–19 theory and transformations; pp.20–23 computation/interface; pp.24–26 Adriyala; pp.27–30 results; pp.31–33 scope and future work. Textbook pp.17–21 IFM and worked movement example. Sinkhole content pp.24–28 is outside the implemented project. Luo 2015, cited by the report, is supplemental literature with a different asymmetric-function approach; do not silently replace the original formulation with it.
