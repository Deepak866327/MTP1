# Surface Subsidence and Strain Prediction

## Understanding the existing project and rebuilding it with modest improvements

Prepared on 3 November 2026 from the two PDFs in this workspace. This is a study and implementation plan; the prediction application has not yet been rebuilt here.

## 1. What the project is about

The project predicts how the ground surface moves after coal is extracted underground, especially by longwall mining. When the roof above the mined area caves and the overlying rock mass adjusts, the surface can settle into a broad depression called a subsidence trough or basin. Surface points also move horizontally. Differences in those movements produce stretching and compression, which are relevant to buildings, roads, pipelines, and other surface assets.

The original report is titled **Prediction of Surface Subsidence and Strain over Inclined Seam using Influence Function Method**, by Ayan Ahmed, supervised by Professor Debasis Deb at IIT Kharagpur, dated 1 May 2026. Its central task is to extend a flat-seam subsidence model to gently inclined coal seams and turn that model into usable software. The documented scope is approximately **0–12 degrees of seam inclination**, with the abstract using less than 12 degrees and the conclusion saying up to about 12 degrees. This is the report's applicability limit, rather than a universal geological classification. (MTP, PDF pp.1, 4, 31–33.)

In everyday terms: enter the mine layout, depth, seam orientation, extraction areas, and calibrated influence parameters; the program predicts where the surface will sink, how far it will move horizontally, and where horizontal strain will develop.

This is a mathematical prediction and numerical computation project. The words training and testing in the report describe parameter fitting on one monitoring line and evaluation on another. The presented method does not require a machine-learning model. Likewise, stochastic describes the influence-function formulation; the report does not document Monte Carlo uncertainty simulation.

### How the two PDFs relate

| Source | What it contains | How we use it |
| --- | --- | --- |
| MTP 1.pdf: 33 PDF pages | Project report: theory, inclined-seam extension, C++ implementation description, software features, Adriyala case study, results, limitations | Main source for what the original project built and what we must reproduce |
| subsidence pdf .pdf: 28 PDF pages | Photographed Chapter 12, Subsidence, from Fundamentals and Applications of Rock Mechanics; printed pp.345–371, including a repeated final page | Theory source for subsidence, influence functions, displacement, strain, and worked examples |

The textbook chapter covers more than this project, including sinkhole subsidence, physical models, and other prediction methods. The reported application focuses on trough subsidence using the stochastic influence function. A sinkhole-prediction module is a separate task.

Both files are image scans. Text was extracted locally with OCR and important equations, input values, plots, and result pages were also checked visually. OCR text is a reading aid and may omit or misread lines. References below use **PDF page numbers**, counted from the first page, because the report's section numbering and printed page numbering are inconsistent.

## 2. What was built in the original project

The report describes three connected outputs: a mathematical formulation, a numerical computation engine, and an interactive analysis interface.

| Part | Documented behavior | Evidence |
| --- | --- | --- |
| Flat-seam model | Calculates surface influence from small extracted elements using a stochastic influence function | MTP pp.15–18; textbook pp.17–21 |
| Inclined-seam extension | Uses seam geometry and a change of coordinates to apply the influence calculation and transform displacement back into the ground coordinate system | MTP pp.16–19 |
| C++ engine | Discretizes the mine and surface, superposes contributions, and stores displacement fields | MTP pp.20–23 |
| Displacement outputs | Ux, Uy, and Uz: movement along the global x, y, and vertical directions | MTP pp.20–23 |
| Strain outputs | Ex and Ey, calculated from horizontal displacement gradients | MTP p.22 |
| Graphical inputs | Field dimensions, grid spacing, seam normal, reference coordinates, subsidence parameter, influence angle, and multiple rectangular extraction areas | MTP p.20 |
| Interactive results | Colored field maps, selectable fields and color maps, statistics, cursor inspection, and user-defined cross-section lines | MTP p.23; screenshots pp.27–29 |
| Field comparison | Fits one Adriyala monitoring line and predicts a second using the same fitted parameters | MTP pp.24–26 |

Multiple rectangular extraction regions are already described in the original interface. Heatmaps, point inspection, custom profile lines, and summary statistics are also existing features. They should be reproduced as baseline functionality rather than presented as new contributions.

