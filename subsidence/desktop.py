"""Local Tkinter workbench. Launch with `python -m subsidence gui`."""

from dataclasses import replace
import gc
import json
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

from .calibration import CalibrationFailure, CalibrationSettings, load_calibration_settings
from .config import FlatModel, InclinedModel, Project, load_model, load_project
from .desktop_plots import field_figure, profile_figure, station_figure
from .geometry import ValidationError
from .observations import load_observations
from .profiles import ProfileLine
from .workspace import COLORMAPS, EXAMPLES, FIELDS, ProjectDocument, calibrate_document, compute_document, example_document, export_run, load_document, open_run, save_document


class DesktopApp:
    def __init__(self, root, document=None):
        self.root = root
        root.title("Subsidence Workbench — Phase 7")
        root.geometry("1440x920")
        root.minsize(1100, 730)
        self.run = None
        self.busy = False
        self.jobs = queue.Queue()
        self.variables = {}
        self.plots = {}
        self.profile_lines = []
        self.status = tk.StringVar(value="Load an example or project, then compute.")
        self.evidence = tk.StringVar()
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TButton", padding=(9, 5))
        style.configure("Title.TLabel", font=("Segoe UI", 19, "bold"), foreground="#17324d")
        style.configure("Sub.TLabel", foreground="#42586b")
        style.configure("Accent.TButton", background="#24648a", foreground="white")
        header = ttk.Frame(root, padding=(16, 12))
        header.pack(fill="x")
        ttk.Label(header, text="Subsidence Workbench", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="Influence function prediction • flat and gently inclined single seams (0–12°)", style="Sub.TLabel").pack(anchor="w")
        bar = ttk.Frame(root, padding=(12, 0, 12, 8))
        bar.pack(fill="x")
        self.example = tk.StringVar(value=EXAMPLES[0])
        ttk.Combobox(bar, textvariable=self.example, values=EXAMPLES, state="readonly", width=28).pack(side="left", padx=3)
        self._button(bar, "Load example", lambda: self.load_example(self.example.get()))
        self._button(bar, "Open project", self.open_project)
        self._button(bar, "Save project", self.save_project)
        self._button(bar, "Open run ZIP", self.open_archive)
        self._button(bar, "Open grid folder", self.open_grid)
        self._button(bar, "Export run ZIP", self.export_archive)
        ttk.Label(root, textvariable=self.evidence, padding=(16, 4), style="Sub.TLabel").pack(fill="x")
        body = ttk.Panedwindow(root, orient="horizontal")
        body.pack(fill="both", expand=True, padx=12)
        left = ttk.Frame(body, width=390)
        body.add(left, weight=0)
        actions = ttk.Frame(left, padding=(0, 5))
        actions.pack(fill="x")
        self._button(actions, "Compute displacement + strain", self.compute, accent=True)
        self._button(actions, "Calibrate", self.calibrate)
        canvas = tk.Canvas(left, width=365, highlightthickness=0)
        scrollbar = ttk.Scrollbar(left, orient="vertical", command=canvas.yview)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)
        self.form = ttk.Frame(canvas, padding=(0, 0, 12, 10))
        window = canvas.create_window((0, 0), window=self.form, anchor="nw")
        self.form.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
        self._build_form()
        self.tabs = ttk.Notebook(body)
        body.add(self.tabs, weight=1)
        self.map_tab = ttk.Frame(self.tabs)
        self.profile_tab = ttk.Frame(self.tabs)
        self.station_tab = ttk.Frame(self.tabs)
        self.calibration_tab = ttk.Frame(self.tabs)
        self.detail_tab = ttk.Frame(self.tabs)
        for frame, name in ((self.map_tab, "Field map"), (self.profile_tab, "Profiles"), (self.station_tab, "Observations"), (self.calibration_tab, "Calibration"), (self.detail_tab, "Run details")):
            self.tabs.add(frame, text=name)
        self._build_views()
        footer = ttk.Frame(root, padding=(12, 7))
        footer.pack(side="bottom", fill="x", before=body)
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=110)
        self.progress.pack(side="right", padx=8)
        status_label = ttk.Label(footer, textvariable=self.status, wraplength=1150)
        status_label.pack(side="left")
        footer.bind("<Configure>", lambda event: status_label.configure(wraplength=max(300, event.width - 160)))
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.set_document(document or example_document(EXAMPLES[0]))
        self._poll_id = root.after(80, self._poll)

    def _button(self, parent, text, action, accent=False):
        button = ttk.Button(parent, text=text, command=lambda: self._guard(action), style="Accent.TButton" if accent else "TButton")
        button.pack(side="left", padx=2)
        return button

    def _guard(self, action):
        if self.busy:
            self.status.set("Operation in progress. Please wait.")
            return
        try:
            return action()
        except (OSError, ValueError, TypeError, tk.TclError) as exc:
            self.status.set(str(exc))
            messagebox.showerror("Check inputs", str(exc), parent=self.root)

    def _entry(self, parent, key, label, row, *, values=None):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        variable = self.variables[key] = tk.StringVar()
        widget = ttk.Combobox(parent, textvariable=variable, values=values, state="readonly", width=20) if values else ttk.Entry(parent, textvariable=variable, width=23)
        widget.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=3)
        widget.bind("<KeyRelease>", self._dirty)
        widget.bind("<<ComboboxSelected>>", self._dirty)
        parent.columnconfigure(1, weight=1)

    def _group(self, title):
        frame = ttk.LabelFrame(self.form, text=title, padding=9)
        frame.pack(fill="x", pady=5)
        return frame

    def _build_form(self):
        project = self._group("Project and evidence")
        self._entry(project, "name", "Project name", 0)
        self._entry(project, "evidence", "Geometry evidence", 1, values=("synthetic_geometry", "reported_geometry", "custom_geometry"))
        self._entry(project, "source", "Source / description", 2)
        model = self._group("Prediction parameters")
        self._entry(model, "model", "Model", 0, values=("Flat", "Inclined v1"))
        self._entry(model, "amplitude", "Smax / p (m)", 1)
        self._entry(model, "beta", "Influence angle β (°)", 2)
        ttk.Label(model, text="Full Gaussian • global z upward\nPositive settlement = −Uz", style="Sub.TLabel").grid(row=3, columnspan=2, sticky="w")
        geometry = self._group("Field, seam and independent grids")
        labels = [("surface_z", "Surface elevation (m)"), ("xmin_m", "Field xmin (m)"), ("xmax_m", "Field xmax (m)"), ("ymin_m", "Field ymin (m)"), ("ymax_m", "Field ymax (m)"), ("ref_x", "Seam reference x (m)"), ("ref_y", "Seam reference y (m)"), ("ref_z", "Seam reference z (m)"), ("normal_x", "Seam normal x"), ("normal_y", "Seam normal y"), ("normal_z", "Seam normal z"), ("source_dx", "Source dx (m)"), ("source_dy", "Source dy (m)"), ("surface_dx", "Surface grid dx (m)"), ("surface_dy", "Surface grid dy (m)")]
        for row, (key, label) in enumerate(labels):
            self._entry(geometry, key, label, row)
        rectangles = self._group("Extraction rectangles (metres)")
        self.rectangles = ttk.Treeview(rectangles, columns=("xmin", "xmax", "ymin", "ymax"), show="headings", height=4, selectmode="browse")
        for name in self.rectangles["columns"]:
            self.rectangles.heading(name, text=name)
            self.rectangles.column(name, width=64, stretch=True)
        self.rectangles.pack(fill="x")
        self.rectangles.bind("<<TreeviewSelect>>", self._select_rectangle)
        self.rect_values = [tk.StringVar(value=value) for value in ("-200", "200", "-100", "100")]
        row = ttk.Frame(rectangles)
        row.pack(fill="x", pady=4)
        for var in self.rect_values:
            ttk.Entry(row, textvariable=var, width=8).pack(side="left", expand=True, fill="x")
        controls = ttk.Frame(rectangles)
        controls.pack(fill="x")
        self._button(controls, "Add", self.add_rectangle)
        self._button(controls, "Replace", self.replace_rectangle)
        self._button(controls, "Remove", self.remove_rectangle)
        notes = self._group("Notes (one per line)")
        self.notes = tk.Text(notes, height=4, width=30, wrap="word", font=("Segoe UI", 9))
        self.notes.pack(fill="x")
        self.notes.bind("<KeyRelease>", self._dirty)

    def _build_views(self):
        controls = ttk.Frame(self.map_tab, padding=8)
        controls.pack(fill="x")
        self.field = tk.StringVar(value="Uz")
        self.colormap = tk.StringVar(value="viridis")
        for label, variable, values in (("Field", self.field, tuple(FIELDS)), ("Color map", self.colormap, COLORMAPS)):
            ttk.Label(controls, text=label).pack(side="left", padx=5)
            box = ttk.Combobox(controls, textvariable=variable, values=values, state="readonly", width=13)
            box.pack(side="left")
            box.bind("<<ComboboxSelected>>", lambda event: self._guard(self.draw_map))
        self.stats = tk.StringVar(value="Compute to inspect fields.")
        stats_label = ttk.Label(self.map_tab, textvariable=self.stats, padding=8)
        stats_label.pack(fill="x")
        self.map_tab.bind("<Configure>", lambda event: stats_label.configure(wraplength=max(300, event.width - 25)))
        self.map_plot = ttk.Frame(self.map_tab)
        self.map_plot.pack(fill="both", expand=True)
        self.hover = tk.StringVar(value="Hover over a map cell to inspect its center and value.")
        ttk.Label(self.map_tab, textvariable=self.hover, padding=8).pack(fill="x")
        profiles = ttk.Frame(self.profile_tab, padding=8)
        profiles.pack(fill="x")
        self.profile_choice = tk.StringVar()
        self.profile_box = ttk.Combobox(profiles, textvariable=self.profile_choice, state="readonly", width=27)
        self.profile_box.pack(side="left")
        self.profile_box.bind("<<ComboboxSelected>>", lambda event: self._guard(self.draw_profile))
        self.profile_field = tk.StringVar(value="Uz")
        box = ttk.Combobox(profiles, textvariable=self.profile_field, values=tuple(FIELDS), state="readonly", width=9)
        box.pack(side="left", padx=4)
        box.bind("<<ComboboxSelected>>", lambda event: self._guard(self.draw_profile))
        self._button(profiles, "Remove line", self.remove_profile)
        editor = ttk.Frame(self.profile_tab, padding=8)
        editor.pack(fill="x")
        self.profile_vars = []
        for column, (label, value, width) in enumerate((("Name", "New profile", 16), ("x1", "-400", 8), ("y1", "0", 8), ("x2", "400", 8), ("y2", "0", 8), ("Samples", "201", 7))):
            ttk.Label(editor, text=label).grid(row=0, column=column, sticky="w", padx=2)
            var = tk.StringVar(value=value)
            self.profile_vars.append(var)
            ttk.Entry(editor, textvariable=var, width=width).grid(row=1, column=column, sticky="ew", padx=2)
            editor.columnconfigure(column, weight=1)
        buttons = ttk.Frame(editor)
        buttons.grid(row=2, columnspan=6, sticky="w", pady=5)
        self._button(buttons, "Add / replace line", self.add_profile)
        ttk.Label(self.profile_tab, text="Endpoints use global metres and must lie inside the cell-center domain. Ex/Ey remain global components.", padding=8, wraplength=650, style="Sub.TLabel").pack(fill="x")
        self.profile_plot = ttk.Frame(self.profile_tab)
        self.profile_plot.pack(fill="both", expand=True)
        stations = ttk.Frame(self.station_tab, padding=8)
        stations.pack(fill="x")
        self._button(stations, "Load station CSV + metadata", self.load_stations)
        self._button(stations, "Clear observations", self.clear_stations)
        self.station_choice = tk.StringVar()
        self.station_box = ttk.Combobox(stations, textvariable=self.station_choice, state="readonly", width=22)
        self.station_box.pack(side="left", padx=4)
        self.station_box.bind("<<ComboboxSelected>>", lambda event: self._guard(self.draw_stations))
        self.station_info = tk.StringVar(value="No station observations loaded.")
        ttk.Label(self.station_tab, textvariable=self.station_info, padding=8, wraplength=650).pack(fill="x")
        self.station_metrics = ttk.Treeview(self.station_tab, columns=("line", "role", "n", "rmse", "mae", "bias"), show="headings", height=3)
        for key in self.station_metrics["columns"]:
            self.station_metrics.heading(key, text=key.upper() + (" (m)" if key in ("rmse", "mae", "bias") else ""))
            self.station_metrics.column(key, width=95)
        self.station_metrics.pack(fill="x", padx=8)
        self.station_plot = ttk.Frame(self.station_tab)
        self.station_plot.pack(fill="both", expand=True)
        self.fit_pages = ttk.Notebook(self.calibration_tab)
        self.fit_pages.pack(fill="both", expand=True)
        self.fit_setup = ttk.Frame(self.fit_pages)
        self.fit_results = ttk.Frame(self.fit_pages)
        self.fit_pages.add(self.fit_setup, text="Fit settings")
        self.fit_pages.add(self.fit_results, text="Results")
        fit = ttk.LabelFrame(self.fit_setup, text="Fit settings — configured before held-out evaluation", padding=10)
        fit.pack(fill="x", padx=8, pady=8)
        for row, (key, label) in enumerate((("amp_lo", "Amplitude lower (m)"), ("amp_hi", "Amplitude upper (m)"), ("beta_lo", "β lower (degrees)"), ("beta_hi", "β upper (degrees)"), ("bounds_basis", "Bounds basis"), ("max_nfev", "Max function evaluations"))):
            self._entry(fit, key, label, row, values=("synthetic_demonstration", "documented_site_information") if key == "bounds_basis" else None)
        ttk.Label(fit, text="Initial guesses: amplitude (m), β (degrees), one pair per line").grid(row=6, columnspan=2, sticky="w", pady=(8, 2))
        self.starts = tk.Text(fit, height=3, width=40, font=("Consolas", 10))
        self.starts.grid(row=7, columnspan=2, sticky="ew")
        ttk.Label(fit, text="Physical/site or synthetic justification and source for both bounds").grid(row=8, columnspan=2, sticky="w", pady=(8, 2))
        self.justification = tk.Text(fit, height=3, width=40, wrap="word", font=("Segoe UI", 9))
        self.justification.grid(row=9, columnspan=2, sticky="ew")
        buttons = ttk.Frame(fit)
        buttons.grid(row=10, columnspan=2, sticky="w", pady=5)
        self._button(buttons, "Load fit settings", self.load_fit_settings)
        self._button(buttons, "Calibrate fit line + frozen test", self.calibrate, accent=True)
        ttk.Label(self.fit_setup, text="Only fit-role stations enter optimization. Test stations stay held out. Reusing test outcomes to revise settings requires new independent evaluation data.", padding=8, wraplength=650, style="Sub.TLabel").pack(fill="x")
        self.calibration_text = tk.Text(self.fit_results, height=12, wrap="word", font=("Consolas", 10))
        self.calibration_text.pack(fill="both", expand=True, padx=8, pady=4)
        self.details = tk.Text(self.detail_tab, wrap="word", font=("Consolas", 10))
        self.details.pack(fill="both", expand=True, padx=8, pady=8)

    def _set_text(self, widget, value, readonly=False):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        if readonly:
            widget.configure(state="disabled")

    def _dirty(self, event=None):
        if self.run is not None:
            self.status.set("Inputs edited. Maps still show the previous computed run; compute to refresh physical inputs.")

    def set_document(self, document, *, clear_run=True):
        self.base_document = document
        self.observations = document.observations
        self.fit_settings = document.calibration_settings
        self.profile_lines = list(document.profiles)
        data = document.project.to_dict()
        values = {"name": data["name"], "evidence": data["evidence"], "source": data["provenance"].get("desktop_source_description", data["provenance"].get("description", "")), "surface_z": data["surface_elevation_m"], "model": "Flat" if isinstance(document.model, FlatModel) else "Inclined v1", "amplitude": getattr(document.model, "smax_m", getattr(document.model, "p_m", None)), "beta": document.model.influence_angle_deg, **data["field"]}
        for i, suffix in enumerate(("x", "y", "z")):
            values[f"ref_{suffix}"] = data["seam"]["reference_xyz_m"][i]
            values[f"normal_{suffix}"] = data["seam"]["normal_xyz"][i]
        for key, section in (("source", "source_mesh"), ("surface", "surface_grid")):
            for axis in ("dx", "dy"):
                values[f"{key}_{axis}"] = data[section][f"{axis}_m"]
        for key, value in values.items():
            self.variables[key].set(str(value))
        self.rectangles.delete(*self.rectangles.get_children())
        for rect in data["extraction_rectangles"]:
            self.rectangles.insert("", "end", values=[rect[k] for k in ("xmin_m", "xmax_m", "ymin_m", "ymax_m")])
        self._set_text(self.notes, "\n".join(data["notes"]))
        self.field.set(document.selected_field)
        self.colormap.set(document.colormap)
        self._fill_fit_settings(document.calibration_settings)
        self._refresh_profile_choices()
        self._refresh_station_info()
        self.evidence.set(f"Geometry: {data['evidence']}  |  Global metres; z upward; settlement = −Uz  |  Original field reproduction remains incomplete")
        if clear_run:
            self.run = None
            self._clear_plots()
            self.stats.set("Compute displacement and strain to inspect fields.")
            self.station_metrics.delete(*self.station_metrics.get_children())
            self._set_text(self.calibration_text, "No calibration in this project yet. Bounds and evidence must be documented.", True)
            self.fit_pages.select(self.fit_setup)
            self._set_text(self.details, json.dumps(data, indent=2, ensure_ascii=False), True)
        self.status.set("Project loaded. Compute to create maps and evaluate observations.")

    def _fill_fit_settings(self, settings):
        self.fit_settings = settings
        for key in ("amp_lo", "amp_hi", "beta_lo", "beta_hi"):
            self.variables[key].set("")
        self.variables["bounds_basis"].set("synthetic_demonstration" if self.base_document.project.evidence == "synthetic_geometry" else "documented_site_information")
        self.variables["max_nfev"].set("200")
        self._set_text(self.starts, "")
        self._set_text(self.justification, "")
        if settings is not None:
            for key, value in zip(("amp_lo", "amp_hi", "beta_lo", "beta_hi"), (*settings.amplitude_bounds_m, *settings.influence_angle_bounds_deg)):
                self.variables[key].set(str(value))
            self.variables["bounds_basis"].set(settings.bounds_basis)
            self.variables["max_nfev"].set(str(settings.max_nfev))
            self._set_text(self.starts, "\n".join(f"{a}, {b}" for a, b in settings.initial_guesses))
            self._set_text(self.justification, settings.bounds_justification)

    def collect_document(self, *, require_fit=False):
        def number(key):
            try:
                return float(self.variables[key].get())
            except ValueError as exc:
                raise ValidationError(f"Enter a number for {key}.") from exc
        data = self.base_document.project.to_dict()
        data.update(name=self.variables["name"].get(), evidence=self.variables["evidence"].get(), surface_elevation_m=number("surface_z"))
        data["field"] = {k: number(k) for k in ("xmin_m", "xmax_m", "ymin_m", "ymax_m")}
        data["seam"] = {"reference_xyz_m": [number(f"ref_{a}") for a in ("x", "y", "z")], "normal_xyz": [number(f"normal_{a}") for a in ("x", "y", "z")]}
        for key, section in (("source", "source_mesh"), ("surface", "surface_grid")):
            data[section] = {f"{a}_m": number(f"{key}_{a}") for a in ("dx", "dy")}
        data["extraction_rectangles"] = [dict(zip(("xmin_m", "xmax_m", "ymin_m", "ymax_m"), map(float, self.rectangles.item(i, "values")))) for i in self.rectangles.get_children()]
        data["notes"] = self.notes.get("1.0", "end-1c").splitlines()
        original_source = data["provenance"].get("desktop_source_description", data["provenance"].get("description", ""))
        if self.variables["source"].get() != original_source:
            data["provenance"] = {**data["provenance"], "desktop_source_description": self.variables["source"].get()}
        model = (FlatModel if self.variables["model"].get() == "Flat" else InclinedModel)(number("amplitude"), number("beta"))
        settings = None
        if require_fit or any(self.variables[k].get().strip() for k in ("amp_lo", "amp_hi", "beta_lo", "beta_hi")):
            guesses = []
            for line in self.starts.get("1.0", "end-1c").splitlines():
                if line.strip():
                    guesses.append(tuple(float(v.strip()) for v in line.split(",")))
            controls = {} if self.fit_settings is None else {k: getattr(self.fit_settings, k) for k in ("ftol", "xtol", "gtol")}
            settings = CalibrationSettings((number("amp_lo"), number("amp_hi")), (number("beta_lo"), number("beta_hi")), tuple(guesses), self.variables["bounds_basis"].get(), self.justification.get("1.0", "end-1c"), int(self.variables["max_nfev"].get()), **controls)
        return ProjectDocument(Project.from_dict(data), model, tuple(self.profile_lines), self.observations, settings, self.field.get(), self.colormap.get())

    def load_example(self, name):
        self.set_document(example_document(name))

    def open_project(self):
        path = filedialog.askopenfilename(parent=self.root, title="Open desktop project JSON", filetypes=[("Desktop project", "*.json")])
        if path:
            info = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            if isinstance(info, dict) and info.get("application") == "subsidence_desktop":
                self.set_document(load_document(path))
            else:
                project = load_project(path)
                model = filedialog.askopenfilename(parent=self.root, title="Choose model settings for this geometry", filetypes=[("Model settings", "*.json")])
                if model:
                    self.set_document(ProjectDocument(project, load_model(model)))

    def save_project(self):
        document = self.collect_document()
        path = filedialog.asksaveasfilename(parent=self.root, title="Save project with configuration and observations", defaultextension=".json", filetypes=[("Desktop project", "*.json")])
        if path:
            save_document(document, path)
            self.status.set(f"Project saved: {path}")

    def open_archive(self):
        path = filedialog.askopenfilename(parent=self.root, title="Reopen saved run without recomputing", filetypes=[("Run archive", "*.zip")])
        if path:
            self._begin("Opening saved run…", lambda: open_run(path), self.show_run)

    def open_grid(self):
        path = filedialog.askdirectory(parent=self.root, title="Select a CLI solve/deform output folder")
        if path:
            self._begin("Opening saved grid…", lambda: open_run(path), self.show_run)

    def _ready_run(self):
        if self.run is None:
            raise ValidationError("Compute or open a saved run first.")
        doc = self.collect_document()
        if not self.run.matches(doc):
            raise ValidationError("Physical inputs or observations changed. Compute before exporting this run.")
        self.run.document = replace(self.run.document, profiles=doc.profiles, selected_field=doc.selected_field, colormap=doc.colormap)
        return self.run

    def export_archive(self):
        run = self._ready_run()
        path = filedialog.asksaveasfilename(parent=self.root, title="Export complete run to a new ZIP filename", defaultextension=".zip", filetypes=[("Run archive", "*.zip")])
        if path:
            self._begin("Exporting arrays, figures and provenance…", lambda: export_run(run, path), lambda value: self.status.set(f"Complete run exported: {path}"))

    def compute(self):
        document = self.collect_document()
        self._begin("Computing displacement, strain and station predictions…", lambda: compute_document(document), self.show_run)

    def calibrate(self):
        document = self.collect_document(require_fit=True)
        self._begin("Calibrating fit-role stations, then evaluating the frozen model…", lambda: calibrate_document(document), self.show_run)

    def _widgets(self, widget):
        for child in widget.winfo_children():
            yield child
            yield from self._widgets(child)

    def _begin(self, message, operation, success):
        # Tk objects in Matplotlib reference cycles must be finalized on the
        # Tk thread. Reference counting still frees numerical working arrays;
        # defer cycle collection until this job returns to the event loop.
        gc.collect()
        self.gc_was_enabled = gc.isenabled()
        gc.disable()
        self.busy = True
        self.status.set(message)
        self.progress.start(12)
        self.disabled_widgets = []
        for widget in self._widgets(self.root):
            if isinstance(widget, (ttk.Entry, ttk.Combobox, ttk.Button, tk.Text)):
                self.disabled_widgets.append((widget, str(widget.cget("state"))))
                widget.configure(state="disabled")
        self.on_success = success

        def work():
            try:
                self.jobs.put((True, operation()))
            except Exception as exc:
                self.jobs.put((False, exc))
        threading.Thread(target=work, daemon=True, name="subsidence-compute").start()

    def _poll(self):
        try:
            ok, value = self.jobs.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.progress.stop()
            if self.gc_was_enabled:
                gc.enable()
            gc.collect()
            for widget, state in self.disabled_widgets:
                widget.configure(state=state)
            if ok:
                self._guard(lambda: self.on_success(value))
            else:
                self.status.set(str(value))
                if isinstance(value, CalibrationFailure):
                    self._set_text(self.calibration_text, "No converged start; no fitted model selected or held-out evaluation performed.\n\n" + json.dumps(value.attempts, indent=2), True)
                    self.tabs.select(self.calibration_tab)
                    self.fit_pages.select(self.fit_results)
                messagebox.showerror("Operation failed", str(value), parent=self.root)
        self._poll_id = self.root.after(80, self._poll)

    def show_run(self, run):
        self._clear_plots()
        self.set_document(run.document, clear_run=False)
        self.run = run
        self.draw_map()
        if self.profile_lines:
            self.draw_profile()
        self.draw_stations()
        if run.calibration is not None:
            c = run.calibration
            report = {"evidence": c.fitted.dataset.metadata.evidence, "manual_model": c.manual_model.to_dict(), "fitted_model": c.fitted_model.to_dict(), "selected_start_index": c.selected_start, "selected_fit_sum_squared_residual_m2": c.attempts[c.selected_start]["sum_squared_residual_m2"], "line_comparisons": {name: {"role": metrics["role"], "manual": c.manual.line_metrics[name], "fitted": metrics} for name, metrics in c.fitted.line_metrics.items()}, "diagnostics": c.diagnostics}
        else:
            report = run.calibration_summary
        self._set_text(self.calibration_text, "No calibration in this run." if report is None else self._fit_report(report), True)
        self.fit_pages.select(self.fit_setup if report is None else self.fit_results)
        details = {"project": run.document.project.to_dict(), "model": run.document.model.to_dict(), "solver": run.displacement.metadata, "strain": run.strain.metadata, "calibration": report, "field_statistics": {f: run.statistics(f) for f in FIELDS}, "evidence_note": "Reported geometry is not field validation. Synthetic observations verify software only. Original inclined conventions remain unconfirmed."}
        self._set_text(self.details, json.dumps(details, indent=2, ensure_ascii=False), True)
        self.status.set("Run ready. Map/color/profile changes reuse cached arrays. Save project or export a portable run ZIP.")

    @staticmethod
    def _fit_report(report):
        manual, fitted = report["manual_model"], report["fitted_model"]
        amplitude = "smax_m" if "smax_m" in fitted else "p_m"
        d = report["diagnostics"]
        lines = ["AUTOMATIC CALIBRATION", f"Evidence: {report['evidence']}", "", "Parameter                 Manual         Fitted", f"{amplitude + ' (m)':24s}  {manual[amplitude]:12.7g}  {fitted[amplitude]:12.7g}", f"{'Influence angle (deg)':24s}  {manual['influence_angle_deg']:12.7g}  {fitted['influence_angle_deg']:12.7g}", "", "FIT AND HELD-OUT TESTING — frozen parameters", "Residual = predicted global Uz - observed global Uz; all errors in metres.", ""]
        for name, comparison in report["line_comparisons"].items():
            m, f = comparison["manual"], comparison["fitted"]
            lines.extend([f"{name} ({comparison['role']}), {f['count']} stations", f"  Manual RMSE {m['rmse_m']:.7g} m → Fitted RMSE {f['rmse_m']:.7g} m", f"  Fitted MAE {f['mae_m']:.7g} m; bias {f['bias_m']:.7g} m", ""])
        lines.extend([f"Fit-only sum of squared residuals: {report['selected_fit_sum_squared_residual_m2']:.7g} m²", f"Selected start: {report['selected_start_index']}; converged starts: {d['successful_start_count']}", f"Local parameter sensitivity rank: {d['scaled_jacobian_rank']}/2; scaled condition: {d['scaled_jacobian_condition_number']}", "", *d["warnings"], "Local sensitivity and agreeing starts do not prove uniqueness or establish confidence intervals.", "Synthetic recovery verifies software only. Actual field improvement requires independent held-out measurements.", "", "Full objectives, residuals, comparisons and plots are retained by Export run ZIP. Numerical diagnostics and source information are available in Run details."])
        return "\n".join(lines)

    def _clear_plots(self):
        for key in list(self.plots):
            self._discard_plot(key)

    def _discard_plot(self, key):
        canvas, toolbar = self.plots.pop(key)
        # Clear while the live toolbar can still receive history updates.
        # Cancel TkAgg's queued idle draw before destroying its Tk widget.
        idle = getattr(canvas, "_idle_draw_id", None)
        if idle is not None:
            canvas.get_tk_widget().after_cancel(idle)
            canvas._idle_draw_id = None
        canvas.figure.clear()
        canvas.toolbar = None
        toolbar.destroy()
        canvas.get_tk_widget().destroy()
        canvas.figure.set_canvas(None)
        del canvas, toolbar
        gc.collect()

    def _plot(self, key, container, figure):
        if key in self.plots:
            self._discard_plot(key)
        canvas = FigureCanvasTkAgg(figure, master=container)
        toolbar = NavigationToolbar2Tk(canvas, container, pack_toolbar=False)
        toolbar.pack(side="bottom", fill="x")
        canvas.get_tk_widget().pack(fill="both", expand=True)
        canvas.draw()
        self.plots[key] = canvas, toolbar
        return canvas

    def draw_map(self):
        if self.run is None:
            return
        name = self.field.get()
        if name in ("Ex", "Ey") and self.colormap.get() not in ("coolwarm", "RdBu_r"):
            self.colormap.set("RdBu_r")
        figure = field_figure(self.run, name, self.colormap.get())
        canvas = self._plot("map", self.map_plot, figure)
        canvas.mpl_connect("motion_notify_event", self._hover)
        stats = self.run.statistics(name)
        suffix = " • positive tensile; boundary cells use one-sided differences" if name in ("Ex", "Ey") else " • global z upward; positive settlement = −Uz"
        self.stats.set(f"{name}: min {stats['minimum']:.6g}, max {stats['maximum']:.6g}, mean {stats['mean']:.6g} {stats['unit']}" + suffix)

    def _hover(self, event):
        if self.run is None or event.inaxes is not self.plots["map"][0].figure.axes[0] or event.xdata is None or event.ydata is None:
            return
        value = self.run.inspect(event.xdata, event.ydata, self.field.get())
        if value is not None:
            self.hover.set(f"Cell center ({value['x_m']:.5g}, {value['y_m']:.5g}) m • {self.field.get()} = {value['value']:.7g} {value['unit']}" + (" • one-sided strain boundary" if value["one_sided_boundary"] else ""))

    def _refresh_profile_choices(self):
        names = [line.name for line in self.profile_lines]
        self.profile_box.configure(values=names)
        if self.profile_choice.get() not in names:
            self.profile_choice.set(names[0] if names else "")

    def add_profile(self):
        name, x1, y1, x2, y2, count = [var.get() for var in self.profile_vars]
        line = ProfileLine(name, (float(x1), float(y1)), (float(x2), float(y2)), int(count))
        if self.run is not None:
            self.run.profile(line)  # Validate bounds before changing saved lines.
        self.profile_lines = [p for p in self.profile_lines if p.name != name] + [line]
        self._refresh_profile_choices()
        self.profile_choice.set(name)
        if self.run is not None:
            self.run.document = replace(self.run.document, profiles=tuple(self.profile_lines))
            self.draw_profile()
            self.draw_map()
        self.status.set("Profile saved; sampled from cached arrays without rerunning the influence solver.")

    def remove_profile(self):
        self.profile_lines = [p for p in self.profile_lines if p.name != self.profile_choice.get()]
        self._refresh_profile_choices()
        if self.run is not None:
            self.run.document = replace(self.run.document, profiles=tuple(self.profile_lines))
            self.draw_map()
            if self.profile_lines:
                self.draw_profile()
            elif "profile" in self.plots:
                self._discard_plot("profile")

    def draw_profile(self):
        if self.run is None or not self.profile_choice.get():
            return
        line = next(p for p in self.profile_lines if p.name == self.profile_choice.get())
        self._plot("profile", self.profile_plot, profile_figure(self.run.profile(line), self.profile_field.get()))

    def _select_rectangle(self, event=None):
        selection = self.rectangles.selection()
        if selection:
            for variable, value in zip(self.rect_values, self.rectangles.item(selection[0], "values")):
                variable.set(value)

    def _rectangle_values(self):
        from .geometry import Rectangle
        values = [float(v.get()) for v in self.rect_values]
        Rectangle(*values)
        return values

    def add_rectangle(self):
        self.rectangles.insert("", "end", values=self._rectangle_values())
        self._dirty()

    def replace_rectangle(self):
        if not self.rectangles.selection():
            raise ValidationError("Select a rectangle to replace.")
        self.rectangles.item(self.rectangles.selection()[0], values=self._rectangle_values())
        self._dirty()

    def remove_rectangle(self):
        self.rectangles.delete(*self.rectangles.selection())
        self._dirty()

    def load_stations(self):
        csv_path = filedialog.askopenfilename(parent=self.root, title="Station observations CSV", filetypes=[("Station CSV", "*.csv")])
        if not csv_path:
            return
        meta_path = filedialog.askopenfilename(parent=self.root, title="Provenance, datum/sign/stage and fit/test roles JSON", filetypes=[("Observation metadata", "*.json")])
        if meta_path:
            self.observations = load_observations(csv_path, meta_path)
            self._refresh_station_info()
            self._clear_station_view()
            self.status.set("Observations loaded. Compute to evaluate them or calibrate with documented bounds.")

    def clear_stations(self):
        self.observations = None
        self._refresh_station_info()
        self._clear_station_view()
        self.status.set("Observations cleared. Compute before exporting a run with this change.")

    def _refresh_station_info(self):
        data = self.observations
        self.station_box.configure(values=[] if data is None else list(data.metadata.line_roles))
        self.station_choice.set("" if data is None else next(iter(data.metadata.line_roles)))
        self.station_info.set("No observations. Adriyala raw station coordinates/measurements remain unavailable." if data is None else f"{len(data.stations)} stations • {data.metadata.evidence} • {data.metadata.measurement_stage}\n{data.metadata.coordinate_reference} | {data.metadata.vertical_datum}")

    def _clear_station_view(self):
        self.station_metrics.delete(*self.station_metrics.get_children())
        if "stations" in self.plots:
            self._discard_plot("stations")

    def draw_stations(self):
        self.station_metrics.delete(*self.station_metrics.get_children())
        if self.run is None or self.run.evaluation is None:
            if "stations" in self.plots:
                self._discard_plot("stations")
            return
        # Plots always describe the run's observations, including after a new
        # upload. Recompute before replacing those numerical comparisons.
        if self.observations is not self.run.document.observations:
            self.status.set("New observation inputs are pending. Compute to refresh comparison plots.")
            return
        for name, m in self.run.evaluation.line_metrics.items():
            self.station_metrics.insert("", "end", values=(name, m["role"], m["count"], *(f"{m[k]:.7g}" for k in ("rmse_m", "mae_m", "bias_m"))))
        line = self.station_choice.get()
        if line:
            self._plot("stations", self.station_plot, station_figure(self.run, line))

    def load_fit_settings(self):
        path = filedialog.askopenfilename(parent=self.root, title="Calibration settings JSON", filetypes=[("Fit settings", "*.json")])
        if path:
            self._fill_fit_settings(load_calibration_settings(path))

    def close(self):
        if self.busy:
            messagebox.showinfo("Operation in progress", "Wait for the current operation before closing.", parent=self.root)
            return
        self.root.after_cancel(self._poll_id)
        self._clear_plots()
        self.root.destroy()


def launch(project_path=None):
    document = load_document(project_path) if project_path else None
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise ValidationError(f"The workbench needs a graphical desktop with Tk: {exc}") from exc
    DesktopApp(root, document)
    root.mainloop()
