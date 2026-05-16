import csv
import time
import tkinter as tk
from dataclasses import dataclass, field, asdict
from datetime import datetime
from tkinter import ttk, filedialog, messagebox
from typing import Callable, Dict, List, Optional


@dataclass
class ContextParameters:
    target_person: str = "Chirurgie"
    instrument_type: str = "Pinzette"
    urgency_level: str = "Normal"
    side_direction: str = "Mitte"
    speed_profile: str = "Standard"


@dataclass
class ActionRequest:
    action: str
    params: ContextParameters
    selected_at: float


@dataclass
class LogEntry:
    timestamp: str
    event_type: str
    details: str
    latency_ms: float = 0.0
    duration_ms: float = 0.0
    scenario: str = ""
    mode: str = ""


@dataclass
class Scenario:
    name: str
    description: str
    preload_params: ContextParameters
    recommended_actions: List[str]


class EventLogger:
    def __init__(self):
        self.entries: List[LogEntry] = []

    def log(self, event_type: str, details: str, scenario: str, mode: str,
            latency_ms: float = 0.0, duration_ms: float = 0.0) -> LogEntry:
        entry = LogEntry(
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            event_type=event_type,
            details=details,
            latency_ms=latency_ms,
            duration_ms=duration_ms,
            scenario=scenario,
            mode=mode,
        )
        self.entries.append(entry)
        return entry

    def export_csv(self, path: str) -> None:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "timestamp", "event_type", "details", "latency_ms",
                    "duration_ms", "scenario", "mode"
                ],
            )
            writer.writeheader()
            for e in self.entries:
                writer.writerow(asdict(e))


class RobotSimulator:
    VALID_STATES = ["idle", "ready", "executing", "paused", "fehler", "emergency stop"]

    def __init__(self, on_state_change: Callable[[], None], logger: EventLogger):
        self.state = "ready"
        self.current_action: Optional[ActionRequest] = None
        self.queue: List[ActionRequest] = []
        self.completed: List[str] = []
        self.on_state_change = on_state_change
        self.logger = logger
        self._tk_root: Optional[tk.Tk] = None
        self._after_token = None
        self._execution_started_at = 0.0

    def bind_root(self, root: tk.Tk) -> None:
        self._tk_root = root

    def select_and_queue(self, request: ActionRequest) -> None:
        if self.state in {"fehler", "emergency stop"}:
            return
        if self.current_action is None:
            self.queue.insert(0, request)
        else:
            self.queue.append(request)
        self.on_state_change()

    def execute_next(self, scenario: str, mode: str) -> None:
        if self.state in {"fehler", "emergency stop"}:
            return
        if self.current_action is not None or not self.queue:
            return
        self.current_action = self.queue.pop(0)
        self.state = "executing"
        self._execution_started_at = time.time()
        latency_ms = (self._execution_started_at - self.current_action.selected_at) * 1000
        duration_ms = self._estimate_duration_ms(self.current_action)
        self.logger.log(
            "aktion_ausführung",
            self._describe_action(self.current_action),
            scenario=scenario,
            mode=mode,
            latency_ms=latency_ms,
            duration_ms=duration_ms,
        )
        self.on_state_change()
        if self._tk_root is not None:
            self._after_token = self._tk_root.after(int(duration_ms), lambda: self._complete_current(scenario, mode))

    def _complete_current(self, scenario: str, mode: str) -> None:
        if self.current_action is None or self.state != "executing":
            return
        duration_ms = (time.time() - self._execution_started_at) * 1000
        desc = self._describe_action(self.current_action)
        self.completed.insert(0, f"{self.current_action.action} ({duration_ms:.0f}ms)")
        self.completed = self.completed[:8]
        self.logger.log("aktion_abgeschlossen", desc, scenario=scenario, mode=mode, duration_ms=duration_ms)
        self.current_action = None
        self.state = "ready"
        self._after_token = None
        self.on_state_change()

    def cancel_current(self, scenario: str, mode: str) -> None:
        if self.state == "executing" and self.current_action is not None:
            if self._tk_root is not None and self._after_token is not None:
                self._tk_root.after_cancel(self._after_token)
            desc = self._describe_action(self.current_action)
            self.logger.log("aktion_abgebrochen", desc, scenario=scenario, mode=mode)
            self.current_action = None
            self.state = "ready"
            self._after_token = None
            self.on_state_change()

    def not_halt(self, scenario: str, mode: str) -> None:
        if self._tk_root is not None and self._after_token is not None:
            self._tk_root.after_cancel(self._after_token)
        self._after_token = None
        self.state = "emergency stop"
        self.current_action = None
        self.logger.log("not_halt", "Not-Halt aktiviert", scenario=scenario, mode=mode)
        self.on_state_change()

    def set_fehler(self, message: str, scenario: str, mode: str) -> None:
        self.state = "fehler"
        self.logger.log("fehler", message, scenario=scenario, mode=mode)
        self.on_state_change()

    def reset(self, scenario: str, mode: str) -> None:
        if self._tk_root is not None and self._after_token is not None:
            self._tk_root.after_cancel(self._after_token)
        self._after_token = None
        self.state = "ready"
        self.current_action = None
        self.logger.log("status_zurückgesetzt", "Roboterstatus zurückgesetzt", scenario=scenario, mode=mode)
        self.on_state_change()

    def clear_queue(self, scenario: str, mode: str) -> None:
        self.queue.clear()
        self.logger.log("warteschlange_geleert", "Ausstehende Warteschlange geleert", scenario=scenario, mode=mode)
        self.on_state_change()

    @staticmethod
    def _estimate_duration_ms(request: ActionRequest) -> int:
        base = {
            "Instrument übergeben": 2400,
            "In Bereitschaft fahren": 1300,
            "Zur Bedienperson fahren": 1600,
            "Zurückziehen / zurückfahren": 1500,
            "Position halten": 800,
            "In sichere Pose fahren": 1800,
            "Aktuelle Aktion abbrechen": 500,
        }.get(request.action, 1200)
        urgency_mod = {"Niedrig": 200, "Normal": 0, "Hoch": -250, "Kritisch": -500}
        speed_mod = {"Langsam": 300, "Standard": 0, "Schnell": -300}
        return max(400, base + urgency_mod.get(request.params.urgency_level, 0) + speed_mod.get(request.params.speed_profile, 0))

    @staticmethod
    def _describe_action(request: ActionRequest) -> str:
        p = request.params
        return (
            f"{request.action} | target={p.target_person}, instrument={p.instrument_type}, "
            f"urgency={p.urgency_level}, side={p.side_direction}, speed={p.speed_profile}"
        )