The supplied report identifies C++ as the numerical engine language. It does not identify the interface framework, supply a complete source-code listing, document a build system, or provide a complete software distribution. We cannot infer that the interface used Qt, React, Python, or any particular web framework from these PDFs.

## 3. How the original project was built

### Step 1: Understand the mechanics and choose a prediction method

The work begins with the textbook treatment of subsidence. Important concepts include mining depth, extraction height, seam dip, angle of draw, critical and subcritical extraction, surface slope, horizontal displacement, and horizontal strain. The chapter compares empirical, analytical, profile-function, influence-function, physical-model, and numerical approaches. (Textbook, PDF pp.1–16.)

The project chooses the Influence Function Method, or IFM. It treats the extracted area as many small sources. Each source creates a spatial distribution of movement at the surface, and the contributions are added. The project uses the stochastic influence function as its chosen distribution. (Textbook pp.17–20; MTP pp.12–18.)

### Step 2: Divide the geometry into small elements

A rectangular computational field is divided using spacings dx and dy. In the reported implementation, cell-center surface coordinates are written as:

```text
Px = i * dx + dx/2
Py = j * dy + dy/2
Pz = 0
```

The extraction map records whether a cell has been mined. Extracted cells become influence sources; unextracted cells do not contribute. Multiple rectangular extraction regions can be included. The source geometry is placed on the seam plane using its orientation and a reference point. (MTP pp.20–21.)

The rebuild should separate the extraction mesh from the observation grid, even if the initial reproduction uses the same spacing. This allows us to refine numerical integration without unnecessarily increasing the number of displayed surface points.

### Step 3: Compute the contribution from one extracted element

For a flat seam, the stochastic kernel shown in the documents is:

```text
Phi(r) = exp(-pi * r^2 / R^2) / R^2
R = H * tan(beta)
dS = Smax * Phi(r) * dA
```

Here H is depth, r is horizontal distance from the source to the surface point's vertical projection, R is the influence scale, and dA is the extracted element area. The influence is strongest near the source and decreases with distance. Smax sets the subsidence amplitude. A cell-center approximation uses kernel value at the cell center multiplied by cell area; it should be checked by mesh refinement rather than assumed to be an exact cell integral. (MTP pp.15, 18, 21–22; textbook p.18, Eq.12.24.)

As a simple illustration, H = 400 m and beta = 20 degrees give R approximately 145.6 m. This is an explanatory calculation, not an additional measured mine result.

### Step 4: Add all contributions and resolve displacement directions

The textbook and report relate the magnitude of elemental horizontal movement to vertical movement using:

```text
dU_horizontal = dS * r/H
```

The horizontal movement is resolved into x and y components with the direction from the surface point toward the source. The program sums the contributions of all extracted elements at each surface point to obtain Ux, Uy, and Uz. These are vector contributions: direction and sign must be retained. (Textbook pp.20–21; MTP pp.15–19, 22.)

For our rebuild, adopt a clear global convention: z is positive upward, subsidence has Uz < 0, and the positive settlement magnitude is S = -Uz. For a flat seam at depth H and a source at (xa, ya), a consistent form is:

```text
dUz = -dS
dUx = dS * (xa - Px) / H
dUy = dS * (ya - Py) / H
```

The sign convention is our explicit implementation choice. It must be reconciled with the original equations and stored in run metadata. At the center of a symmetric flat-seam extraction, horizontal contributions cancel. Cancellation depends on symmetry; merely enclosing the whole panel inside an influence circle is not enough to guarantee zero horizontal movement at an arbitrary point.

### Step 5: Extend the calculation to an inclined seam

In an inclined seam, depth and the relationship between surface and seam coordinates vary across the panel. The report retains the stochastic influence-function concept, represents seam orientation using a normal vector, transforms into a seam-related coordinate system, evaluates influence there, and transforms displacement back into global coordinates. This creates an asymmetric trough. A simple rotation of an already computed flat-seam result would not capture the full geometry described. (MTP pp.16–19.)

A useful geometric starting point for the rebuild is the plane equation:

```text
n dot (A - Aref) = 0
za = zref - [nx * (xa - xref) + ny * (ya - yref)] / nz
```

Normalize n and ensure it points consistently upward. For source A and surface point P, the source-to-point vector can be decomposed into normal and tangential parts:

```text
d = P - A
h_normal = d dot n
q_tangent = d - h_normal * n
r_tangent = norm(q_tangent)
```

These are geometric identities, not a complete replacement derivation of the original inclined-seam solver. Before coding that solver, resolve whether depth means vertical depth or normal separation, which coordinates the influence kernel uses, how dA is measured, and how the displacement components are rotated. MTP pp.21–22 refer to normal depth, while the surrounding explanation also discusses depth changing along dip. Those statements need a single precise mathematical specification.

Equation 10 on MTP p.22 appears to express **Smax = p / n_s^z**, where n_s^z denotes the normal's z component. The exact normalization and its interaction with vector transformation should be verified against original code if available. Page 25 labels p = 1.3 m, while p.26 describes the fitted amplitude as Smax = 1.3. Keep these names distinct until the convention is resolved; do not silently assume they are identical for inclined geometry.

### Step 6: Calculate horizontal strain

After computing displacement, the report estimates the two normal horizontal strain components by centered differences:

```text
Ex[i,j] = (Ux[i+1,j] - Ux[i-1,j]) / (2 * dx)
Ey[i,j] = (Uy[i,j+1] - Uy[i,j-1]) / (2 * dy)
```

Strain is dimensionless. For display, 0.001 strain equals 1 mm/m. A common convention is positive tensile strain and negative compressive strain. Boundary cells need a documented one-sided method or must be excluded from derivative summaries. Array axes must be documented so the x derivative is actually taken along x. (MTP p.22.)

The report's arbitrary cross-section plotting is an existing visualization feature. If the rebuild later reports normal strain along an arbitrary line direction, compute the full horizontal strain tensor, including shear, before projecting it onto that direction. Ex and Ey alone do not define directional strain for every line.

### Step 7: Build the interface and compare against measurements

The original interface replaces static input files with graphical entry and displays the computed fields directly. It includes user-defined profiles and statistics. The case study then compares model profiles with measured vertical subsidence. The report describes a direct computation cost proportional to the number of sources times the number of surface points, O(Nsources × Nsurface). It mentions loop and memory optimizations but does not provide a repeatable timing benchmark. (MTP pp.20–26.)

```text
Mine geometry + extraction areas + parameters
    -> seam geometry and extracted cells
    -> surface evaluation points
    -> influence contributions and superposition
    -> Ux, Uy, Uz
    -> Ex, Ey and profile sampling
    -> maps, statistics, measured/predicted comparisons
```

## 4. What the Adriyala case study demonstrates

### Reported mine and model inputs

The physical panel description and the computational geometry are slightly different and should both be retained. The following are transcribed from MTP PDF pp.24–25.

| Item | Reported value |
| --- | --- |
| Location | Adriyala Mine, Telangana, India |
| Physical Longwall Panel-1 dimensions | 2333 m long × 250 m wide |
| Seam thickness | 6.50–7.00 m |
| Height of extraction | 3.50 m |
| Seam gradient | 1 in 5.5 |
| Reported panel depth range | 366.12–456.68 m |
| Computational field | 2310 m × 470 m |
| Grid spacing | dx = 10 m; dy = 10 m |
| Reported seam normal components | (-0.0186, -0.1779, 0.9838) |
| Reference point on seam | (0, 120, -456.68) m |
| Computational extraction rectangle | x = 0–2310 m; y = 120–370 m |
| Reported p | 1.3 m, obtained by trial and error |
| Influence angle beta | 20 degrees |
| Fit line | S11–S58 |
| Independent test line in the report | S61–S99 |

The normal's length is approximately 0.99993, consistent with rounded unit-normal components. Normalizing it gives an inferred dip of approximately 10.305 degrees, which agrees with arctan(1/5.5). This calculation checks the transcription; it does not establish the full surveyed geometry. The 2310-by-470 field at 10 m spacing gives 231 × 47 = **10,857 surface points**, consistent with the screenshots.