class WoZApp(tk.Tk):
    ACTION_CATEGORIES: Dict[str, List[str]] = {
        "Primär": ["Instrument übergeben", "Zur Bedienperson fahren", "In Bereitschaft fahren"],
        "Positionierung": ["Zurückziehen / zurückfahren", "Position halten", "In sichere Pose fahren"],
        "Steuerung": ["Aktuelle Aktion abbrechen"],
    }

    def __init__(self):
        super().__init__()
        self.title("WoZ-Assistentenarm Zauberer-Oberfläche (Prototyp)")
        self.geometry("1400x860")
        self.minsize(1200, 760)

        self.logger = EventLogger()
        self.mode_var = tk.StringVar(value="Studie")
        self.selected_action_var = tk.StringVar(value="Keine Aktion ausgewählt")
        self.status_var = tk.StringVar(value="ready")

        self.context = ContextParameters()
        self.scenarios = self._build_scenarios()
        self.scenario_var = tk.StringVar(value=self.scenarios[0].name)

        self.robot = RobotSimulator(self.refresh_state, self.logger)
        self.robot.bind_root(self)

        self.param_vars: Dict[str, tk.StringVar] = {}
        self.log_text: Optional[tk.Text] = None
        self.recommended_text: Optional[tk.Text] = None

        self._build_ui()
        self._bind_shortcuts()
        self.load_scenario(self.scenario_var.get(), initial=True)
        self.refresh_state()

    def _build_scenarios(self) -> List[Scenario]:
        return [
            Scenario(
                "Einfache Übergabe",
                "Routine-Übergabe von Bereitschaft zur Fachkraft und zurück.",
                ContextParameters("Chirurgie", "Skalpell", "Normal", "Rechts", "Standard"),
                ["Zur Bedienperson fahren", "Instrument übergeben", "Zurückziehen / zurückfahren", "In Bereitschaft fahren"],
            ),
            Scenario(
                "Unterbrochene Übergabe",
                "Übergabe starten, dann abbrechen und in sichere Pose zurückkehren.",
                ContextParameters("Pflegekraft", "Spritze", "Hoch", "Links", "Schnell"),
                ["Zur Bedienperson fahren", "Instrument übergeben", "Aktuelle Aktion abbrechen", "In sichere Pose fahren"],
            ),
            Scenario(
                "Dringende Neupriorisierung",
                "Dringende Anfrage während laufender Positionierung.",
                ContextParameters("Leitende Chirurgie", "Klemme", "Kritisch", "Mitte", "Schnell"),
                ["Position halten", "Aktuelle Aktion abbrechen", "Zur Bedienperson fahren", "Instrument übergeben"],
            ),
        ]

    def _build_ui(self):
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=4)
        self.columnconfigure(2, weight=3)
        self.rowconfigure(0, weight=8)
        self.rowconfigure(1, weight=3)

        left = ttk.LabelFrame(self, text="Live-Steuerung (Schnellaktionen)")
        left.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self._build_left_panel(left)

        center = ttk.LabelFrame(self, text="Roboterstatus & Ausführung")
        center.grid(row=0, column=1, sticky="nsew", padx=6, pady=6)
        self._build_center_panel(center)

        right = ttk.LabelFrame(self, text="Szenario + Kontext + Modus")
        right.grid(row=0, column=2, sticky="nsew", padx=6, pady=6)
        self._build_right_panel(right)

        bottom = ttk.LabelFrame(self, text="Ereignisprotokoll")
        bottom.grid(row=1, column=0, columnspan=3, sticky="nsew", padx=6, pady=6)
        self._build_bottom_panel(bottom)

    def _build_left_panel(self, parent):
        row = 0
        for cat, actions in self.ACTION_CATEGORIES.items():
            ttk.Label(parent, text=cat, font=("TkDefaultFont", 10, "bold")).grid(row=row, column=0, sticky="w", pady=(8, 3), padx=6)
            row += 1
            for action in actions:
                btn = tk.Button(parent, text=action, font=("TkDefaultFont", 12, "bold"), height=2,
                                command=lambda a=action: self.select_action(a), wraplength=250)
                btn.grid(row=row, column=0, sticky="ew", padx=6, pady=3)
                row += 1

        ttk.Separator(parent, orient="horizontal").grid(row=row, column=0, sticky="ew", padx=6, pady=8)
        row += 1
        self.emergency_btn = tk.Button(parent, text="NOT-HALT (Leertaste)", bg="#c62828", fg="white", font=("TkDefaultFont", 13, "bold"),
                                       height=2, command=self.do_not_halt)
        self.emergency_btn.grid(row=row, column=0, sticky="ew", padx=6, pady=6)
        parent.columnconfigure(0, weight=1)

    def _build_center_panel(self, parent):
        for i in range(8):
            parent.rowconfigure(i, weight=0)
        parent.columnconfigure(0, weight=1)

        ttk.Label(parent, text="Status:", font=("TkDefaultFont", 11, "bold")).grid(row=0, column=0, sticky="w", padx=8, pady=(10, 3))
        self.state_label = ttk.Label(parent, textvariable=self.status_var, font=("TkDefaultFont", 14, "bold"), foreground="green")
        self.state_label.grid(row=1, column=0, sticky="w", padx=8)

        ttk.Label(parent, text="Ausgewählte Aktion:", font=("TkDefaultFont", 10, "bold")).grid(row=2, column=0, sticky="w", padx=8, pady=(12, 3))
        ttk.Label(parent, textvariable=self.selected_action_var, wraplength=520).grid(row=3, column=0, sticky="w", padx=8)

        button_row = ttk.Frame(parent)
        button_row.grid(row=4, column=0, sticky="ew", padx=8, pady=8)
        button_row.columnconfigure((0, 1, 2), weight=1)
        ttk.Button(button_row, text="Bestätigen / Ausführen (Enter)", command=self.confirm_and_execute).grid(row=0, column=0, sticky="ew", padx=2)
        ttk.Button(button_row, text="Laufende Aktion abbrechen", command=self.cancel_current).grid(row=0, column=1, sticky="ew", padx=2)
        ttk.Button(button_row, text="Fehler simulieren", command=self.inject_fehler).grid(row=0, column=2, sticky="ew", padx=2)

        queue_frame = ttk.LabelFrame(parent, text="Warteschlange / Aktuell / Abgeschlossen")
        queue_frame.grid(row=5, column=0, sticky="nsew", padx=8, pady=6)
        queue_frame.columnconfigure((0, 1, 2), weight=1)

        self.current_lbl = ttk.Label(queue_frame, text="Aktuell: -", wraplength=180)
        self.current_lbl.grid(row=0, column=0, sticky="nw", padx=5, pady=4)
        self.queue_lbl = ttk.Label(queue_frame, text="Warteschlange: -", wraplength=180)
        self.queue_lbl.grid(row=0, column=1, sticky="nw", padx=5, pady=4)
        self.completed_lbl = ttk.Label(queue_frame, text="Abgeschlossen: -", wraplength=220)
        self.completed_lbl.grid(row=0, column=2, sticky="nw", padx=5, pady=4)

        safety_frame = ttk.Frame(parent)
        safety_frame.grid(row=6, column=0, sticky="ew", padx=8, pady=(8, 4))
        ttk.Button(safety_frame, text="Warteschlange leeren", command=self.clear_queue).pack(side="left", padx=2)
        ttk.Button(safety_frame, text="Zur sicheren Pose", command=lambda: self.select_action("In sichere Pose fahren")).pack(side="left", padx=2)
        ttk.Button(safety_frame, text="Roboterstatus zurücksetzen", command=self.reset_robot).pack(side="left", padx=2)

    def _build_right_panel(self, parent):
        parent.columnconfigure(0, weight=1)

        mode_frame = ttk.LabelFrame(parent, text="Modus")
        mode_frame.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        ttk.Radiobutton(mode_frame, text="Studie", variable=self.mode_var, value="Studie", command=self.on_modus_geändert).pack(anchor="w", padx=4, pady=2)
        ttk.Radiobutton(mode_frame, text="Training", variable=self.mode_var, value="Training", command=self.on_modus_geändert).pack(anchor="w", padx=4, pady=2)

        sc_frame = ttk.LabelFrame(parent, text="Szenarien")
        sc_frame.grid(row=1, column=0, sticky="ew", padx=6, pady=6)
        names = [s.name for s in self.scenarios]
        combo = ttk.Combobox(sc_frame, values=names, textvariable=self.scenario_var, state="readonly")
        combo.pack(fill="x", padx=5, pady=4)
        combo.bind("<<ComboboxSelected>>", lambda e: self.load_scenario(self.scenario_var.get()))
        ttk.Button(sc_frame, text="Szenario neu laden", command=lambda: self.load_scenario(self.scenario_var.get())).pack(fill="x", padx=5, pady=3)

        self.scenario_desc_lbl = ttk.Label(sc_frame, text="", wraplength=340, foreground="#333")
        self.scenario_desc_lbl.pack(fill="x", padx=5, pady=4)
        self.recommended_text = tk.Text(sc_frame, height=5, wrap="word", state="disabled")
        self.recommended_text.pack(fill="x", padx=5, pady=4)

        ctx = ttk.LabelFrame(parent, text="Kontextparameter")
        ctx.grid(row=2, column=0, sticky="nsew", padx=6, pady=6)
        fields = {
            "target_person": ["Chirurgie", "Pflegekraft", "Leitende Chirurgie", "Assistenzarzt/-ärztin"],
            "instrument_type": ["Pinzette", "Skalpell", "Spritze", "Klemme", "Tupfer"],
            "urgency_level": ["Niedrig", "Normal", "Hoch", "Kritisch"],
            "side_direction": ["Links", "Rechts", "Mitte"],
            "speed_profile": ["Langsam", "Standard", "Schnell"],
        }
        for i, (name, options) in enumerate(fields.items()):
            ttk.Label(ctx, text=name.replace("_", " ").title()).grid(row=i, column=0, sticky="w", padx=4, pady=3)
            var = tk.StringVar(value=options[0])
            self.param_vars[name] = var
            cb = ttk.Combobox(ctx, values=options, textvariable=var, state="readonly")
            cb.grid(row=i, column=1, sticky="ew", padx=4, pady=3)
            cb.bind("<<ComboboxSelected>>", lambda e, n=name: self.on_param_change(n))
        ctx.columnconfigure(1, weight=1)

    def _build_bottom_panel(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        self.log_text = tk.Text(parent, height=10, state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        controls = ttk.Frame(parent)
        controls.grid(row=1, column=0, sticky="ew", padx=5, pady=(0, 5))
        ttk.Button(controls, text="CSV exportieren", command=self.export_logs).pack(side="left")
        ttk.Button(controls, text="Protokollansicht leeren", command=self.clear_log_view).pack(side="left", padx=4)

    def _bind_shortcuts(self):
        self.bind("<Return>", lambda e: self.confirm_and_execute())
        self.bind("<space>", lambda e: self.do_not_halt())
        self.bind("1", lambda e: self.select_action("Instrument übergeben"))
        self.bind("2", lambda e: self.select_action("Zur Bedienperson fahren"))
        self.bind("3", lambda e: self.select_action("In Bereitschaft fahren"))
        self.bind("4", lambda e: self.select_action("In sichere Pose fahren"))
        self.bind("c", lambda e: self.cancel_current())

    def _current_mode(self) -> str:
        return self.mode_var.get()

    def _current_scenario(self) -> str:
        return self.scenario_var.get()

    def _get_context(self) -> ContextParameters:
        return ContextParameters(**{k: v.get() for k, v in self.param_vars.items()})

    def select_action(self, action: str):
        self.selected_action_var.set(action)
        self.logger_and_view("aktion_ausgewählt", f"Ausgewählte Aktion: {action}")

    def confirm_and_execute(self):
        action = self.selected_action_var.get()
        if action == "Keine Aktion ausgewählt":
            self.logger_and_view("warnung", "Ausführung ignoriert: keine Aktion ausgewählt")
            return
        req = ActionRequest(action=action, params=self._get_context(), selected_at=time.time())
        self.robot.select_and_queue(req)
        self.robot.execute_next(self._current_scenario(), self._current_mode())

    def cancel_current(self):
        self.robot.cancel_current(self._current_scenario(), self._current_mode())

    def do_not_halt(self):
        self.robot.not_halt(self._current_scenario(), self._current_mode())

    def clear_queue(self):
        self.robot.clear_queue(self._current_scenario(), self._current_mode())

    def reset_robot(self):
        self.robot.reset(self._current_scenario(), self._current_mode())

    def inject_fehler(self):
        self.robot.set_fehler("Simulierter Fehlerzustand für Wiederherstellungsübung", self._current_scenario(), self._current_mode())

    def on_modus_geändert(self):
        self.logger_and_view("modus_geändert", f"Modus changed to {self._current_mode()}")

    def on_param_change(self, name: str):
        self.logger_and_view("parameter_änderung", f"{name} -> {self.param_vars[name].get()}")

    def load_scenario(self, scenario_name: str, initial: bool = False):
        s = next((x for x in self.scenarios if x.name == scenario_name), None)
        if s is None:
            return
        for k, v in asdict(s.preload_params).items():
            if k in self.param_vars:
                self.param_vars[k].set(v)
        self.scenario_desc_lbl.configure(text=s.description)
        self.recommended_text.configure(state="normal")
        self.recommended_text.delete("1.0", "end")
        self.recommended_text.insert("1.0", "Recommended flow:\n- " + "\n- ".join(s.recommended_actions))
        self.recommended_text.configure(state="disabled")
        self.selected_action_var.set("Keine Aktion ausgewählt")
        self.robot.clear_queue(self._current_scenario(), self._current_mode())
        self.robot.reset(self._current_scenario(), self._current_mode())
        self.logger_and_view("szenario_start" if initial else "szenario_gewechselt", f"Szenario geladen: {s.name}")

    def logger_and_view(self, event_type: str, details: str):
        entry = self.logger.log(event_type, details, self._current_scenario(), self._current_mode())
        self._append_log(entry)

    def refresh_state(self):
        st = self.robot.state
        self.status_var.set(st)
        color = {"ready": "green", "executing": "blue", "paused": "#bb6d00", "fehler": "#b71c1c", "emergency stop": "#c62828", "idle": "gray"}.get(st, "black")
        self.state_label.configure(foreground=color)

        cur = self.robot.current_action.action if self.robot.current_action else "-"
        q = ", ".join(r.action for r in self.robot.queue) if self.robot.queue else "-"
        done = "\n".join(self.robot.completed[:6]) if self.robot.completed else "-"

        self.current_lbl.configure(text=f"Current: {cur}")
        self.queue_lbl.configure(text=f"Queue: {q}")
        self.completed_lbl.configure(text=f"Completed:\n{done}")

        if st in {"fehler", "emergency stop"}:
            self.selected_action_var.set("Keine Aktion ausgewählt")

    def _append_log(self, entry: LogEntry):
        if self.log_text is None:
            return
        line = (
            f"[{entry.timestamp}] {entry.event_type} | {entry.details} | "
            f"lat={entry.latency_ms:.1f}ms dur={entry.duration_ms:.1f}ms | "
            f"scenario={entry.scenario} mode={entry.mode}\n"
        )
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def export_logs(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        self.logger.export_csv(path)
        messagebox.showinfo("Export", f"Logs exported to:\n{path}")

    def clear_log_view(self):
        if self.log_text is None:
            return
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")


if __name__ == "__main__":
    app = WoZApp()
    app.mainloop()