Using the reported reference point and the plane equation above gives source-corner vertical depths of approximately 456.68, 413.01, 411.47, and 367.80 m over the computational rectangle. The last value differs slightly from the physical minimum depth of 366.12 m. The difference between surveyed panel size, computational panel size, and rounded orientation values must be explained rather than silently corrected.

The report's observation period begins on 15 October 2014, the panel completion date is 29 December 2016, and the stated observation end/panel sealing date is 27 October 2017. Those dates describe the case study; the implemented model is presented as a final-subsidence model rather than a time-evolution model. (MTP pp.24, 33.)

### Reported results and their limits

The report fits a profile on S11–S58 and uses the same estimated parameters on S61–S99. It reports RMSE of approximately **0.25 m for fitting** and **0.26 m for testing**, with corresponding subsidence magnitudes/ranges described as about 1.25 m and 1.6 m. The Uz map screenshot has a minimum near -1.277 m. These are reported results, not results independently reproduced in this workspace. (MTP pp.25–27.)

These comparisons support the report's ability to reproduce a broad subsidence trough for this case. They do not establish universal mine-to-mine accuracy. An error of 0.25 m means roughly 25 cm RMSE, not 0.25 percent error. The visible measured profiles also contain departures from the smooth prediction. The report attributes these to geological variation, caving irregularities, and measurement uncertainty; these explanations are plausible interpretations rather than mechanisms independently demonstrated by the provided data. (MTP pp.26, 29–30.)

The field comparisons shown are for **vertical subsidence**. Curves labeled estimated strain are model outputs; they are not independent strain measurements. The PDFs do not demonstrate measured-field validation of every Ux, Uy, Ex, and Ey output.

### What prevents an exact reproduction immediately

The workspace initially contained only the two PDFs. They do not include complete original source code, raw station coordinates and measurements, the precise fitted objective, full survey-coordinate conversion, measurement uncertainty, or all numerical conventions. Monitoring-station details on p.24 include an unfinished placeholder rather than a complete dataset description.

We can rebuild the model and software from the documented method. Exact reproduction of the published RMSE requires the actual monitoring tables and matching conventions. If only the graphs are available, digitized values can support an approximate comparison, provided they are labeled as digitized and their uncertainty is retained. Synthetic data can verify the computation but cannot substitute for field validation.

## 5. The rebuild we should target

Working title: **Reproducible Prediction of Surface Subsidence and Strain over Gently Inclined Coal Seams**.

The first target is a working reproduction of the documented scientific method: flat and gently inclined single-seam geometry, one or more rectangular extraction regions, Ux/Uy/Uz, Ex/Ey, field maps, statistics, custom profiles, and measured-versus-predicted subsidence evaluation.

Add three modest, useful improvements after establishing that baseline:

| Improvement | Why it helps | How we demonstrate it |
| --- | --- | --- |
| Automatic, bounded fitting of p/amplitude and beta | Replaces reported trial-and-error calibration with a repeatable procedure | Save objective, bounds, initial guesses, fitted values, residuals, and fit/test metrics |
| Numerical and field-validation report | Makes mesh sensitivity, residual patterns, and applicability visible | Compare mesh levels, preserve a separate testing line, and show RMSE/MAE/bias and peak errors |
| Saved projects and exportable runs | Allows another person to reproduce a result and reuse inputs | Save configuration, inputs, field/profile CSV, figures, and a run summary together |

An optional small extension is a parameter-sensitivity envelope. If parameter ranges are assumed rather than inferred statistically, label the output as a sensitivity envelope rather than a confidence interval. Another optional extension is shear and principal horizontal strain; this needs a proper tensor implementation and verification.

Keep steep seams beyond the report's approximately 12-degree scope, interacting multiple seams, time-dependent face advance, detailed geological layering, and automated structural-damage classification for later research. These change the scientific scope and are not required for a modest rebuild. Several of them are explicitly listed as future work in MTP pp.32–33.

## 6. Suggested implementation approach

### Technology choice

For a fresh build, start with **Python, NumPy, SciPy, pandas, Plotly, and a local Streamlit interface**. This makes the equations and fitting procedure straightforward to inspect and modify. Keep the numerical core independent of the interface. This preserves the scientific project while changing the implementation language from the original C++ engine.

If retaining C++ is a course requirement, or original C++ code becomes available, use a C++ numerical core with the same configuration and result formats. If Python performance becomes a measured problem, optimize the identified kernel or move it to C++ after numerical parity is established. Do not maintain two complete engines without a concrete reason.

SciPy provides bounded nonlinear least-squares fitting and numerical integration tools. Streamlit supports Plotly figures and file downloads, which cover the planned interactive plots and export workflow. Exact dependency versions should be selected and pinned when implementation begins. Sources: [SciPy least_squares](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.least_squares.html), [SciPy simpson](https://docs.scipy.org/doc/scipy/reference/generated/scipy.integrate.simpson.html), [Streamlit Plotly charts](https://docs.streamlit.io/develop/api-reference/charts/st.plotly_chart), and [Streamlit downloads](https://docs.streamlit.io/develop/api-reference/widgets/st.download_button).

This is a local scientific application plan. It does not require a hosted website, user accounts, a cloud database, or a separate API for the first version.

### Proposed modules

| Module | Responsibility |
| --- | --- |
| config and data loading | Units, coordinate metadata, schema checks, saved project files, observation CSV |
| geometry | Seam plane, normalized normal, local/global coordinate conversion, extraction membership |
| mesh | Independent source discretization and surface grids; partial boundary cells |
| influence | Flat and inclined formulations with explicit amplitude, support, and normalization conventions |
| solver | Accumulate vector contributions with predictable memory use |
| deformation | Ex, Ey, derivative boundaries; optional shear, slope, and curvature |
| profiles | Sample fields along requested lines and evaluate directly at monitoring points |
| calibration | Fit training observations with recorded bounds and starts |
| validation | Residual metrics, numerical convergence, held-out evaluation |
| visualization and reporting | Maps, profiles, summaries, saved runs, export |
| interface | Input forms and results presentation; calls the core without embedding its equations |

The solver interface should accept a validated project configuration and evaluation points, and return coordinates, displacement, strain where applicable, units, and metadata. Monitoring predictions should be evaluated at the actual station coordinates, rather than comparing the nearest plotted cell to each station without documenting that approximation.

## 7. Phase-by-phase rebuild plan

Estimated effort is **6–8 focused working weeks for one developer/student**, assuming the monitoring data and formula decisions become available early. This is a planning estimate. Data recovery or a required C++ interface can add time. The week allocations include room for learning and integration.

| Phase | Suggested timing | Main deliverable | Dependency |
| --- | --- | --- | --- |
| 0 | Week 1, first half | Source audit, equation specification, data inventory | Supplied PDFs |
| 1 | Week 1, second half | Geometry, configuration, and independent meshes | Phase 0 conventions |
| 2 | Week 2 | Verified flat-seam displacement solver | Phase 1 |
| 3 | Week 3 | Ex/Ey and profile sampling | Phase 2 |
| 4 | Week 4 | Inclined-seam solver and geometric checks | Phases 0–3 |
| 5 | Week 5 | Adriyala baseline comparison | Phase 4 and observations |
| 6 | Week 6 | Automatic calibration and held-out metrics | Phase 5 data readiness |
| 7 | Week 7 | Interface parity, saved runs, exports | Core outputs stable |
| 8 | Week 8 | Sensitivity, final verification, report, demo | Earlier phases complete |

### Phase 0: Recover the specification and organize evidence

**Work.** Build a source-to-equation register with PDF page references. Transcribe the reported Adriyala parameters. List missing raw data and original code. Agree on units, coordinate axes, the definition of beta, p versus Smax, influence support, extraction-area measure, and displacement signs. Write out the inclined-seam transformation rather than relying on a figure alone.

**Deliverables.** A model specification, parameter dictionary, data inventory, baseline input file, and a list of unresolved assumptions. The accompanying adriyala_reported_inputs.json is an initial transcription, not a finalized runnable solver configuration.

**Ready to proceed when.** The flat-seam equations and conventions are unambiguous. Inclined-seam gaps are explicitly logged and can be resolved before Phase 4. Missing field data does not stop synthetic flat-seam development.

### Phase 1: Build geometry, input validation, and meshes

**Work.** Define field extents, extraction rectangles, seam reference point and normal. Normalize the normal and create a seam plane. Generate source-cell centers and areas, and an independent surface grid. Use extraction-region union so overlapping rectangles do not double-count extraction. Handle partially intersected boundary cells consistently.

**Deliverables.** Loadable project files, a geometry preview, and source/surface coordinate arrays. Include a symmetric synthetic flat panel and the reported Adriyala geometry as separately labeled examples.

**Ready to proceed when.** Source points lie on the specified plane, mined area matches geometry within the chosen discretization, all depths are physically consistent, and overlapping regions are counted once. The source cell size and observation-grid spacing can be changed independently.

### Phase 2: Implement the flat-seam displacement solver

**Work.** Implement the stochastic kernel, cell-area weighting, superposition, and vector displacement resolution. Start with a small transparent calculation. Compare the surface sum with an independently derived analytical rectangular-panel integral for a flat seam with constant H and Smax. Use chunks rather than allocating every source-to-observation pair for large runs.

**Deliverables.** Ux, Uy, Uz arrays with units and sign metadata; a reproducible flat-panel example; a concise verification notebook or report.

**Ready to proceed when.** No extraction gives zero movement; a symmetric flat panel gives symmetric Uz and the expected horizontal cancellation at its center; distant predictions decay; doubling amplitude doubles displacement; mesh refinement approaches the reference integral. Choose tolerances before using the solver for calibration.

### Phase 3: Compute strain and custom profiles

**Work.** Calculate Ex and Ey from displacement with documented array axes and boundary treatment. Sample Ux, Uy, Uz, Ex, and Ey along user-defined line endpoints. Include distance along the line. Verify derivatives using manufactured displacement fields with known derivatives, not only outputs of the subsidence solver.

**Deliverables.** Strain fields, profile tables, plots with explicit units, and checks for constant and linear displacement fields.

**Ready to proceed when.** Constant displacement gives zero strain, linear displacement gives the known strain, boundary handling is visible, and profile interpolation agrees with direct calculations within a documented tolerance. If arbitrary directional strain is shown, include and verify shear strain first.

### Phase 4: Implement the gently inclined seam

**Work.** Finalize the local/global coordinate basis, normal-distance definition, tangential offset, area Jacobian, amplitude normalization, and displacement rotation. Apply the same selected stochastic formulation in the agreed coordinate system. Keep the initial supported dip range within the report's approximately 12-degree scope.

**Deliverables.** An inclined-seam solver, derivation notes, and synthetic examples at zero dip and several dips within scope. Include a coordinate diagram so source and ground coordinates are easy to inspect.

**Ready to proceed when.** Zero dip reduces to the flat solver; transforming to local coordinates and back preserves points and vectors; source depths are correct; a consistent rotation/reflection of geometry and coordinates gives correspondingly transformed results. An asymmetric trough appears for the intended geometry without numerical discontinuities. Treat asymmetry alone as a qualitative check, not proof of correctness.

### Phase 5: Reproduce the Adriyala baseline

**Work.** Load station coordinates, measured Uz, line IDs, and the correct measurement stage. Recreate the documented geometry and start from p = 1.3 m and beta = 20 degrees under the resolved amplitude convention. Predict at station coordinates. Reproduce the fit-line and testing-line plots before modifying the fitting strategy.

**Deliverables.** Baseline figures, station-level predicted/observed/residual CSV, and a comparison with the reported 0.25 m and 0.26 m RMSE. Record any difference in geometry, datum, amplitude convention, kernel support, or preprocessing.

**Ready to proceed when.** Data provenance and coordinates are documented and results are numerically reproducible. Agreement with the published metrics is assessed honestly. If raw data is unavailable, publish an explicitly approximate digitized comparison and keep exact reproduction marked incomplete. Continue interface work independently while waiting for data.

### Phase 6: Add automatic calibration

**Work.** Fit the amplitude convention selected in Phase 0 and beta on S11–S58 only. Use bounded least squares, several initial guesses, and a saved residual objective. Set physically justified bounds using site information and extraction height; do not treat a parameter in metres as a dimensionless factor. Keep S61–S99 out of fitting and preprocessing decisions based on observed test outcomes.

**Deliverables.** Saved fit settings and fitted parameters, fit-line residual plots, a held-out testing report, and a comparison with the original manual parameter choice. Check whether amplitude and influence spread are separately identifiable from the available line.

**Ready to proceed when.** Calibration is repeatable; synthetic data with known parameters can recover them within justified numerical tolerance; results do not depend strongly on arbitrary starts without being reported; test results use the frozen fitted parameters. An accuracy improvement is claimed only if the held-out evidence supports it. If the test line is repeatedly used to guide revisions, a new independent evaluation dataset is needed.

### Phase 7: Rebuild the interface and add reproducible exports

**Work.** Add forms for mine parameters, extraction rectangles, grid settings, and observation upload. Reproduce original field selection, heatmaps, hover values, statistics, and line profiles. Show observed/predicted profiles and calibration results. Save project settings and complete run outputs, with clear units and source labels.

**Deliverables.** A local application that can load an example, compute, inspect results, save a project, reopen it, and export a result bundle. Include displacement and strain maps with appropriate color scales: strain benefits from a signed scale centered at zero.

**Ready to proceed when.** A user can complete that workflow without editing source code. Reopening a saved run restores its configuration and provenance. Numerical results agree with running the same core outside the interface. Changing a color map or cross-section does not trigger unnecessary recomputation of the entire model.

### Phase 8: Complete improvements and prepare the final project

**Work.** Complete grid-convergence and domain-extent studies. Add a sensitivity envelope if the data and time support it. Record runtime and memory for a stated machine and a stated mesh. Assemble the comparison between reported baseline, reproduced baseline, and improved workflow. Prepare the dissertation/report and demonstration.

**Deliverables.** Versioned source, pinned environment, example configurations, available observations with provenance, saved runs, figures, validation results, user guide, and final presentation. Include a clear distinction between functionality reproduced and improvements added.

**Completion criteria.** Another person can reproduce an example from the saved inputs. All numerical conventions are documented. Field-validation claims match the available measurements. No unpublished accuracy claim is based solely on synthetic data or a visually smooth plot. Any unresolved source discrepancy is listed in the final report.

## 8. Numerical decisions that need particular care

### Influence radius and normalization

The Gaussian kernel above integrates to one over the full plane. Within a circle of radius R, its integral is 1 - exp(-pi), approximately 0.9568. Therefore, cutting it off at R without adjusting weights drops approximately 4.32 percent of total kernel weight. The textbook explicitly normalizes finite-ring weights. (Textbook pp.19–20.)

Choose a full Gaussian or a documented finite-support approximation. If matching a finite-ring reference, reproduce its normalization. Do not renormalize only the extracted part of the kernel at each point; that would remove the intended dependence on how much of the influence region is mined. Do not change the support convention midway through a baseline comparison.

### Angles, areas, and coordinates

Use separate names for seam dip, influence angle, and horizontal azimuth. Beta is reused for different meanings in parts of the source material. Store angles with explicit units and convert degrees to radians at a controlled boundary. For an inclined panel, projected plan area and actual seam area differ; the Jacobian must match the chosen integral. Do not include an area correction twice.

The actual observation grid should extend beyond extraction boundaries to show the trough and its decay. The published field is cropped near the panel ends. Preserve that crop for screenshot reproduction, but assess a larger domain for the complete deformation field. A larger observation domain must not change predictions at existing points when all source contributions are unchanged.

### Calibration and interpretation

Keep p in metres, Smax in metres, and the textbook's separate dimensionless subsidence factor distinct. Seam thickness of 6.5–7 m is not the same as the reported extraction height of 3.5 m. Avoid introducing a new fitted parameter for every mismatch before checking geometry, signs, support, and units.

Full-grid strain is more sensitive to discretization than a smooth subsidence curve. Verify strain convergence separately from displacement convergence. Report estimated model strains as such until independent strain or horizontal-movement measurements are available.

## 9. Data, metrics, and evidence we need to retain

### Observation data

A minimum observation file should contain station_id, line_id, x_m, y_m, and uz_observed_m. Retain observation date or stage, vertical datum and sign convention, coordinate-system origin/orientation, and provenance. Optional columns include measurement uncertainty, surface elevation, observed horizontal displacement, and observed strain. If local distance is the only station coordinate available, retain the line endpoints or survey transform needed to place each station in the model.

Do not invent missing station coordinates or pretend that model-generated values are observations. Retain raw values before any cleaning. If robust fitting or outlier handling is used, document it and show the unaltered observations alongside the fitted model.

### Evaluation metrics

Let e_i = predicted Uz_i - observed Uz_i at the same station and stage.

```text
RMSE = sqrt(mean(e_i^2))
MAE  = mean(abs(e_i))
Bias = mean(e_i)
```

Also compare peak settlement magnitude and location, and the width of the trough using a stated definition. R-squared can be supplementary, but it should not replace residual plots. If reporting normalized RMSE, state the normalization denominator explicitly. Use the same metric definitions for the manual baseline and automatic calibration.

### Comparing the original and improved project

| Question | Required evidence |
| --- | --- |
| Did we reproduce the model? | Source-referenced equations and numerical checks |
| Did we reproduce Adriyala results? | Same station data, geometry, conventions, and comparable residual metrics |
| Did fitting improve? | Frozen held-out comparison plus repeatable fit procedure |
| Did usability improve? | Saved/reopened runs and complete export workflow |
| Did speed improve? | Timings on the same input, hardware, precision, and error tolerance |
| Did strain accuracy improve? | Independent strain/horizontal-movement evidence; subsidence-only fitting is insufficient |

No numerical target for improved field accuracy can be promised from the PDFs alone. Reproducibility is an achievable improvement even if the fitted model's held-out error remains similar.

## 10. First implementation tasks and final deliverables

Begin by completing the equation specification, obtaining the raw monitoring tables if available, and resolving the p/Smax and inclined-area conventions. Then implement a small flat-seam case and verify it independently before extending to the full Adriyala geometry. The graphical interface follows a verified numerical core.

The finished project should include:

1. A documented mathematical model with units, signs, support, and coordinate transformations.
2. A working flat- and gently inclined-seam numerical engine.
3. Displacement and horizontal-strain fields, maps, statistics, and custom profiles.
4. A reproducible Adriyala comparison, or an explicitly labeled approximate reproduction if data is incomplete.
5. Automatic calibration and held-out evaluation where observations permit it.
6. Saved configurations, station-level outputs, plots, and a result report.
7. A reproducible environment, numerical verification evidence, user guide, and final presentation.

## 11. Source map and further reading

The two supplied PDFs establish what the original project reports. Supplemental links below support implementation choices or wider literature; they do not fill missing original implementation details by assumption.

| Topic | Source location |
| --- | --- |
| Project identity and summary | MTP PDF pp.1, 4 |
| IFM theory and flat-seam equations | MTP pp.12–18; textbook pp.17–21 |
| Inclined geometry and transformations | MTP pp.16–19 |
| Graphical inputs, mesh, C++ solver, strains, visualization | MTP pp.20–23 |
| Adriyala physical and computational inputs | MTP pp.24–25 |
| Calibration, testing, and stated RMSE | MTP pp.25–26 |
| Result screenshots and interpretation | MTP pp.27–30 |
| Scope and future extensions | MTP pp.31–33 |
| General subsidence and movement definitions | Textbook pp.1–13 |
| Other profile functions and examples | Textbook pp.14–16 |
| Finite-ring influence weights and normalization | Textbook pp.18–21 |
| Other physical/numerical approaches | Textbook pp.23–24 |
| Sinkhole material, outside the current model | Textbook pp.24–28 |

MTP pp.27 and 28 repeat the same Uz/Ey figure page. Textbook pp.27 and 28 repeat printed p.371. Repetitions are not additional validation cases. The report's contents and table lists also do not consistently match all body headings and material.

The report cites Yi Luo's 2015 paper, which develops a continuous asymmetric influence function for inclined coal seams. It is useful for a later literature comparison and as a separate model candidate; it should not be silently substituted for the geometry-based formulation being reproduced here. [Luo, 2015, An improved influence function method for predicting subsidence caused by longwall mining operations in inclined coal seams](https://link.springer.com/article/10.1007/s40789-015-0086-x).

Local reading aids are stored under docs/source_extracts. The durable project brief is PROJECT_MEMORY.md in the workspace root. The Word document is generated from this Markdown plan, so this file remains the editable source of the rebuild document.
